"""A minimal MCP client over stdio, for adapters and tests.

Starts a server from an {"command", "args", "env"} config (the shape
contract.mcp_config returns, and the shape agent runtimes take) and
calls its tools. Only what the hub's own adapters need: no
notifications from the server, no sampling, no resources.

    with McpClient(req.mcp) as corpus:
        hits = corpus.call("search", query="glow respiration", limit=5)
"""
from __future__ import annotations

import json
import os
import subprocess


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, config: dict):
        self.p = subprocess.Popen(
            [config["command"], *config.get("args", [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={**os.environ, **config.get("env", {})})
        self._id = 0
        init = self.request("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "conjecture-hub", "version": "1"}})
        self.server = init.get("serverInfo", {})
        self.instructions = init.get("instructions", "")
        self._send({"jsonrpc": "2.0",
                    "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    "params": params or {}})
        line = self.p.stdout.readline()
        if not line:
            raise McpError(f"server closed during {method}")
        reply = json.loads(line)
        if "error" in reply:
            raise McpError(reply["error"].get("message", str(reply)))
        return reply["result"]

    def tools(self) -> list[dict]:
        return self.request("tools/list")["tools"]

    def call(self, name: str, **args):
        """Call a tool and decode its JSON text result."""
        res = self.request("tools/call", {"name": name, "arguments": args})
        text = res["content"][0]["text"]
        if res.get("isError"):
            raise McpError(text)
        return json.loads(text)

    def close(self) -> None:
        if self.p.poll() is None:
            self.p.stdin.close()
            self.p.wait(timeout=10)

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
