"""Engine: a single Codex agent reading the corpus through the CLI.

Architecturally the simplest possible engine: one agent, one pass,
tools. It exists to be the control that multi-agent architectures must
beat, run on a model family that is not Claude so the first scoreboard
is cross-model. The CLI runs the corpus commands itself in a read-only
sandbox; each one is logged by the hub, from the transcript when the
sandbox keeps the CLI from writing the log itself.
"""
from __future__ import annotations

from codex_cli import GUARD, effort_of, model_of, record_cli_calls, run


def generate(req) -> str:
    proc = run(GUARD + req.prompt, cwd=req.hub, model=model_of(req.manifest),
               effort=effort_of(req.manifest), timeout=req.timeout)
    req.raw_path.write_text(proc.stdout + "\n===STDERR===\n" + proc.stderr,
                            encoding="utf-8")
    record_cli_calls(req, proc.stdout + "\n" + proc.stderr)
    return proc.stdout
