from __future__ import annotations
import os
import sys
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_data_dir() -> Path:
    """Per-user application data directory for the desktop app.

    Precedence:
      1. H3C_AGENT_DATA_DIR env (set by the Electron shell at launch)
      2. ~/.h3c-agent (cross-platform default)
    All local artifacts (sqlite db, storage) live here so the app is
    self-contained and survives upgrades.
    """
    env = os.environ.get("H3C_AGENT_DATA_DIR")
    base = Path(env).expanduser() if env else Path.home() / ".h3c-agent"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_env_files() -> tuple[str, ...]:
    """Locate .env files to load, in priority order (later wins).

    Development: read ``./.env`` (repo backend/.env).
    Packaged (PyInstaller frozen):
      1. The .env bundled inside the app at ``sys._MEIPASS/.env`` (optional).
      2. ``<DATA_DIR>/.env`` — optional user overrides; values here take
         precedence over the bundled defaults.
    Note: MinerU config is NOT read from .env in desktop mode — it lives in
    the system_settings DB table and is managed via the Settings UI.
    """
    if getattr(sys, "frozen", False):
        files: list[str] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bundled = Path(meipass) / ".env"
            if bundled.is_file():
                files.append(str(bundled))
        data_dir_env = _resolve_data_dir() / ".env"
        if data_dir_env.is_file():
            files.append(str(data_dir_env))
        return tuple(files)
    return (".env",)


class Settings(BaseSettings):
    """All sensitive defaults are empty/placeholder. Real values MUST come from
    backend/.env (gitignored) or process env. See backend/.env.example for the
    full list of variables.

    Desktop mode: the database defaults to a local SQLite file under the
    per-user data dir (~/.h3c-agent/app.db). Set DATABASE_URL to a Postgres
    DSN to fall back to the old server deployment mode.
    """
    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(), env_file_encoding="utf-8", extra="ignore"
    )

    # Per-user data directory (sqlite db + storage live here in desktop mode).
    DATA_DIR: str = ""

    # Desktop single-user mode: when true, the app runs for a single local user
    # and skips multi-tenant role gating. Even so, login can still be required
    # (see REQUIRE_LOGIN) — the single user just authenticates with username +
    # password and then has full rights.
    DESKTOP_MODE: bool = True

    # Require username/password login. When true (default), the backend
    # validates the access token on every request and the frontend shows the
    # login screen. Set false to auto-resolve the local user with no login
    # (kiosk / single-machine no-auth mode).
    REQUIRE_LOGIN: bool = True

    # Leave blank → defaults to sqlite under DATA_DIR (see __init__ below).
    DATABASE_URL: str = ""

    # MUST be replaced in production via env. 32+ bytes random.
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Fernet key (base64-encoded 32 bytes). If blank, crypto.py derives one
    # deterministically from JWT_SECRET — fine for dev, NOT for prod.
    ENCRYPTION_KEY: str = ""

    STORAGE_ROOT: str = "../storage"
    SKILLS_DIR: str = "../storage/skills"
    UPLOADS_DIR: str = "../storage/uploads"
    MAX_UPLOAD_MB: int = 50

    CORS_ORIGINS: str = "http://localhost:5173"

    # First-run admin bootstrap; change immediately after first login.
    SEED_ADMIN_USERNAME: str = "admin"
    SEED_ADMIN_PASSWORD: str = "admin123"

    # ---- File parsing (MinerU) ----
    MINERU_MODE: str = "cloud"  # "cloud" | "local" | "disabled"
    MINERU_BASE_URL: str = "https://mineru.net"
    MINERU_API_KEY: str = ""
    MINERU_TIMEOUT_SEC: int = 60
    # Hard cap on parsed markdown stored / sent to model
    PARSED_MARKDOWN_HARD_LIMIT: int = 20000

    # ---- SMTP (Task notifications) ----
    # Leave blank to disable email notifications. Configure via .env.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""        # display-name <addr@host>; for QQ the address part must equal SMTP_USER
    SMTP_USE_TLS: bool = True  # STARTTLS; for SSL on 465 set to False and SMTP_USE_SSL=True
    SMTP_USE_SSL: bool = False
    APP_BASE_URL: str = "http://localhost:5173"  # link target in emails / notifications
    # Backend public base URL used when handing out signed file URLs to external
    # tools (MCP servers). Falls back to APP_BASE_URL when unset.
    BACKEND_BASE_URL: str = ""

    # ---- Logging ----
    LOG_LEVEL: str = "INFO"  # DEBUG | INFO | WARNING | ERROR


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Resolve the per-user data dir and derive the sqlite path from it when unset.
    data_dir = Path(s.DATA_DIR).expanduser() if s.DATA_DIR else _resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    s.DATA_DIR = str(data_dir)

    if not s.DATABASE_URL:
        s.DATABASE_URL = f"sqlite+aiosqlite:///{data_dir / 'app.db'}"

    # Storage paths. In a PyInstaller-frozen (packaged) app the working dir and
    # bundle are read-only/ephemeral, so the repo-relative defaults
    # ("../storage/...") don't exist. Point them at the per-user DATA_DIR so
    # uploads and the seeded built-in skills live in a writable, persistent
    # place. In development we keep the repo-relative defaults so existing
    # skills under ./storage/skills stay reachable without re-seeding.
    if getattr(sys, "frozen", False):
        if s.STORAGE_ROOT == "../storage":
            s.STORAGE_ROOT = str(data_dir / "storage")
        if s.SKILLS_DIR == "../storage/skills":
            s.SKILLS_DIR = str(data_dir / "skills")
        if s.UPLOADS_DIR == "../storage/uploads":
            s.UPLOADS_DIR = str(data_dir / "uploads")
    return s


settings = get_settings()
