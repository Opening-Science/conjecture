"""The MCP server speaks the protocol and returns exactly what the CLI does.

Drives mcp_server.py as a subprocess over stdio, the way an agent client
would, against the test pack's corpus (tests/_pack.py: the toy pack
unless CONJECTURE_PACK says otherwise).

    python -m unittest tests/test_mcp_server.py      (from the repository root)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pack  # noqa: E402,F401  (sets CONJECTURE_PACK)

HUB = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

# a query the pack itself says finds something, and one bare term of it
QUERY = next(iter(PACK.entry_queries.values()))[0]
TERM = max(QUERY.split(), key=len)


def cli(*args: str) -> str:
    return subprocess.run([PY, str(HUB / "corpus_api.py"), *args],
                          capture_output=True, text=True, check=True,
                          cwd=HUB).stdout.rstrip("\n")


class McpSession:
    def __init__(self, env: dict | None = None):
        self.p = subprocess.Popen(
            [PY, str(HUB / "mcp_server.py")], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, cwd=HUB,
            env={**os.environ, **(env or {})})
        self.next_id = 0

    def send(self, method: str, params: dict | None = None,
             notify: bool = False) -> dict | None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        return json.loads(self.p.stdout.readline())

    def close(self) -> None:
        self.p.stdin.close()
        self.p.wait(timeout=10)


class TestMcpServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.log = Path(tempfile.mkdtemp()) / "calls.jsonl"
        cls.s = McpSession({"CONJECTURE_CALL_LOG": str(cls.log)})
        cls.init = cls.s.send("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"}})
        cls.s.send("notifications/initialized", notify=True)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()

    def tool(self, name: str, **args) -> dict:
        return self.s.send("tools/call", {"name": name,
                                          "arguments": args})["result"]

    def test_handshake(self):
        r = self.init["result"]
        self.assertEqual(r["protocolVersion"], "2025-06-18")
        self.assertIn("tools", r["capabilities"])
        self.assertEqual(r["serverInfo"]["name"], "conjecture-corpus")

    def test_lists_exactly_the_four_calls(self):
        tools = self.s.send("tools/list")["result"]["tools"]
        self.assertEqual({t["name"] for t in tools},
                         {"search", "get_work", "statements", "neighbors"})
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["annotations"]["readOnlyHint"])
            self.assertFalse(t["annotations"]["openWorldHint"])

    def test_search_matches_cli(self):
        r = self.tool("search", query=QUERY, limit=3)
        self.assertFalse(r["isError"])
        self.assertEqual(r["content"][0]["text"],
                         cli("search", QUERY, "--limit", "3"))

    def test_get_statements_neighbors_match_cli(self):
        wid = json.loads(cli("search", TERM, "--limit", "1"))[0]["work_id"]
        self.assertEqual(self.tool("get_work", work_id=wid)["content"][0]
                         ["text"], cli("get", wid))
        self.assertEqual(self.tool("statements", work_id=wid)["content"][0]
                         ["text"], cli("statements", wid))
        self.assertEqual(self.tool("neighbors", work_id=wid)["content"][0]
                         ["text"], cli("neighbors", wid))

    def test_unknown_work_is_null_not_error(self):
        r = self.tool("get_work", work_id="W0")
        self.assertFalse(r["isError"])
        self.assertEqual(r["content"][0]["text"], "null")

    def test_bad_arguments_are_tool_errors(self):
        r = self.tool("search", query="  ")          # no usable terms
        self.assertTrue(r["isError"])
        r = self.tool("search")                       # missing query
        self.assertTrue(r["isError"])

    def test_limit_is_capped(self):
        r = self.tool("search", query=TERM, limit=500)
        self.assertLessEqual(len(json.loads(r["content"][0]["text"])), 50)

    def test_protocol_errors(self):
        self.assertEqual(self.s.send("resources/list")["error"]["code"],
                         -32601)
        self.assertEqual(self.s.send("tools/call", {"name": "sql"})
                         ["error"]["code"], -32602)
        self.assertEqual(self.s.send("ping")["result"], {})

    def test_calls_are_logged(self):
        self.tool("search", query=TERM, limit=1)
        lines = [json.loads(x) for x in
                 self.log.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(x["tool"] == "search" and
                            x["args"].get("query") == TERM
                            for x in lines))


if __name__ == "__main__":
    unittest.main()
