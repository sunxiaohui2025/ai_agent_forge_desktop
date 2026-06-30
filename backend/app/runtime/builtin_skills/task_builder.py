"""Built-in callable Skill: 自动化任务生成器 (create_task).

Mirrors the 专家生成器 (expert_builder) flow but for scheduled automation
Tasks. The LLM drives a two-step flow from a natural-language request such as
"帮我创建一个自动化任务，任务是要每天汇总新闻，调用资讯助手，执行时间是每天早上9点"。

  1. action="list_agents"
     Return the catalog of available experts (enabled Agents) — code + name +
     description — so the model can pick which expert the task should invoke.

  2. action="create"
     Persist a new Task bound to the chosen agent. The model supplies the task
     name, the prompt to send the expert each run, and a schedule. The schedule
     can be given directly (schedule_type + schedule_value) OR as a plain
     interval (interval_minutes / interval_hours / interval_days / cron / once),
     which we normalise to the cron/once form the scheduler understands.

Registered as an `atomic.callable` Skill (source_json.callable =
``app.runtime.builtin_skills.task_builder:run``). The owner user id is injected
by the agent runner as ``_owner_user_id`` (tasks are strictly per-user) since a
callable Skill only receives the model-supplied arguments otherwise.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from ...db.session import SessionLocal
from ...db.models import Agent, Task

SKILL_CODE = "create_task"

# Default time-of-day used when a day/week-level interval doesn't name an hour.
_DEFAULT_HOUR = 9


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _interval_to_cron(payload: dict[str, Any]) -> str | None:
    """Best-effort: turn an interval description into a 5-field cron expression.

    Supports interval_minutes / interval_hours / interval_days. Returns None when
    no interval field is present so the caller can fall back to other inputs.
    """
    mins = _int_or_none(payload.get("interval_minutes"))
    hours = _int_or_none(payload.get("interval_hours"))
    days = _int_or_none(payload.get("interval_days"))
    at_hour = _int_or_none(payload.get("at_hour"))
    at_minute = _int_or_none(payload.get("at_minute")) or 0

    if mins and mins > 0:
        if mins >= 60 and mins % 60 == 0:
            return f"0 */{mins // 60} * * *"
        return f"*/{max(1, min(59, mins))} * * * *"
    if hours and hours > 0:
        if hours >= 24 and hours % 24 == 0:
            return f"{at_minute} {at_hour if at_hour is not None else _DEFAULT_HOUR} */{hours // 24} * *"
        return f"{at_minute} */{max(1, min(23, hours))} * * *"
    if days and days > 0:
        return f"{at_minute} {at_hour if at_hour is not None else _DEFAULT_HOUR} */{max(1, days)} * *"
    return None


async def _list_agents() -> dict[str, Any]:
    async with SessionLocal() as db:
        agents = (await db.execute(
            select(Agent).where(Agent.enabled.is_(True)).order_by(Agent.id)
        )).scalars().all()
    return {
        "agents": [
            {"code": a.code, "name": a.name,
             "description": (a.description or "")[:280]}
            for a in agents
        ],
        "hint": (
            "请从以上专家中为自动化任务挑选一个最合适的执行专家（用 agent_code 提交，"
            "也可用 agent_name）。然后用 action='create' 提交任务，必须包含 name(任务名称)、"
            "agent_code(执行专家)、prompt_text(每次执行时发给专家的指令)、调度信息。"
            "调度可直接给 schedule_type+schedule_value(cron 5 段表达式或 once 的 ISO 时间)，"
            "或给出间隔 interval_minutes / interval_hours / interval_days(可选 at_hour/at_minute)。"
        ),
    }


async def _resolve_agent(db, payload: dict[str, Any]) -> Agent | None:
    agent_id = _int_or_none(payload.get("agent_id"))
    if agent_id is not None:
        a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if a:
            return a
    code = str(payload.get("agent_code") or payload.get("agent") or "").strip()
    if code:
        a = (await db.execute(select(Agent).where(Agent.code == code))).scalar_one_or_none()
        if a:
            return a
    name = str(payload.get("agent_name") or payload.get("agent") or "").strip()
    if name:
        a = (await db.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
        if a:
            return a
    return None


def _normalise_schedule(payload: dict[str, Any]) -> tuple[str, str | None]:
    """Return (schedule_type, schedule_value) from whatever the model supplied."""
    stype = str(payload.get("schedule_type") or "").strip().lower()
    sval = payload.get("schedule_value")
    sval = str(sval).strip() if sval not in (None, "") else None

    # Explicit cron/once with a value → trust it.
    if stype == "cron" and sval:
        return "cron", sval
    if stype == "once" and sval:
        return "once", sval
    if stype == "manual":
        return "manual", None

    # No usable explicit schedule → derive a cron from interval fields.
    cron = _interval_to_cron(payload)
    if cron:
        return "cron", cron
    # A bare cron expression handed in schedule_value without a type.
    if sval and len(sval.split()) == 5:
        return "cron", sval
    if sval and re.match(r"^\d{4}-\d{2}-\d{2}", sval):
        return "once", sval
    return "manual", None


async def _create(payload: dict[str, Any]) -> dict[str, Any]:
    owner_user_id = _int_or_none(payload.get("_owner_user_id"))
    if owner_user_id is None:
        return {"ok": False, "error": "无法确定任务归属用户，请在对话中调用本工具创建任务"}

    name = str(payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "缺少任务名称 name"}

    prompt_text = str(payload.get("prompt_text") or payload.get("prompt") or "").strip()
    if not prompt_text:
        return {"ok": False, "error": "缺少 prompt_text（每次执行时发送给专家的指令内容）"}

    description = str(payload.get("description") or "").strip() or None
    timezone = str(payload.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"

    schedule_type, schedule_value = _normalise_schedule(payload)

    # Validate the schedule before persisting so a bad cron doesn't silently
    # create a never-firing task.
    from ...services.croniter_compat import _next_cron_fire, next_fire_time
    if schedule_type == "cron":
        try:
            _next_cron_fire(schedule_value or "", timezone)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"调度表达式无效: {e}", "schedule_value": schedule_value}
    elif schedule_type == "once":
        try:
            if next_fire_time("once", schedule_value or "", timezone) is None:
                return {"ok": False, "error": "一次性执行时间已过，请给出未来的时间"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"执行时间无效: {e}"}

    async with SessionLocal() as db:
        agent = await _resolve_agent(db, payload)
        if not agent or not agent.enabled:
            return {
                "ok": False,
                "error": "未找到可用的执行专家，请先用 action='list_agents' 查看可选专家，再用 agent_code 指定",
            }

        t = Task(
            owner_user_id=owner_user_id,
            agent_id=agent.id,
            name=name[:128],
            description=description,
            prompt_text=prompt_text,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            timezone=timezone,
            max_runtime_seconds=1800,
            concurrency_policy="skip",
            notify_channels_json=["inapp"],
            notify_on="always",
            enabled=True,
        )
        db.add(t)
        await db.commit()
        await db.refresh(t)

        # Arm the scheduler exactly like the REST create path does.
        if t.enabled and t.schedule_type in ("cron", "once") and t.schedule_value:
            try:
                from ...services.task_runner import get_scheduler
                get_scheduler().schedule(t.id, t.schedule_type, t.schedule_value, t.timezone)
            except Exception:  # noqa: BLE001 — scheduling failure shouldn't lose the row
                pass

        sched_desc = (
            f"周期 cron `{t.schedule_value}`" if t.schedule_type == "cron"
            else f"单次 {t.schedule_value}" if t.schedule_type == "once"
            else "仅手动触发"
        )
        return {
            "ok": True,
            "task": {
                "id": t.id,
                "name": t.name,
                "agent_id": t.agent_id,
                "agent_name": agent.name,
                "schedule_type": t.schedule_type,
                "schedule_value": t.schedule_value,
                "timezone": t.timezone,
                "enabled": t.enabled,
            },
            "message": (
                f"已创建自动化任务「{t.name}」，由专家「{agent.name}」执行，调度：{sched_desc}。"
                "可在「自动化」中查看、运行或编辑。"
            ),
        }


async def run(**kwargs: Any) -> dict[str, Any]:
    """Skill entrypoint. Dispatch on ``action``.

    action="list_agents" → enumerate available experts.
    action="create"      → create the Task from structured fields.
    Defaults to list_agents so a first call without args is still useful.
    """
    action = str(kwargs.get("action") or "").strip().lower()
    if action in ("", "list", "list_agents", "agents"):
        return await _list_agents()
    if action == "create":
        return await _create(kwargs)
    return {
        "ok": False,
        "error": f"未知 action: {action}",
        "hint": "action 必须是 'list_agents' 或 'create'",
    }
