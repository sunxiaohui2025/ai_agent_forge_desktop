from __future__ import annotations
from datetime import datetime
from typing import Any
from sqlalchemy import (
    String, Integer, Boolean, ForeignKey, DateTime, Text, JSON, BigInteger, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # admin/operator/user
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(256))


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str | None] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(256))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/disabled

    role: Mapped[Role] = relationship(lazy="joined")
    department: Mapped["Department | None"] = relationship("Department", foreign_keys=[department_id], lazy="joined")


class Department(Base, TimestampMixin):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(String(256))


class Model(Base, TimestampMixin):
    __tablename__ = "models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(32))  # anthropic/openai-compatible
    model_id: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str | None] = mapped_column(String(256))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    max_tokens: Mapped[int] = mapped_column(Integer, default=8192)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Provider-specific extra params merged into the API call (e.g. {"enable_thinking": false})
    extra_params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MCPConnector(Base, TimestampMixin):
    __tablename__ = "mcp_connectors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    transport: Mapped[str] = mapped_column(String(16))  # stdio/sse/http
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    user_summary: Mapped[str | None] = mapped_column(Text, default=None)
    tool_summaries_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    user_summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CliApp(Base, TimestampMixin):
    """A "连接应用" — a command-line application the agent can drive.

    Rows represent apps the user has *connected* (installed + opted-in). The
    static metadata catalog lives in code (runtime/cli_apps_catalog.py); this
    table records the connected state plus where the binary resolved on the
    host so the in-process CLI MCP can execute it.
    """
    __tablename__ = "cli_apps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Catalog key (e.g. "ffmpeg") or "custom-<slug>" for user-added apps.
    app_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str | None] = mapped_column(String(64), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    # The CLI binary name the agent invokes (first detected of bin_names).
    bin_name: Mapped[str] = mapped_column(String(128))
    bin_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    version: Mapped[str | None] = mapped_column(String(64), default=None)
    install_command: Mapped[str | None] = mapped_column(String(512), default=None)
    # installed / not_installed — refreshed on connect / detect.
    status: Mapped[str] = mapped_column(String(16), default="not_installed")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentCliApp(Base):
    __tablename__ = "agent_cli_apps"
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    cli_app_id: Mapped[int] = mapped_column(ForeignKey("cli_apps.id", ondelete="CASCADE"), primary_key=True)


class SystemSetting(Base, TimestampMixin):
    """Key-value store for desktop-app runtime configuration.

    Each row holds one config namespace as a JSON blob — e.g. key="mineru"
    stores {mode, api_key, base_url, timeout_sec}. Secrets (API keys) are
    Fernet-encrypted in `value_enc`; non-secret fields go in `value_json`.
    This lets the desktop personal-assistant runs without a .env file: users
    configure everything from the Settings UI.
    """
    __tablename__ = "system_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # Non-secret, displayable fields (mode, base_url, timeout …)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Encrypted secrets blob (api_key, tokens …) — JSON string, Fernet-encrypted.
    value_enc: Mapped[str | None] = mapped_column(Text, default=None)


class Skill(Base, TimestampMixin):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(16))  # atomic / composite
    # atomic: {"path": ".../skill_dir"}; composite: {"yaml": "..."} (parsed at runtime)
    source_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    user_summary: Mapped[str | None] = mapped_column(Text, default=None)
    user_summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    default_model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    fallback_model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    upload_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_turns: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    effort: Mapped[str] = mapped_column(String(16), default="low", server_default="low")
    # File-parsing length cap fed into the model:
    #   None → use settings.PARSED_MARKDOWN_HARD_LIMIT
    #   0    → no cap (inject the full parsed markdown)
    #   >0   → cap to this many characters (head 60% + tail 40% with omission marker)
    parsed_content_limit: Mapped[int | None] = mapped_column(Integer)
    # Optional default local working directory. When set and the conversation
    # has no user-selected workspace, the agent operates inside this directory.
    work_dir: Mapped[str | None] = mapped_column(String(1024))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentSkill(Base):
    __tablename__ = "agent_skills"
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)


class AgentMCP(Base):
    __tablename__ = "agent_mcps"
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    mcp_id: Mapped[int] = mapped_column(ForeignKey("mcp_connectors.id", ondelete="CASCADE"), primary_key=True)


class RoleAgentGrant(Base):
    __tablename__ = "role_agent_grants"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)


class Workspace(Base, TimestampMixin):
    """A project = a local working directory + default config.

    Desktop concept (Codex-style): when a conversation is bound to a workspace
    it becomes a "task" operating inside `path`; without one it is a plain
    "chat". `path` is an absolute local directory chosen via the OS folder
    picker. Owned by the single local user in desktop mode.
    """
    __tablename__ = "workspaces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(String(1024))  # absolute local dir
    default_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    # Default execution permission for tasks in this workspace:
    #   ask / auto / full  (maps to SDK permission_mode in the runner)
    permission_mode: Mapped[str] = mapped_column(String(16), default="ask")
    icon: Mapped[str | None] = mapped_column(String(256))
    color: Mapped[str | None] = mapped_column(String(32))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="新对话")
    # Desktop project model:
    #   kind='chat'  → workspace_id is NULL (plain Q&A, no file ops)
    #   kind='task'  → bound to a workspace, operates in its directory
    kind: Mapped[str] = mapped_column(String(16), default="chat", index=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True, default=None)
    # Per-conversation overrides (NULL = inherit from agent/workspace default).
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"), default=None)
    permission_mode: Mapped[str | None] = mapped_column(String(16), default=None)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user/assistant/tool/system
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_calls_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(BigInteger)
    mime: Mapped[str] = mapped_column(String(128))
    # Parsed text/markdown for LLM consumption
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/parsing/done/failed
    parse_engine: Mapped[str | None] = mapped_column(String(32))  # text/mineru-cloud/mineru-local/local-lib
    parsed_markdown: Mapped[str | None] = mapped_column(Text)
    parsed_chars: Mapped[int] = mapped_column(Integer, default=0)
    parse_error: Mapped[str | None] = mapped_column(Text)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class CallLog(Base):
    __tablename__ = "call_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DownloadToken(Base):
    """One-time / time-limited URL token for serving files (skill outputs, uploads).

    Path is stored absolute and validated against allowed roots on each fetch to
    prevent path-traversal. Owner check ensures cross-user access is blocked.
    """
    __tablename__ = "download_tokens"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(1024))
    file_name: Mapped[str] = mapped_column(String(256))
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    max_downloads: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unlimited within expiry
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ====================== Solution Packs ======================

