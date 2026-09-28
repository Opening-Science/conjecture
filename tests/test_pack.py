"""Pack files load, and overlays (extends:) resolve as documented.

    python -m unittest tests/test_pack.py      (from the repository root)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pack  # noqa: E402  (sets CONJECTURE_PACK)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pack  # noqa: E402


class TestOverlay(unittest.TestCase):
    def setUp(self):
        self.base = _pack.PACK_YAML.resolve()
        self.dir = Path(tempfile.mkdtemp()).resolve()

    def overlay(self, text: str, name: str = "pack.yaml") -> Path:
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_inherits_everything_not_overridden(self):
        b = pack.load(self.base)
        o = pack.load(self.overlay(f"extends: {self.base}\n"))
        for f in ("name", "knowledgebase", "questions_source", "state_dir",
                  "entry_queries", "domain", "measurement_areas"):
            self.assertEqual(getattr(o, f), getattr(b, f), f)
        self.assertEqual(o.path, (self.dir / "pack.yaml").resolve())

    def test_override_paths_resolve_against_the_overlay(self):
        (self.dir / "local").mkdir()
        o = pack.load(self.overlay(
            f"extends: {self.base}\n"
            "corpus:\n  knowledgebase: local/full.sqlite\n"))
        b = pack.load(self.base)
        self.assertEqual(o.knowledgebase, self.dir / "local" / "full.sqlite")
        # the rest of corpus merges key by key, still the base's
        self.assertEqual(o.fieldmap, b.fieldmap)
        self.assertEqual(o.n_works, b.n_works)
        self.assertEqual(o.state_dir, b.state_dir)

    def test_relative_extends(self):
        rel = os.path.relpath(self.base, self.dir)
        o = pack.load(self.overlay(f"extends: {rel}\n"))
        self.assertEqual(o.name, pack.load(self.base).name)
        self.assertEqual(o.state_dir, pack.load(self.base).state_dir)

    def test_loop_is_refused(self):
        a = self.overlay("extends: b.yaml\n", "a.yaml")
        self.overlay("extends: a.yaml\n", "b.yaml")
        with self.assertRaises(ValueError):
            pack.read_raw(a)


if __name__ == "__main__":
    unittest.main()
