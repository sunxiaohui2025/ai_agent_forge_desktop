"""Task scheduling + execution.

Runs scheduled tasks in-process via APScheduler-free, lightweight asyncio.
Each task gets a per-task asyncio.Lock to enforce 'skip' concurrency, and
each run calls the existing AgentRunner with a fresh Conversation. SSE
events from the runner are consumed and persisted into the messages table
so the user can revisit the run as a regular conversation.

We intentionally do NOT depend on apscheduler — we maintain our own
asyncio.Task per cron entry that sleeps until next fire time.
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from .croniter_compat import next_fire_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..db.session import SessionLocal
from ..db.models import (
    Task, TaskRun, Notification, User, Conversation, Message, Agent,
    AgentSkill, AgentMCP, AgentPack, Skill, MCPConnector, SolutionPack, Model,
)
from ..runtime.agent_runner import AgentRunner, AgentContext
from . import mailer

logger = logging.getLogger(__name__)


# ---------- per-task lock registry ----------
_task_locks: dict[int, asyncio.Lock] = {}


def _lock_for(task_id: int) -> asyncio.Lock:
    lk = _task_locks.get(task_id)
    if lk is None:
        lk = asyncio.Lock()
        _task_locks[task_id] = lk
    return lk


# ---------- agent context loading (mirrors api/chat.py) ----------
async def _load_agent_context(db: AsyncSession, agent_id: int) -> AgentContext:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
    skill_ids = [r[0] for r in (await db.execute(
        select(AgentSkill.skill_id).where(AgentSkill.agent_id == a.id))).all()]
    mcp_ids = [r[0] for r in (await db.execute(
        select(AgentMCP.mcp_id).where(AgentMCP.agent_id == a.id))).all()]
    pack_ids = [r[0] for r in (await db.execute(
        select(AgentPack.pack_id).where(AgentPack.agent_id == a.id))).all()]
    skills = list((await db.execute(
        select(Skill).where(Skill.id.in_(skill_ids), Skill.enabled.is_(True)))).scalars().all()) if skill_ids else []
    mcps = list((await db.execute(
        select(MCPConnector).where(MCPConnector.id.in_(mcp_ids), MCPConnector.enabled.is_(True)))).scalars().all()) if mcp_ids else []
    packs = list((await db.execute(
        select(SolutionPack).where(SolutionPack.id.in_(pack_ids), SolutionPack.enabled.is_(True)))).scalars().all()) if pack_ids else []
    model = (await db.execute(select(Model).where(Model.id == a.default_model_id))).scalar_one_or_none() if a.default_model_id else None
    # Fallback to the first enabled model when the expert has none bound.
    if model is None:
        model = (await db.execute(
            select(Model).where(Model.enabled.is_(True)).order_by(Model.id)
        )).scalars().first()
    fb = (await db.execute(select(Model).where(Model.id == a.fallback_model_id))).scalar_one_or_none() if a.fallback_model_id else None
    # Scheduled/headless task runs have NO human present to answer interactive
    # permission prompts. If we ran in "task mode" (workspace_dir set →
    # permission_mode="ask"), the very first gated tool (Write/Edit/Bash) would
    # call the can_use_tool callback, emit a permission_request, and block on a
    # Future that nobody ever resolves — so the run hangs in "running" until it
    # times out / gets reaped, and under the `skip` concurrency policy every
    # later cron fire is skipped. That is exactly the "一直执行中" bug.
    #
    # Tasks are Q&A prompts, so we force read-only CHAT mode: the agent answers
    # the prompt with safe read-only tools (Read/Glob/Grep/WebSearch) and can
    # never request an interactive approval. This also avoids granting the agent
    # autonomous Bash/Write access to its broad work_dir on every run.
    return AgentContext(agent=a, skills=skills, mcps=mcps, packs=packs, model=model, fallback_model=fb, history=[],
                        workspace_dir=None,
                        permission_mode=None)


# Grace period beyond a task's max_runtime before a still-"running" run is
# considered stale (orphaned by a crashed/killed process) and force-closed.
_STALE_GRACE_SECONDS = 120


async def _reap_stale_run_for_task(db: AsyncSession, task: Task) -> bool:
    """If this task's last run is wedged in 'running' past its allowed runtime,
    mark it failed so a new run can proceed. Returns True if a stale run was reaped.

    This is the runtime counterpart to `_reconcile_orphan_runs` (which only runs
    on startup). Without it, a run orphaned by a killed worker — or one whose
    in-process timeout never fired — blocks every future run under the default
    `skip` concurrency policy, leaving the task stuck "执行中" forever.
    """
    if task.last_run_status != "running" or not task.last_run_id:
        return False
    run = (await db.execute(select(TaskRun).where(TaskRun.id == task.last_run_id))).scalar_one_or_none()
    if not run or run.status != "running":
        return False
    started = run.started_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    budget = max(10, int(task.max_runtime_seconds or 1800)) + _STALE_GRACE_SECONDS
    if started is not None and (now - started).total_seconds() < budget:
        return False  # still within its allowed runtime — genuinely running
    run.status = "failed"
    run.finished_at = now
    if started is not None:
        run.duration_ms = int((now - started).total_seconds() * 1000)
    run.error_message = "执行超时未结束（worker 中断或卡死），已由系统自动清理。请重新运行。"
    task.last_run_status = "failed"
    task.last_run_at = now
    await db.commit()
    logger.warning("Reaped stale running run %s for task %s", run.id, task.id)
    # Notify the owner that the run was force-closed. Without this a task that
    # hangs (e.g. a stalled model stream) is silently reaped and the user never
    # learns the run failed — they just see a permanently blank conversation.
    owner = (await db.execute(select(User).where(User.id == task.owner_user_id))).scalar_one_or_none()
    if owner:
        try:
            await _notify_run(db, task, run, owner)
        except Exception as e:  # noqa: BLE001 — notification failure must not break reaping
            logger.warning("notify after reap failed for task %s: %s", task.id, e)
    return True


# ---------- run a single task ----------
async def execute_task(task_id: int, *, triggered_by: str = "manual",
                        triggered_user_id: int | None = None) -> int | None:
    """Execute a task once. Returns the TaskRun id (or None if skipped/missing)."""
    async with SessionLocal() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
        if not task:
            return None
        owner = (await db.execute(select(User).where(User.id == task.owner_user_id))).scalar_one_or_none()
        if not owner or owner.status != "active":
            return None
        if not task.enabled and triggered_by == "cron":
            return None

        # Self-heal: force-close a run wedged in 'running' past its runtime budget
        # before applying the concurrency policy, so a stale run never blocks
        # future runs indefinitely.
        await _reap_stale_run_for_task(db, task)

        # concurrency skip
        if task.concurrency_policy == "skip" and task.last_run_status == "running":
            run_no = await _next_run_no(db, task_id)
            run = TaskRun(task_id=task_id, run_no=run_no, triggered_by=triggered_by,
                          triggered_user_id=triggered_user_id, status="skipped",
                          error_message="上一次执行尚未完成，已按并发策略跳过本次")
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return run.id

        # create conversation + run row
        conv = Conversation(user_id=owner.id, agent_id=task.agent_id,
                             title=f"[任务] {task.name}")
        db.add(conv)
        await db.flush()

        run_no = await _next_run_no(db, task_id)
        run = TaskRun(
            task_id=task_id, run_no=run_no, triggered_by=triggered_by,
            triggered_user_id=triggered_user_id, status="running",
            conversation_id=conv.id,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        task.last_run_id = None  # set after flush
        task.last_run_status = "running"
        task.last_run_at = run.started_at
        await db.commit()
        await db.refresh(run)
        task.last_run_id = run.id
        await db.commit()

        # ── Execute the agent run ──
        try:
            ctx = await _load_agent_context(db, task.agent_id)

            # persist user message in the conversation
            user_msg = Message(conversation_id=conv.id, role="user",
                              content_json={"text": task.prompt_text or ""})
            db.add(user_msg)
            await db.commit()

            # consume runner stream
            text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_traces: list[dict] = []
            saved_files: list[dict] = []
            saved_uis: list[dict] = []
            tokens_in = tokens_out = 0
            had_error: str | None = None
            had_interaction = False
            # Tool names we treat as 'requires user interaction'
            INTERACTION_TOOLS = {"AskUserQuestion"}

            runner = AgentRunner(ctx, user_id=owner.id)

            async def _consume() -> None:
                nonlocal tokens_in, tokens_out, had_error, had_interaction
                async for ev in runner.stream(task.prompt_text or "", []):
                    t = ev.type
                    d = ev.data or {}
                    if t == "text":
                        text_parts.append(d.get("text", ""))
                    elif t == "thinking":
                        thinking_parts.append(d.get("text", ""))
                    elif t in ("tool_use", "tool_result"):
                        tool_traces.append({"type": t, "data": d})
                        name = d.get("name") if t == "tool_use" else ""
                        if name and name in INTERACTION_TOOLS:
                            had_interaction = True
                    elif t == "file":
                        saved_files.append(d if isinstance(d, dict) else {})
                    elif t == "ui":
                        # UI surfaces require user click → treat as needing interaction
                        saved_uis.append(d if isinstance(d, dict) else {})
                        had_interaction = True
                    elif t == "done":
                        tokens_in = d.get("tokens_in", 0) or 0
                        tokens_out = d.get("tokens_out", 0) or 0
                    elif t == "error":
                        had_error = d.get("message") or "执行错误"

            timed_out = False

            async def _cancelled_bailout() -> None:
                # Commit 'cancelled' BEFORE re-raising, otherwise the run stays
                # "running" forever and every later cron fire is skipped.
                run.status = "cancelled"
                run.finished_at = datetime.now(timezone.utc)
                if run.started_at:
                    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
                run.error_message = "执行被中断（服务重启或手动取消）"
                task.last_run_status = "cancelled"
                task.last_run_at = run.finished_at
                await db.commit()
                await db.refresh(run)
                await _notify_run(db, task, run, owner)

            # Run the stream in an explicitly-managed task instead of
            # `asyncio.wait_for(_consume(), ...)`. `wait_for` cancels the inner
            # coroutine on timeout and then AWAITS it to finish unwinding — but
            # AgentRunner.stream()'s `finally` block does `await`/`yield` during
            # teardown, and an async generator that yields while being torn down
            # does not cooperate with cancellation. So `wait_for` would hang
            # forever waiting for a coroutine that never dies, the run stayed
            # "running" past its budget, and only the external watchdog reaped it
            # (~1920s) — leaving the conversation blank and skipping every next
            # fire. Here we cap the wait ourselves, cancel, allow a bounded grace
            # for cleanup, then ABANDON the task if it still refuses to finish so
            # the scheduler always makes progress. An orphaned stream self-cleans
            # when its httpx read-timeout fires.
            consume_task = asyncio.create_task(_consume())

            def _swallow(t: asyncio.Task) -> None:
                # Retrieve any exception from an abandoned task so asyncio does
                # not log "Task exception was never retrieved".
                if not t.cancelled():
                    t.exception()
            consume_task.add_done_callback(_swallow)

            budget = max(10, task.max_runtime_seconds)
            try:
                done, _pending = await asyncio.wait({consume_task}, timeout=budget)
            except asyncio.CancelledError:
                consume_task.cancel()
                await _cancelled_bailout()
                raise

            if consume_task not in done:
                # Hard timeout: exceeded budget (or the stream refused to yield/
                # cancel). Cancel it, give a bounded grace to unwind, then move on.
                timed_out = True
                consume_task.cancel()
                try:
                    await asyncio.wait({consume_task}, timeout=30)
                except asyncio.CancelledError:
                    await _cancelled_bailout()
                    raise
            elif consume_task.cancelled():
                await _cancelled_bailout()
                raise asyncio.CancelledError()
            else:
                exc = consume_task.exception()
                if exc is not None:
                    had_error = f"{type(exc).__name__}: {exc}"

            # persist assistant message
            content_payload: dict[str, Any] = {"text": "".join(text_parts)}
            if thinking_parts:
                content_payload["thinking"] = "".join(thinking_parts)
            if saved_files:
                content_payload["files"] = saved_files
            if saved_uis:
                content_payload["uis"] = saved_uis
            am = Message(
                conversation_id=conv.id, role="assistant",
                content_json=content_payload,
                tool_calls_json={"trace": tool_traces} if tool_traces else None,
                tokens_in=tokens_in, tokens_out=tokens_out,
            )
            db.add(am)

            # finalize run
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000) if run.started_at else 0
            run.tokens_in = tokens_in
            run.tokens_out = tokens_out

            # status precedence: timeout > interaction > error > success
            if timed_out:
                run.status = "timeout"
                run.error_message = f"任务执行超过 {task.max_runtime_seconds} 秒，已强制中断"
            elif had_interaction:
                run.status = "failed"
                run.error_message = "任务需要用户交互（AskUserQuestion / UI 表单），定时任务已跳过本次"
            elif had_error:
                run.status = "failed"
                run.error_message = had_error
            else:
                run.status = "succeeded"

            # summary = trim of final assistant text
            text_full = ("".join(text_parts) or "").strip()
            run.summary = (text_full[:200] + ("…" if len(text_full) > 200 else "")) if text_full else None

            # update task aggregate
            task.last_run_status = run.status
            task.last_run_at = run.finished_at

            await db.commit()
            await db.refresh(run)

            # notify
            await _notify_run(db, task, run, owner)
            return run.id

        except Exception as e:
            # Catch failures from _load_agent_context / AgentRunner construction.
            # Without this, the run is stuck "running" forever.
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            if run.started_at:
                run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
            run.error_message = f"{type(e).__name__}: {e}"
            task.last_run_status = "failed"
            task.last_run_at = run.finished_at
            await db.commit()
            await db.refresh(run)
            await _notify_run(db, task, run, owner)
            logger.exception("Task %s execute failed", task_id)
            return run.id


async def _next_run_no(db: AsyncSession, task_id: int) -> int:
    from sqlalchemy import func as _f
    n = (await db.execute(
        select(_f.coalesce(_f.max(TaskRun.run_no), 0)).where(TaskRun.task_id == task_id)
    )).scalar_one()
    return int(n or 0) + 1


# ---------- notifications ----------
async def _notify_run(db: AsyncSession, task: Task, run: TaskRun, owner: User) -> None:
    on = task.notify_on or "always"
    if on == "success" and run.status != "succeeded":
        return
    if on == "failure" and run.status == "succeeded":
        return
    channels = list(task.notify_channels_json or [])
    notify_status: dict[str, Any] = {}
    title, body, link = _format_notification(task, run)

    if "inapp" in channels:
        n = Notification(
            user_id=owner.id, type="task_run",
            title=title, body=body, link_url=link,
            detail_json={"task_id": task.id, "run_id": run.id, "status": run.status},
        )
        db.add(n)
        notify_status["inapp"] = {"ok": True}

    if "email" in channels:
        to_addr = (task.notify_email_to or owner.email or "").strip()
        if not to_addr:
            notify_status["email"] = {"ok": False, "error": "未填写收件邮箱"}
        else:
            html = _format_email_html(task, run, link)
            res = await mailer.send_email(to_addr, title, body, html)
            notify_status["email"] = res

    if "feishu" in channels:
        try:
            from .bridge_manager import get_bridge_manager
            fs_text = f"{title}\n{body}"
            if link:
                fs_text += f"\n{link}"
            notify_status["feishu"] = await get_bridge_manager().push_feishu_text(fs_text)
        except Exception as e:
            notify_status["feishu"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    run.notified_at = datetime.now(timezone.utc)
    run.notify_status_json = notify_status
    await db.commit()


def _format_notification(task: Task, run: TaskRun) -> tuple[str, str, str]:
    status_label = {
        "succeeded": "成功", "failed": "失败", "timeout": "超时",
        "cancelled": "已取消", "skipped": "已跳过",
    }.get(run.status, run.status or "")
    title = f"[任务] {task.name} · {status_label}"
    parts = []
    if run.summary:
        parts.append(run.summary)
    if run.error_message:
        parts.append(f"错误: {run.error_message}")
    if run.duration_ms:
        parts.append(f"耗时 {run.duration_ms / 1000:.1f}s")
    body = "\n".join(parts) if parts else "（无详细信息）"
    base = (settings.APP_BASE_URL or "").rstrip("/")
    link = f"{base}/tasks/{task.id}/runs/{run.id}" if base else ""
    return title, body, link


def _format_email_html(task: Task, run: TaskRun, link: str) -> str:
    color = {"succeeded": "#34a853", "failed": "#ea4335", "timeout": "#ea4335",
             "cancelled": "#9aa0a6", "skipped": "#9aa0a6"}.get(run.status, "#5f6368")
    summary = run.summary or "（无输出）"
    error = f'<p style="color:#ea4335;margin:6px 0">{run.error_message}</p>' if run.error_message else ""
    btn = f'<p><a href="{link}" style="display:inline-block;padding:8px 14px;background:#4285f4;color:#fff;border-radius:6px;text-decoration:none">查看详情</a></p>' if link else ""
    return f"""
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#202124;font-size:14px;line-height:1.6">
  <h2 style="margin:0 0 8px">[任务] {task.name}</h2>
  <p style="margin:0 0 12px">状态: <span style="color:{color};font-weight:600">{run.status}</span> · 耗时 {run.duration_ms / 1000:.1f}s</p>
  <pre style="background:#f1f3f4;padding:10px 12px;border-radius:6px;white-space:pre-wrap">{summary}</pre>
  {error}
  {btn}
