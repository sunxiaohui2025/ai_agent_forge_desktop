"""Tests for skill-script execution fallbacks (subprocess entry + uploads link)."""
import asyncio
import tempfile
import unittest
from pathlib import Path

from app.runtime.agent_runner import AgentRunner


class _StubRunner:
    """Bare object exposing just the methods under test."""
    _run_skill_script_subprocess = AgentRunner._run_skill_script_subprocess
    _link_uploads_into_workspace = AgentRunner._link_uploads_into_workspace
    _get_session_workspace = AgentRunner._get_session_workspace

    def __init__(self, ws):
        self._session_workspace = str(ws)
        self._user_id = 1


class SubprocessFallbackTests(unittest.TestCase):
    def test_argparse_script_runs_and_writes_output(self):
        src = (
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--title')\n"
            "p.add_argument('--output')\n"
            "a = p.parse_args()\n"
            "open(a.output, 'w').write(a.title)\n"
        )
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "cli_tool.py"
            script.write_text(src, encoding="utf-8")
            out = Path(td) / "res.txt"
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script,
                # workspace/cwd/workdir are helpers we inject for the in-process
                # path; the script never declared them, so they must be filtered
                # out instead of crashing argparse.
                call_kwargs={"title": "hello", "output": str(out),
                             "workspace": td, "cwd": td, "workdir": td},
                cwd=td,
            ))
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(res["exit_code"], 0)
            self.assertEqual(out.read_text(), "hello")

    def test_nonzero_exit_is_reported_as_error(self):
        src = ("import argparse, sys\n"
               "argparse.ArgumentParser().parse_args()\n"
               "sys.stderr.write('boom')\n"
               "sys.exit(3)\n")
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "t.py"
            script.write_text(src, encoding="utf-8")
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script, call_kwargs={}, cwd=td))
            self.assertIn("error", res)
            self.assertEqual(res["exit_code"], 3)
            self.assertIn("boom", res["stderr"])

    def test_boolean_kwarg_becomes_bare_flag(self):
        src = (
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--verbose', action='store_true')\n"
            "p.add_argument('--output')\n"
            "a = p.parse_args()\n"
            "open(a.output,'w').write(str(a.verbose))\n"
        )
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "t.py"
            script.write_text(src, encoding="utf-8")
            out = Path(td) / "o.txt"
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script,
                call_kwargs={"verbose": True, "output": str(out)}, cwd=td))
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(out.read_text(), "True")

    def test_sibling_imports_still_work(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "helper.py").write_text("VALUE = 'ok'\n", encoding="utf-8")
            script = Path(td) / "t.py"
            script.write_text(
                "import argparse, helper\n"
                "p = argparse.ArgumentParser()\n"
                "p.add_argument('--output')\n"
                "a = p.parse_args()\n"
                "open(a.output,'w').write(helper.VALUE)\n",
                encoding="utf-8",
            )
            out = Path(td) / "o.txt"
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script, call_kwargs={"output": str(out)}, cwd=td))
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(out.read_text(), "ok")


    def test_positional_and_flags_combined(self):
        """argparse scripts may declare both, e.g. render_check.py <html> --screenshots d."""
        src = (
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('target')\n"
            "p.add_argument('--label')\n"
            "p.add_argument('--output')\n"
            "a = p.parse_args()\n"
            "open(a.output,'w').write(a.target + '|' + a.label)\n"
        )
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "t.py"
            script.write_text(src, encoding="utf-8")
            out = Path(td) / "o.txt"
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script,
                call_kwargs={"label": "L", "output": str(out)},
                cwd=td, argv_extra=["T"]))
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(out.read_text(), "T|L")

    def test_sys_argv_script_without_args_gets_actionable_error(self):
        """No argparse and no positional args → tell the model to use `args`."""
        src = "import sys\nprint(sys.argv[1])\n"
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "t.py"
            script.write_text(src, encoding="utf-8")
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script, call_kwargs={"skill_path": "/x"}, cwd=td))
            self.assertIn("args", res.get("error", ""))
            self.assertIn("skill_path", res.get("hint_ignored_kwargs", []))

    def test_sys_argv_script_runs_with_positional_args(self):
        src = "import sys\nopen(sys.argv[2],'w').write(sys.argv[1])\n"
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "t.py"
            script.write_text(src, encoding="utf-8")
            out = Path(td) / "o.txt"
            r = _StubRunner(td)
            res = asyncio.run(r._run_skill_script_subprocess(
                script_path=script, call_kwargs={}, cwd=td,
                argv_extra=["hi", str(out)]))
            self.assertTrue(res.get("ok"), res)
            self.assertEqual(out.read_text(), "hi")


class UploadsLinkTests(unittest.TestCase):
    def test_uploads_symlinked_into_workspace(self):
        from app.core.config import settings
        with tempfile.TemporaryDirectory() as td:
            uploads = Path(td) / "uploads"
            (uploads / "1").mkdir(parents=True)
            (uploads / "1" / "report.pdf").write_text("data")
            ws = Path(td) / "ws"
            ws.mkdir()
            old = settings.UPLOADS_DIR
            settings.UPLOADS_DIR = str(uploads)
            try:
                r = _StubRunner(ws)
                self.assertIsNotNone(r._link_uploads_into_workspace())
                # The point of the change: scripts can read uploads/<name>.
                self.assertEqual((ws / "uploads" / "report.pdf").read_text(), "data")
            finally:
                settings.UPLOADS_DIR = old

    def test_missing_uploads_dir_is_tolerated(self):
        from app.core.config import settings
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td) / "ws"
            ws.mkdir()
            old = settings.UPLOADS_DIR
            settings.UPLOADS_DIR = str(Path(td) / "nope")
            try:
                self.assertIsNone(_StubRunner(ws)._link_uploads_into_workspace())
            finally:
                settings.UPLOADS_DIR = old


if __name__ == "__main__":
    unittest.main()
