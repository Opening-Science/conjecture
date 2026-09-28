"""The corpus builder's configuration and safety properties (offline).

    python -m unittest tests/test_builder.py      (from the repository root)

That the builder reproduces a real pack's corpus is checked against the
biophoton pack's cache, not here: it needs gigabytes of cached OpenAlex
records and the network.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pack  # noqa: E402  (sets CONJECTURE_PACK)

HUB = Path(__file__).resolve().parent.parent
BUILDER = HUB / "builder"
sys.path.insert(0, str(BUILDER))


def fresh_config(pack_yaml: Path, **env):
    """builder/config.py re-imported against another pack."""
    old = {k: os.environ.get(k) for k in ("CONJECTURE_PACK", *env)}
    os.environ["CONJECTURE_PACK"] = str(pack_yaml)
    os.environ.update(env)
    try:
        for m in ("pack", "config"):
            sys.modules.pop(m, None)
        return importlib.import_module("config")
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for m in ("pack", "config"):
            sys.modules.pop(m, None)


class TestConfig(unittest.TestCase):
    def test_defaults_without_a_build_block(self):
        C = fresh_config(_pack.toy_pack())
        base = _pack.toy_pack().parent.resolve()
        self.assertEqual(C.WORKDIR, base / "build")
        self.assertEqual(C.CACHE, base / "build" / "cache")
        self.assertEqual(C.KB_PATH, (base / "knowledgebase.sqlite").resolve())
        self.assertIsNone(C.SEEDS_CSV)
        self.assertEqual(C.CORE_TOPIC_HINTS, ())
        self.assertEqual(C.HOP1_MIN_LINKS, 2)

    def test_overlay_paths_resolve_against_the_file_that_sets_them(self):
        d = Path(tempfile.mkdtemp()).resolve()
        (d / "base").mkdir()
        base = d / "base" / "pack.yaml"
        base.write_text(_pack.toy_pack().read_text() + (
            "\nbuild:\n  seeds: seeds.csv\n  core_topic_hints: [Glow]\n"
            "  expansion: {hop2_min_links: 4}\n"))
        over = d / "pack.yaml"
        over.write_text(f"extends: base/pack.yaml\nbuild:\n  paths:\n"
                        f"    cache: shared/cache\n")
        C = fresh_config(over)
        self.assertEqual(C.SEEDS_CSV, d / "base" / "seeds.csv")
        self.assertEqual(C.CACHE, d / "shared" / "cache")
        self.assertEqual(C.CORE_TOPIC_HINTS, ("glow",))
        self.assertEqual(C.HOP2_MIN_LINKS, 4)

    def test_hops_are_one_or_two(self):
        d = Path(tempfile.mkdtemp()).resolve()
        for hops, ok in ((1, True), (2, True), (3, False)):
            p = d / f"h{hops}.yaml"
            p.write_text(f"extends: {_pack.toy_pack()}\n"
                         f"build:\n  expansion: {{hops: {hops}}}\n")
            if ok:
                self.assertEqual(fresh_config(p).HOPS, hops)
            else:
                with self.assertRaises(ValueError):
                    fresh_config(p)

    def test_credentials_only_from_the_environment(self):
        C = fresh_config(_pack.toy_pack(), OPENALEX_API_KEY="sekret-123",
                         OPENALEX_MAILTO="a@b.c")
        self.assertEqual((C.API_KEY, C.MAILTO), ("sekret-123", "a@b.c"))


class TestOpenAlexClient(unittest.TestCase):
    def test_key_is_redacted_from_http_errors(self):
        import httpx
        fresh_config(_pack.toy_pack(), OPENALEX_API_KEY="sekret-123")
        sys.modules.pop("openalex", None)
        os.environ["OPENALEX_API_KEY"] = "sekret-123"
        try:
            oa = importlib.import_module("openalex")
            req = httpx.Request("GET", "https://api.openalex.org/works?"
                                "api_key=sekret-123")
            resp = httpx.Response(500, request=req)
            with self.assertRaises(httpx.HTTPStatusError) as e:
                oa._check(resp)
            self.assertNotIn("sekret-123", str(e.exception))
            self.assertIn("<OPENALEX_API_KEY>", str(e.exception))
        finally:
            os.environ.pop("OPENALEX_API_KEY", None)
            for m in ("openalex", "config", "pack"):
                sys.modules.pop(m, None)


class TestStatementTerms(unittest.TestCase):
    def test_pack_gap_terms_extend_the_hub_vocabulary(self):
        import re
        hub = re.compile("|".join((r"detection limit", r"traceab")), re.I)
        pack = re.compile("|".join((r"detection limit", r"traceab",
                                    r"dark[- ]count")), re.I)
        for text in ("detection limit", "traceable", "dark count"):
            self.assertLessEqual(bool(hub.search(text)),
                                 bool(pack.search(text)))


class TestRunner(unittest.TestCase):
    def run_py(self, *args):
        return subprocess.run([sys.executable, str(BUILDER / "run.py"), *args],
                              capture_output=True, text=True)

    def test_lists_stages_in_dependency_order(self):
        order = [line.split()[0] for line in
                 self.run_py("--list").stdout.splitlines() if line.strip()]
        self.assertEqual(order, ["A", "B", "C", "E", "index", "I", "J", "K",
                                 "refs"])

    def test_unknown_stage_is_refused(self):
        self.assertNotEqual(self.run_py("Z").returncode, 0)


if __name__ == "__main__":
    unittest.main()
