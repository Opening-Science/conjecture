"""The run panel reads everything from the pack and the manifests.

    python -m unittest tests/test_panel.py      (from the repository root)
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pack  # noqa: E402,F401  (sets CONJECTURE_PACK)

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))
sys.path.insert(0, str(HUB / "panel"))

import build_data  # noqa: E402
import contract  # noqa: E402
from pack import PACK  # noqa: E402


class TestPackJson(unittest.TestCase):
    def test_describes_the_pack_and_every_adapter(self):
        pj = build_data.pack_json()
        self.assertEqual(pj["pack"]["name"], PACK.name)
        self.assertEqual([q[0] for q in pj["questions"]],
                         sorted(p.stem for p in PACK.seeds_dir.glob("*.json")))
        self.assertEqual({e["id"] for e in pj["engines"]},
                         {m.name for m in contract.discover("engine")})
        self.assertEqual({j["id"] for j in pj["judges"]},
                         {m.name for m in contract.discover("judge")})
        for a in pj["engines"] + pj["judges"]:
            self.assertIn(a["state"], ("ready", "needs", "designed"))
            self.assertEqual(a["state"] == "designed", not a["built"])

    def test_key_names_come_from_manifests(self):
        want = set()
        for m in contract.discover():
            r = m.get("requires") or {}
            want |= set(r.get("env") or []) | set(r.get("env_any") or [])
        self.assertEqual(set(build_data.pack_json()["keys"]), want)

    def test_static_hints_name_no_local_path(self):
        text = json.dumps(build_data.pack_json(local=False))
        self.assertNotIn(str(Path.home()), text)
        self.assertNotIn(str(HUB), text)


class TestJobs(unittest.TestCase):
    def test_whitelist_holds_only_unattended_model_runs(self):
        import server
        jobs = server.JOBS
        for m in contract.discover():
            unattended = (m.built and m["invocation"] == "self-driving"
                          and m["backend"] != "none")
            key = f"{'gen' if m.kind == 'engine' else 'judge'}-{m.name}"
            self.assertEqual(key in jobs, unattended, key)
        for j in jobs.values():
            self.assertTrue(all(isinstance(a, str) for a in j["argv"]))


class TestResultsAndExport(unittest.TestCase):
    def test_no_results_is_an_error_not_an_empty_page(self):
        if PACK.audit_db.exists():
            self.skipTest("this pack has results")
        with self.assertRaises(sqlite3.Error):
            build_data.data_json()

    def test_export_is_static_and_path_free(self):
        out = Path(tempfile.mkdtemp()) / "site"
        subprocess.run([sys.executable, str(HUB / "panel" / "export.py"),
                        "--out", str(out)], check=True, capture_output=True)
        for f in ("index.html", "app.js", "style.css", "pack.json"):
            self.assertTrue((out / f).is_file(), f)
        self.assertFalse((out / "fonts").exists())
        self.assertTrue(json.loads((out / "pack.json").read_text())["static"])
        for f in out.rglob("*"):
            if f.is_file() and f.suffix in (".json", ".html", ".js"):
                self.assertNotIn(str(Path.home()), f.read_text(), f.name)


if __name__ == "__main__":
    unittest.main()
