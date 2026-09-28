"""Judge: Codex over one batch of candidates, cited abstracts inlined."""
from __future__ import annotations

from codex_cli import effort_of, model_of, run


def judge(req) -> str:
    proc = run(req.prompt, cwd=req.hub / "judge",
               model=model_of(req.manifest), effort=effort_of(req.manifest),
               timeout=req.timeout)
    req.raw_path.write_text(proc.stdout + "\n===STDERR===\n" + proc.stderr,
                            encoding="utf-8")
    return proc.stdout
