"""v2 draft schemas: field.yaml validates, and the store enforces its rules.

    python -m unittest tests/test_v2_schemas.py      (from the repository root)

Set CONJECTURE_FIELD to a field.yaml to also validate a real field.
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path

import jsonschema
import yaml

SCHEMA = Path(__file__).resolve().parent.parent / "schema"
FIELD_SCHEMA = json.loads((SCHEMA / "field.schema.json").read_text())
STORE_SQL = (SCHEMA / "store_v2.sql").read_text()

MINIMAL = {
    "field_version": 2,
    "name": "toy",
    "title": "Toy field",
    "use": "funding",
    "description": "x" * 200,
    "keywords": ["glow", "moss", "cave"],
    "lenses": {"L": {"title": "Glow", "definition": "y" * 40}},
    "questions": {"source": "questions.md"},
    "prompts": {"domain": "d", "causal_levels": "L1 a", "verifier_setting": "v"},
    "sources": {"openalex": {"enabled": True}},
    "growth": {
        "routes": ["keyword"],
        "relevance": {"embedding_model": "m", "labeller": "human"},
        "stop": {"min_relevant_share": 0.05, "window": 500},
        "budget": {"works": 1000},
    },
    "outputs": {"dir": "outputs"},
    "state": "state",
}


def errors(field: dict) -> list[str]:
    v = jsonschema.Draft202012Validator(FIELD_SCHEMA)
    return [e.message for e in v.iter_errors(field)]


class TestFieldSchema(unittest.TestCase):
    def test_schema_is_valid(self):
        jsonschema.Draft202012Validator.check_schema(FIELD_SCHEMA)

    def test_minimal_field_validates(self):
        self.assertEqual(errors(MINIMAL), [])

    def test_unknown_source_rejected(self):
        f = copy.deepcopy(MINIMAL)
        f["sources"]["scholarx"] = {"enabled": True}
        self.assertTrue(errors(f))

    def test_proposals_only_in_funding_fields(self):
        f = copy.deepcopy(MINIMAL)
        f["documents"] = [{"title": "P", "kind": "proposal", "path": "p.pdf"}]
        self.assertEqual(errors(f), [])
        f["use"] = "investment"
        f["audit"] = {"decision_contexts": ["investment"]}
        self.assertTrue(errors(f))

    def test_funding_field_cannot_serve_investment(self):
        f = copy.deepcopy(MINIMAL)
        f["audit"] = {"decision_contexts": ["funding_call", "investment"]}
        self.assertTrue(errors(f))

    @unittest.skipUnless(os.environ.get("CONJECTURE_FIELD"), "no real field")
    def test_real_field_validates(self):
        f = yaml.safe_load(Path(os.environ["CONJECTURE_FIELD"]).read_text())
        self.assertEqual(errors(f), [])


class TestStore(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(STORE_SQL)
        self.db.executescript("""
            INSERT INTO works(work_id, title) VALUES ('W1', 'a'), ('W2', 'b');
            INSERT INTO work_sources VALUES ('W1', 'openalex', 'W1', NULL),
                                            ('W2', 'semantic_scholar', 's2', NULL);
            INSERT INTO citations VALUES ('W1', 'W2', 'semantic_scholar'),
                                         ('W2', 'W1', 'openalex'),
                                         ('W2', 'W1', 'grobid');
        """)

    def ask(self, context: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO snapshots VALUES "
                        "('s', 't', NULL, 'h', '{}', NULL)")
        self.db.execute(
            "INSERT INTO asks(ask_id, created, requester, decision_context,"
            " question, modes, snapshot, status) VALUES"
            " (?, 't', 'me', ?, 'q', '[]', 's', 'answered')",
            (f"a-{context}", context))

    def test_commercial_views_drop_s2_only_rows(self):
        works = [r[0] for r in self.db.execute("SELECT work_id FROM works_commercial")]
        self.assertEqual(works, ["W1"])
        edges = self.db.execute("SELECT src_work_id, dst_work_id FROM citations_commercial").fetchall()
        self.assertEqual(edges, [("W2", "W1")])

    def test_citation_support_counts_sources(self):
        n = self.db.execute("SELECT n_sources FROM citation_support"
                            " WHERE src_work_id = 'W2'").fetchone()[0]
        self.assertEqual(n, 2)

    def test_phantom_refs_dropped_from_commercial_edges(self):
        self.db.execute("INSERT INTO phantom_refs VALUES ('W1', 'misattributed')")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM citations_commercial").fetchone()[0], 0)

    def test_firewall_blocks_investment_after_proposal(self):
        self.db.execute("INSERT INTO works(work_id, title) VALUES ('P1', 'proposal')")
        self.db.execute("INSERT INTO documents(work_id, kind) VALUES ('P1', 'proposal')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "firewall"):
            self.ask("investment")
        self.ask("funding_call")

    def test_firewall_blocks_proposal_after_investment(self):
        self.ask("investment")
        self.db.execute("INSERT INTO works(work_id, title) VALUES ('P1', 'proposal')")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "firewall"):
            self.db.execute("INSERT INTO documents(work_id, kind) VALUES ('P1', 'proposal')")

    def test_unknown_source_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO citations VALUES ('W1', 'W9', 'scholarx')")


if __name__ == "__main__":
    unittest.main()
