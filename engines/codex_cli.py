"""Run one prompt through the Codex CLI, isolated from the user's setup.

Shared by the Codex engines and the Codex judge. --ignore-user-config
matters: a user's ~/.codex/config.toml can enable plugins (a browser,
literature search) that would give the engine a retrieval path around
the corpus. Auth still comes from CODEX_HOME, so no key is needed. The
model is pinned from the manifest rather than inherited from that file.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path

GUARD = (
    "IMPORTANT: Do NOT read or execute any files under ~/.claude/, "
    ".claude/skills/, or agents/. Do not modify any file. You are "
    "generating research hypotheses, not editing this repository.\n\n")


def toml(v) -> str:
    """A Python value as a TOML literal, for -c overrides."""
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {toml(x)}" for k, x in v.items()) + "}"
    return json.dumps(v)          # strings and lists of strings coincide


def run(prompt: str, *, cwd: Path, model: str, effort: str = "high",
        timeout: int = 900, mcp: dict | None = None
        ) -> subprocess.CompletedProcess:
    cmd = ["codex", "exec", prompt, "-C", str(cwd), "-s", "read-only",
           "--ignore-user-config",
           "-c", f"model={toml(model)}",
           "-c", f"model_reasoning_effort={toml(effort)}"]
    if mcp is not None:
        for key in ("command", "args", "env"):
            cmd += ["-c", f"mcp_servers.corpus.{key}={toml(mcp[key])}"]
    return subprocess.run(cmd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=timeout)


def model_of(manifest) -> str:
    """'gpt-6-astra, effort high' -> 'gpt-6-astra'."""
    return manifest["model"].split(",")[0].strip()


def effort_of(manifest) -> str:
    m = manifest["model"]
    return m.split("effort", 1)[1].strip() if "effort" in m else "high"


CORPUS_CMD = re.compile(r"corpus_api\.py\s+(search|get|statements|neighbors)"
                        r"\s+(.*)$")
TOOL = {"get": "get_work"}


def transcript_calls(text: str) -> list[dict]:
    """Corpus CLI calls in a Codex transcript, as call-log records.

    Codex prints each command it runs on the line after "exec". Inside
    the read-only sandbox corpus_api.py cannot append to the hub's call
    log, so this is how a CLI engine's corpus use is observed.
    """
    out = []
    lines = text.splitlines()
    for prev, line in zip(lines, lines[1:]):
        if prev.strip() != "exec":
            continue
        m = re.match(r"""\S+ -lc (['"])(.*)\1 in \S""", line)
        cmd = m.group(2) if m else line
        hit = CORPUS_CMD.search(cmd)
        if not hit:
            continue
        try:
            argv = shlex.split(hit.group(2))
        except ValueError:
            argv = hit.group(2).split()
        out.append({"t": None, "tool": TOOL.get(hit.group(1), hit.group(1)),
                    "args": {"argv": argv}, "chars": None, "error": None,
                    "source": "codex transcript"})
    return out


def record_cli_calls(req, transcript: str) -> None:
    """Fill the hub's call log from the transcript if the sandbox kept
    corpus_api.py from writing it."""
    path = Path(req.mcp["env"]["CONJECTURE_CALL_LOG"])
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return
    with open(path, "a", encoding="utf-8") as f:
        for rec in transcript_calls(transcript):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
