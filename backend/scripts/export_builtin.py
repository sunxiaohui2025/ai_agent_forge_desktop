"""Snapshot the current local DB's experts into a bundled seed file.

Reads ~/.h3c-agent/app.db (or the configured sqlite DATABASE_URL) and writes
backend/builtin_agents.json — the experts plus their skill / cli-app / model
bindings, referenced by *stable codes* (not row ids) so they re-bind correctly
on a fresh install where ids differ.

Run from the backend/ directory with the app venv:
    .venv/bin/python scripts/export_builtin.py

The file is gitignored (it may carry internal prompts) but is bundled into the
installer by sidecar.spec so a fresh install ships with the experts pre-loaded.
See app.main._seed_builtin_agents.

Note: model *credentials* are intentionally NOT exported here. Experts bind to
their model by code; provision the models themselves via builtin_models.json or
the admin UI so API keys never get baked into the installer in plaintext.
"""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402


def _db_path() -> Path:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        raise SystemExit(f"export only supports sqlite DBs, got: {url}")
    return Path(url.split(":///", 1)[1])


def export() -> None:
    dbp = _db_path()
    if not dbp.exists():
        raise SystemExit(f"DB not found: {dbp}")
    db = sqlite3.connect(str(dbp))
    db.row_factory = sqlite3.Row

    skill_code = {r["id"]: r["code"] for r in db.execute("select id, code from skills")}
    model_code = {r["id"]: r["code"] for r in db.execute("select id, code from models")}
    cli_key = {r["id"]: r["app_key"] for r in db.execute("select id, app_key from cli_apps")}
    conn_name = {r["id"]: r["name"] for r in db.execute("select id, name from mcp_connectors")}

    def _ids(table: str, col: str, agent_id: int) -> list[int]:
        return [r[0] for r in db.execute(
            f"select {col} from {table} where agent_id=?", (agent_id,))]

    agents = []
    for a in db.execute("select * from agents order by id"):
        d = dict(a)
        skill_codes = [skill_code[i] for i in _ids("agent_skills", "skill_id", d["id"]) if i in skill_code]
        cli_app_keys = [cli_key[i] for i in _ids("agent_cli_apps", "cli_app_id", d["id"]) if i in cli_key]
        connector_names = [conn_name[i] for i in _ids("agent_mcps", "mcp_id", d["id"]) if i in conn_name]
        upload_policy = d.get("upload_policy_json")
        try:
            upload_policy = json.loads(upload_policy) if isinstance(upload_policy, str) else (upload_policy or {})
        except Exception:
            upload_policy = {}
        agents.append({
            "code": d["code"],
            "name": d["name"],
            "description": d.get("description"),
            "icon": d.get("icon"),
            "system_prompt": d.get("system_prompt") or "",
            "default_model_code": model_code.get(d.get("default_model_id")),
            "fallback_model_code": model_code.get(d.get("fallback_model_id")),
            "upload_policy_json": upload_policy,
            "max_turns": d.get("max_turns"),
            "effort": d.get("effort"),
            "parsed_content_limit": d.get("parsed_content_limit"),
            "work_dir": d.get("work_dir"),
            "enabled": bool(d.get("enabled")),
            "is_default": bool(d.get("is_default")),
            "skill_codes": skill_codes,
            "cli_app_keys": cli_app_keys,
            "connector_names": connector_names,
        })

    out = BACKEND / "builtin_agents.json"
    out.write_text(json.dumps(agents, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ exported {len(agents)} agents → {out.name}")
    for a in agents:
        print(f"    - {a['code']:<10} {a['name']}  "
              f"(skills={len(a['skill_codes'])}, cli={len(a['cli_app_keys'])}, "
              f"model={a['default_model_code']})")
    print("  gitignored; bundled into the installer by sidecar.spec")


if __name__ == "__main__":
    export()
