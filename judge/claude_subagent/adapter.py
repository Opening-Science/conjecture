"""Judge: a Claude subagent dispatched in a Claude Code session (handoff).

First call raises Pending with the task; the agent writes its JSON array
to raw_path; the next call collects it.
"""
from __future__ import annotations

from contract import Pending


def judge(req) -> str:
    if not req.raw_path.exists():
        raise Pending(f"{req.prompt}\n---\nWrite the JSON array to: "
                      f"{req.raw_path}")
    return req.raw_path.read_text(encoding="utf-8")