</div>
"""


# ---------- orphan-run reconciliation ----------
async def _reconcile_orphan_runs() -> None:
    """Mark runs stuck in 'running'/'pending' as interrupted on startup.

    A manual or cron run is executed by an in-process asyncio task. If the
    backend process dies (crash / restart) while a run is in flight, the
    finalize code never executes and the TaskRun row stays 'running' forever.
    Because the default 'skip' concurrency policy refuses to start a new run
    while the previous one is 'running', the task appears permanently stuck.

    On boot no run can still be in flight (the event loop just started), so any
    'running'/'pending' row is by definition orphaned. We close them out and
    reset the parent task's last_run_status so future runs proceed.
    """
    from sqlalchemy import update as _update
    async with SessionLocal() as db:
        orphans = (await db.execute(
            select(TaskRun).where(TaskRun.status.in_(("running", "pending")))
        )).scalars().all()
        if not orphans:
            return
        now = datetime.now(timezone.utc)
        affected_task_ids: set[int] = set()
        for run in orphans:
            run.status = "failed"
            run.error_message = "执行被中断（服务重启或异常退出），已自动结束。请重新运行。"
            if run.started_at and not run.finished_at:
                run.finished_at = now
                try:
                    run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
                except Exception:
                    run.duration_ms = 0
            affected_task_ids.add(run.task_id)
        # Reset each parent task whose last_run_status is still 'running'.
        for tid in affected_task_ids:
            t = (await db.execute(select(Task).where(Task.id == tid))).scalar_one_or_none()
            if t and t.last_run_status in ("running", "pending"):
                t.last_run_status = "failed"
                t.last_run_at = now
        await db.commit()
        logger.warning("Reconciled %d orphaned task run(s) on startup", len(orphans))


# ---------- scheduler core ----------
class _Scheduler:
    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}
        self._stopped = asyncio.Event()
        self._watchdog: asyncio.Task | None = None

    def is_running(self, task_id: int) -> bool:
        t = self._tasks.get(task_id)
        return bool(t and not t.done())

    async def start(self) -> None:
        # Reconcile orphaned runs left "running" by a previous process that was
        # killed mid-execution (crash / restart). Without this they stay running
        # forever and the `skip` concurrency policy blocks every future run.
        await _reconcile_orphan_runs()
        # Recover all enabled cron/once schedules
        async with SessionLocal() as db:
            rows = (await db.execute(select(Task).where(Task.enabled.is_(True)))).scalars().all()
            for t in rows:
                if t.schedule_type in ("cron", "once") and t.schedule_value:
                    self.schedule(t.id, t.schedule_type, t.schedule_value, t.timezone)
        # Start the watchdog that periodically reaps runs wedged in 'running'
        # past their runtime budget (covers crashes AND in-process timeout misses).
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watchdog_loop(), name="task-watchdog")

    async def _watchdog_loop(self) -> None:
        """Every 60s, force-close any run stuck in 'running' beyond its budget."""
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(60)
                if self._stopped.is_set():
                    return
                try:
                    async with SessionLocal() as db:
                        stuck = (await db.execute(
                            select(Task).where(Task.last_run_status == "running")
                        )).scalars().all()
                        for t in stuck:
                            await _reap_stale_run_for_task(db, t)
                except Exception as e:  # pragma: no cover
                    logger.warning("task watchdog pass failed: %s", e)
        except asyncio.CancelledError:
            return

    async def stop(self) -> None:
        self._stopped.set()
        if self._watchdog and not self._watchdog.done():
            self._watchdog.cancel()
            try:
                await self._watchdog
            except (asyncio.CancelledError, Exception):
                pass
        for t in list(self._tasks.values()):
            t.cancel()
        for t in list(self._tasks.values()):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

    def cancel(self, task_id: int) -> None:
        t = self._tasks.pop(task_id, None)
        if t and not t.done():
            t.cancel()

    def schedule(self, task_id: int, schedule_type: str, schedule_value: str, tz: str) -> None:
        self.cancel(task_id)
        if schedule_type not in ("cron", "once") or not schedule_value:
            return
        coro = self._loop_one(task_id, schedule_type, schedule_value, tz)
        self._tasks[task_id] = asyncio.create_task(coro, name=f"task-{task_id}")

    async def _loop_one(self, task_id: int, stype: str, sval: str, tz: str) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    delay = next_fire_time(stype, sval, tz)
                except Exception as e:
                    logger.warning("Task %s schedule parse failed: %s", task_id, e)
                    return
                if delay is None:
                    return  # one-shot already passed
                # sleep until fire (in chunks so we can react to stop)
                while delay > 0 and not self._stopped.is_set():
                    chunk = min(delay, 30)
                    await asyncio.sleep(chunk)
                    delay -= chunk
                if self._stopped.is_set():
                    return
                # check enabled flag still set before firing
                async with SessionLocal() as db:
                    t = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
                    if not t or not t.enabled:
                        return
                try:
                    await execute_task(task_id, triggered_by="cron", triggered_user_id=None)
                except Exception as e:
                    logger.exception("Task %s execute failed: %s", task_id, e)
                if stype == "once":
                    return
        except asyncio.CancelledError:
            return


_scheduler = _Scheduler()


def get_scheduler() -> _Scheduler:
    return _scheduler
