"""Engine: the same single Codex agent, reading the corpus over MCP.

Identical to codex-solo except for the retrieval path: the corpus comes
from mcp_server.py as four tools instead of a shell command. The pair
shows whether the access route changes what an engine finds, and this
one is the template for any MCP-speaking agent.
"""
from __future__ import annotations

from codex_cli import effort_of, model_of, run

GUARD = ("IMPORTANT: Do not read or modify files and do not run shell "
         "commands. You are generating research hypotheses; the corpus "
         "tools are your only source.\n\n")


def generate(req) -> str:
    proc = run(GUARD + req.prompt, cwd=req.hub, model=model_of(req.manifest),
               effort=effort_of(req.manifest), timeout=req.timeout,
               mcp=req.mcp)
    req.raw_path.write_text(proc.stdout + "\n===STDERR===\n" + proc.stderr,
                            encoding="utf-8")
    return proc.stdout