class SolutionPack(Base, TimestampMixin):
    """Declarative business workflow packaged as a YAML DAG of nodes.

    Each Pack is registered against an agent in `agent_packs` and shows up to
    the LLM as a single tool `run_pack__<code>(inputs)`. Calling that tool
    spins up a `PackRun` and streams progress via SSE pack_progress/pack_done.
    """
    __tablename__ = "solution_packs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # snake_case, == pack_id
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    yaml_text: Mapped[str] = mapped_column(Text)  # source-of-truth YAML
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # parsed cache
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentPack(Base):
    __tablename__ = "agent_packs"
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("solution_packs.id", ondelete="CASCADE"), primary_key=True)


class PackRun(Base):
    """Execution snapshot of a Pack. Persisted so human_approval can pause+resume."""
    __tablename__ = "pack_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # uuid hex
    pack_id: Mapped[int] = mapped_column(ForeignKey("solution_packs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    # ^ running / success / failed / aborted / waiting_approval
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PackApproval(Base):
    """One row per human_approval node hit. Inbox + decision audit."""
    __tablename__ = "pack_approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    pack_id: Mapped[int] = mapped_column(ForeignKey("solution_packs.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending/approved/rejected/timeout
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str | None] = mapped_column(Text)
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # context highlights for the approver
    assigned_role: Mapped[str | None] = mapped_column(String(32))
    assigned_user_ids: Mapped[list[int] | None] = mapped_column(JSON)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Scheduled Tasks ----------
class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str] = mapped_column(Text, default="")

    schedule_type: Mapped[str] = mapped_column(String(16), default="manual")  # manual / once / cron
    schedule_value: Mapped[str | None] = mapped_column(String(128))           # cron expr or ISO datetime
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")

    max_runtime_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    concurrency_policy: Mapped[str] = mapped_column(String(16), default="skip")  # skip / queue
    notify_channels_json: Mapped[list[str]] = mapped_column(JSON, default=list)  # ["inapp","email"]
    notify_email_to: Mapped[str | None] = mapped_column(String(256))
    notify_on: Mapped[str] = mapped_column(String(16), default="always")        # always / success / failure
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    last_run_id: Mapped[int | None] = mapped_column(BigInteger)
    last_run_status: Mapped[str | None] = mapped_column(String(16))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRun(Base):
    __tablename__ = "task_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    run_no: Mapped[int] = mapped_column(Integer, default=1)
    triggered_by: Mapped[str] = mapped_column(String(16), default="manual")     # manual / cron
    triggered_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / running / succeeded / failed / cancelled / timeout / skipped

    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)

    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_status_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base):
    """Generic in-app notification record."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), default="task_run")  # task_run / system
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(512))
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)



class Favorite(Base):
    """User-curated Q&A bookmark stored in the personal "Space".

    Holds full text snapshots of the question + answer so deleting the source
    conversation/message still leaves the favorite readable. The FK columns
    are soft references (SET NULL) used for the optional "jump back to
    original conversation" button.
    """
    __tablename__ = "favorites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))

    question_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text)
    # Snapshot of assistant-generated file cards (download_url + output_path so
    # the FileCard component can keep refreshing expired tokens forever).
    files_json: Mapped[list[Any] | None] = mapped_column(JSON)

    # snapshots — survive even after the agent/model is deleted
    agent_id: Mapped[int | None] = mapped_column(Integer)
    agent_name: Mapped[str | None] = mapped_column(String(128))
    model_code: Mapped[str | None] = mapped_column(String(64))

    note: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_favorites_user_message"),
    )


# ====================== Remote Bridge (IM channels) ======================
class ChannelConfig(Base, TimestampMixin):
    """Per-channel remote-bridge configuration (Feishu / QQ / WeChat).

    Connects an external IM channel to the local agent so the user can chat
    with their experts from messaging apps. Credentials are stored encrypted
    (Fernet) in `config_enc`; non-secret display fields live in `config_json`.
    """
    __tablename__ = "channel_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # feishu/qq/weixin
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Which expert answers messages from this channel. NULL → default expert.
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    # Non-secret config (app_id, bot id, display options …)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Encrypted secrets blob (app_secret, tokens …) — JSON string, Fernet-encrypted.
    config_enc: Mapped[str | None] = mapped_column(Text, default=None)
    # Live connection status: disconnected / connecting / connected / error
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    status_detail: Mapped[str | None] = mapped_column(Text, default=None)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChannelBinding(Base):
    """Binding between an external IM chat and a local conversation.

    A user pairs their IM account by sending a one-time binding code; once
    bound, messages from `external_chat_id` route to `conversation_id`.
    """
    __tablename__ = "channel_bindings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), index=True)
    external_chat_id: Mapped[str] = mapped_column(String(128), index=True)
    external_user_name: Mapped[str | None] = mapped_column(String(128))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("channel", "external_chat_id", name="uq_channel_chat"),
    )
