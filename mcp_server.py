"""The corpus interface as an MCP server (stdio), for agentic engines.

Any agent that speaks the Model Context Protocol (Claude Code, Codex CLI,
most agent frameworks) can read the pack's corpus through this server
without a custom connector. It exposes exactly the four read-only calls
of corpus_api.py, returns byte-for-byte what the CLI prints, and gives no
other access: no web, no writes, no raw SQL.

    python mcp_server.py                      # speaks MCP on stdin/stdout

Engine configuration, e.g. for Claude Code or Codex:

    {"mcpServers": {"corpus": {
        "command": "/path/to/.venv/bin/python",
        "args": ["/path/to/conjecture/mcp_server.py"],
        "env": {"CONJECTURE_PACK": "/path/to/pack.yaml",
                "CONJECTURE_CALL_LOG": "/path/to/run.calls.jsonl"}}}}

CONJECTURE_CALL_LOG, when set, appends one JSON line per tool call
(time, tool, arguments, result size), so a run's corpus usage is
recorded by the hub rather than self-reported by the engine. The
corpus_api.py CLI logs to the same file.

Dependency-free on purpose: MCP over stdio is newline-delimited JSON-RPC
2.0, and the four methods an engine needs (initialize, tools/list,
tools/call, ping) fit in this file.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent
sys.path.insert(0, str(HUB))

from corpus_api import MAX_LIMIT, Corpus, call, dumps, log_call  # noqa: E402
from pack import PACK  # noqa: E402

SERVER = {"name": "conjecture-corpus", "version": "1.0.0"}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

WORK_ID = {"type": "string", "description": "OpenAlex work id, e.g. W2141663490"}
TOOLS = [
    {"name": "search",
     "description": ("Full-text search over title, abstract and body of "
                     "every work in the corpus. Terms are ANDed. Returns "
                     "works with a matching snippet, best match first."),
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "free-text terms"},
         "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT,
                   "default": 10},
         "core_only": {"type": "boolean", "default": False,
                       "description": "only works in the field's core topic"},
         "year_max": {"type": "integer",
                      "description": "only works published up to this year"},
     }, "required": ["query"], "additionalProperties": False}},
    {"name": "get_work",
     "description": "One work's metadata and abstract, or null if the id "
                    "is not in the corpus.",
     "inputSchema": {"type": "object", "properties": {"work_id": WORK_ID},
                     "required": ["work_id"], "additionalProperties": False}},
    {"name": "statements",
     "description": ("Sentences mined from a work's full text in which it "
                     "states open problems, limitations, controversies or "
                     "future work, with page numbers."),
     "inputSchema": {"type": "object", "properties": {
         "work_id": WORK_ID,
         "kind": {"type": "string", "description": (
             "optional filter: open_question, controversy, "
             "measurement_gap, future_work or limitation")},
     }, "required": ["work_id"], "additionalProperties": False}},
    {"name": "neighbors",
     "description": "Works citing or cited by this one, inside the corpus.",
     "inputSchema": {"type": "object", "properties": {"work_id": WORK_ID},
                     "required": ["work_id"], "additionalProperties": False}},
]
# all four are read-only lookups over a fixed local corpus: tell clients
# so, which lets agent runtimes auto-approve them
for _t in TOOLS:
    _t["annotations"] = {"readOnlyHint": True, "destructiveHint": False,
                         "idempotentHint": True, "openWorldHint": False}
TOOL_NAMES = {t["name"] for t in TOOLS}


class Server:
    def __init__(self) -> None:
        self._corpus: Corpus | None = None

    @property
    def corpus(self) -> Corpus:
        if self._corpus is None:          # open lazily: initialize stays cheap
            self._corpus = Corpus()
        return self._corpus

    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:                    # notification: never answered
            return None
        try:
            result = self.dispatch(method, msg.get("params") or {})
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": e.code, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS \
                else PROTOCOL_VERSIONS[0]
            return {"protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER,
                    "instructions": (
                        f"Read-only literature corpus for the pack "
                        f"'{PACK.name}' ({PACK.title}). Cite works by "
                        f"their work_id; a work_id not returned by these "
                        f"tools does not exist in the corpus.")}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self.call_tool(params.get("name"),
                                   params.get("arguments") or {})
        raise _RpcError(-32601, f"method not found: {method}")

    def call_tool(self, name: str, args: dict) -> dict:
        if name not in TOOL_NAMES:
            raise _RpcError(-32602, f"unknown tool: {name}")
        try:
            text = dumps(call(self.corpus, name, args))
        except (KeyError, ValueError, TypeError, OSError,
                sqlite3.Error) as e:
            # bad arguments are the caller's to fix, reported as a tool
            # error so the agent can see it and retry
            log_call(name, args, 0, str(e))
            return {"content": [{"type": "text", "text": f"error: {e}"}],
                    "isError": True}
        log_call(name, args, len(text), None)
        return {"content": [{"type": "text", "text": text}],
                "isError": False}


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def main() -> None:
    server = Server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": f"parse error: {e}"}}
        else:
            reply = server.handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
