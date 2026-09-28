"""The adapter contract holds, and conformance catches what it should.

    python -m unittest tests/test_contract.py      (from the repository root)

Needs no model and no key: the model-backed adapters are exercised by
conformance/conformance.py, not here. Runs against the toy pack unless
CONJECTURE_PACK names another (tests/_pack.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pack  # noqa: E402,F401  (sets CONJECTURE_PACK)

HUB = Path(__file__).resolve().parent.parent
PY = sys.executable
CONF = HUB / "conformance" / "conformance.py"
sys.path.insert(0, str(HUB))
sys.path.insert(0, str(HUB / "engines"))

import contract  # noqa: E402


def conformance(*args: str, env: dict | None = None) -> None:
    subprocess.run([PY, str(CONF), *args], cwd=HUB, check=False,
                   capture_output=True, text=True,
                   env={**os.environ, **(env or {})})


class TestManifests(unittest.TestCase):
    def test_every_manifest_validates(self):
        ms = contract.discover()
        self.assertGreaterEqual(len(ms), 10)
        for m in ms:
            self.assertEqual(contract.check_manifest(m.data), [], m.path)

    def test_built_adapters_load(self):
        for m in contract.discover():
            if m.built:
                mod = contract.load_adapter(m)
                entry = "generate" if m.kind == "engine" else "judge"
                self.assertTrue(callable(getattr(mod, entry)), m.name)

    def test_run_1_engines_are_still_named_as_in_their_runs(self):
        # scoreboard joins on run.engine; renaming an adapter would orphan
        # every run it made
        names = {m.name for m in contract.discover("engine")}
        self.assertLessEqual({"codex-solo", "baseline-claude"}, names)

    def test_bad_manifest_is_refused(self):
        m = contract.get("engine", "reference").data
        self.assertTrue(contract.check_manifest({**m, "corpus_access": "web"}))
        self.assertTrue(contract.check_manifest(
            {**m, "corpus_access": "connector"}))       # no connector named
        bad_commit = {**m, "upstream": {**m["upstream"], "commit": "abc"}}
        self.assertTrue(contract.check_manifest(bad_commit))


class TestPrompt(unittest.TestCase):
    def test_prompt_hashes_match_the_packs_runs(self):
        # hub changes must not change what a pack's engines were asked:
        # every saved run of a shared-prompt engine rebuilds to its hash
        from pack import PACK
        from prompt import build
        runs = sorted(PACK.runs_dir.glob("*.json"))
        if not runs:
            self.skipTest("this pack has no runs")
        for run in runs:
            seed, engine = run.name.split(".")[:2]
            try:
                m = contract.get("engine", engine)
            except KeyError:
                continue
            if m["corpus_access"] not in ("cli", "mcp") or \
                    m["backend"] == "none":
                continue
            recorded = json.loads(run.read_text())["run"]["config_hash"]
            _, chash = build(seed, m.name, m["backend"],
                             access=m["corpus_access"])
            self.assertEqual(chash, recorded, run.name)

    def test_mcp_prompt_names_tools_not_the_cli(self):
        from pack import PACK
        from prompt import build
        seed = sorted(PACK.seeds_dir.glob("*.json"))[0].stem
        cli, h1 = build(seed, "x", "y")
        mcp, h2 = build(seed, "x", "y", access="mcp")
        self.assertIn("corpus_api.py search", cli)
        self.assertNotIn("corpus_api.py", mcp)
        self.assertIn('search(query="QUERY TERMS", limit=8)', mcp)
        self.assertNotEqual(h1, h2)


class TestVerdicts(unittest.TestCase):
    ITEMS = [{"candidate_id": "C1"}, {"candidate_id": "C2"}]

    def v(self, cid, **kw):
        return {"candidate_id": cid, "verdict": "declined",
                "failing_step": 0, "grounded": False, "testable": True,
                "novel": True, "reason": "r", **kw}

    def test_complete_batch_passes(self):
        self.assertEqual(contract.check_verdicts(
            [self.v("C1"), self.v("C2")], self.ITEMS), [])

    def test_missing_duplicate_unknown_and_bad_values(self):
        probs = contract.check_verdicts(
            [self.v("C1"), self.v("C1"), self.v("C9"),
             self.v("C2", verdict="maybe")], self.ITEMS)
        text = " ".join(probs)
        self.assertIn("C1 judged 2 times", text)
        self.assertIn("unknown candidate C9", text)
        self.assertIn("'maybe' is not one of", text)

    def test_extracts_array_from_prose(self):
        text = "Here you go:\n```json\n" + json.dumps(
            [self.v("C1")]) + "\n```\nDone."
        self.assertEqual(contract.extract_verdicts(text)[0]["candidate_id"],
                         "C1")


class TestTranscript(unittest.TestCase):
    def test_codex_exec_lines_become_calls(self):
        from codex_cli import transcript_calls
        t = textwrap.dedent("""\
            exec
            /bin/zsh -lc '../.venv/bin/python corpus_api.py search "glow respiration" --limit 8' in /hub
             succeeded in 0ms:
            exec
            /bin/zsh -lc 'python3 -c "print(2*3)"' in /hub
            exec
            /bin/zsh -lc '../.venv/bin/python corpus_api.py get W9990000043' in /hub
            exec
            /bin/zsh -lc "../.venv/bin/python corpus_api.py search 'glow lumB' --limit 8" in /hub
            """)
        calls = transcript_calls(t)
        self.assertEqual([c["tool"] for c in calls],
                         ["search", "get_work", "search"])
        self.assertEqual(calls[0]["args"]["argv"][0], "glow respiration")
        self.assertEqual(calls[2]["args"]["argv"], ["glow lumB", "--limit",
                                                    "8"])


class TestConformance(unittest.TestCase):
    """Runs conformance.py for real, into temporary directories."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.work, cls.results = cls.tmp / "work", cls.tmp / "results"
        # an engine that cites a real work from outside the toy corpus,
        # the signature of an engine that brought knowledge in
        rogue = cls.tmp / "adapters" / "rogue"
        rogue.mkdir(parents=True)
        m = contract.get("engine", "reference").data
        (rogue / "engine.yaml").write_text(json.dumps(
            {**m, "name": "rogue", "title": "Rogue (test)"}))
        (rogue / "adapter.py").write_text(textwrap.dedent("""\
            def generate(req):
                return {"hof_version": "1.0", "run": {}, "hypotheses": [{
                    "id": "T1-1", "causal_level": "L1",
                    "statement": "A claim resting on literature from "
                                 "outside the pack corpus entirely.",
                    "scope": {"population": "p", "condition": "c",
                              "outcome": "o"},
                    "rationale": [{"step": "s",
                                   "justification_type": "citation",
                                   "work_ids": ["W2141663490"]}],
                    "cited_work_ids": ["W2141663490"],
                    "proposed_experiment": "measure it"}]}
            """))
        env = {"CONJECTURE_ADAPTER_PATH": str(cls.tmp / "adapters")}
        conformance("--offline", "rogue", "--work", str(cls.work),
                    "--results", str(cls.results), env=env)

    def result(self, kind, name) -> dict:
        return json.loads(
            (self.results / f"{kind}.{name}.json").read_text())

    def checks(self, res) -> dict:
        return {c["check"]: c["ok"] for c in res["checks"]}

    def test_reference_engine_passes(self):
        r = self.result("engine", "reference")
        self.assertEqual(r["status"], "pass", r)
        c = self.checks(r)
        self.assertTrue(c["citations"] and c["corpus_used"]
                        and c["no_outside"])

    def test_reference_judge_passes_and_catches_the_plant(self):
        r = self.result("judge", "reference")
        self.assertEqual(r["status"], "pass", r)
        self.assertEqual(r["info"]["verdicts"]["C2"], "declined")

    def test_outside_citation_fails(self):
        r = self.result("engine", "rogue")
        self.assertEqual(r["status"], "fail")
        c = self.checks(r)
        self.assertFalse(c["citations"])
        self.assertFalse(c["no_outside"])
        self.assertFalse(c["corpus_used"])          # never asked the corpus

    def test_results_record_provenance(self):
        r = self.result("engine", "reference")
        for key in ("commit", "date", "manifest_sha", "adapter_sha"):
            self.assertTrue(r.get(key), key)


if __name__ == "__main__":
    unittest.main()
