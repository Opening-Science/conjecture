"""Engine: a single Claude agent with corpus tool access (handoff).

The Claude counterpart of codex-solo, and the same architecture (one
agent, one pass, tools), so that any difference on the scoreboard is a
model-family difference rather than an architecture difference.

Claude inference here comes from a subagent dispatched inside a Claude
Code session rather than from an API key, because a nested `claude -p`
cannot authenticate from inside one. So the first call raises Pending
with the prompt to dispatch; the agent writes its answer to raw_path;
the next call collects it.
"""
from __future__ import annotations

from contract import Pending


def generate(req) -> str:
    if not req.raw_path.exists():
        raise Pending(f"{req.prompt}\n---\nWrite your JSON answer to: "
                      f"{req.raw_path}\n[config_hash {req.config_hash}]")
    return req.raw_path.read_text(encoding="utf-8")
