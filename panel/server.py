"""The run panel's local server: the pages, the pack's data, the run trigger.

Serves the panel for the active pack (pack.yaml, as for every hub script)
and builds its data on each request, so it is never stale:

    GET  /pack.json    the pack, its questions, every engine and judge
    GET  /data.json    the results of the pack's runs
    GET  /ledger.json  the pack's per-candidate ledger
    GET  /findings.html  the pack's own write-up of its findings, if any

and, for the Run page, five endpoints that do something real:

    GET  /api/status   what keys exist (masked), what is running, what ran
    POST /api/keys     store API keys into hub/.env  (0600, gitignored)
    POST /api/run      launch a whitelisted job sequence
    POST /api/stop     terminate the running sequence
    GET  /api/log      tail of the current/last run log

Design decisions that matter:

- Binds 127.0.0.1 only. This is a local instrument panel, not a service.
- Jobs are a fixed whitelist of argv lists. Nothing from the browser is
  ever interpolated into a shell string; unknown job ids are refused.
  The one browser-supplied parameter — which claims theoria verifies —
  is accepted only by membership in the adapter's own claims file and
  passed as its own argv element, never through a shell.
- theoria never sweeps. Each claim is ~30 min of gpt-5.5 on the Codex
  subscription, so the job starts only with an explicit claim selection;
  an empty selection is a 400, and the adapter itself refuses a bare
  --run for the same reason.
- Jobs and key names are derived from the adapter manifests at start-up:
  one generation job per built, self-driving engine, one judging job per
  built, self-driving judge. The no-model reference adapters are left
  out: their output would sit among a real pack's runs.
- Keys land in the hub's .env with mode 0600 and are echoed back only as
  ****last4. The server never logs them and the page never re-reads them.
- One run at a time. A second /api/run while busy is a 409, not a queue.

    python panel/server.py [port]           (from the hub, with its deps)

For a read-only copy that needs no server, see export.py.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PANEL = Path(__file__).resolve().parent
HUB = PANEL.parent
sys.path.insert(0, str(HUB))
sys.path.insert(0, str(PANEL))

import build_data  # noqa: E402
import contract  # noqa: E402
from pack import PACK  # noqa: E402

PY = sys.executable
ENV_FILE = HUB / ".env"
LOG = PACK.runs_dir / "ui_run.log"
ALLOWED_KEYS = build_data.pack_json()["keys"]


def build_jobs() -> dict[str, dict]:
    """The whitelist, from the manifests.

    It IS the security model, and the honesty model: only what truly runs
    unattended gets an id. Handoff adapters (Claude subagents) are absent,
    because they emit tasks for a session; a button that "ran" them would
    be pretending.
    """
    jobs: dict[str, dict] = {}
    runnable = [m for m in contract.discover()
                if m.built and m["invocation"] == "self-driving"
                and m["backend"] != "none"]
    for m in (m for m in runnable if m.kind == "engine"):
        had = list(PACK.runs_dir.glob(f"*.{m.name}.json"))
        jobs[f"gen-{m.name}"] = {
            "label": f"Generate: {m.name}, every question",
            "argv": [PY, "run_engine.py", m.name, "--all"],
            "needs": m.missing(),
            "warn": (f"overwrites the existing {m.name} run files"
                     if had else None)}
    for m in (m for m in runnable if m.kind == "judge"):
        jobs[f"judge-{m.name}"] = {
            "label": f"Judge: {m.name}, over the certification chunks",
            "argv": [PY, "run_judge.py", m.name], "needs": m.missing()}
    jobs["collect-verdicts"] = {
        "label": "Collect judge verdicts",
        "argv": [PY, "judge/collect_verdicts.py"]}
    if (HUB / "judge" / "theoria_adapter.py").is_file():
        jobs["theoria"] = {
            "label": "Verify: theoria over the claims picked below",
            "argv": [PY, "judge/theoria_adapter.py", "--run", "--timeout",
                     "2400"],
            "claims": True}      # requires an explicit selection; never sweeps
    jobs["rebuild"] = {
        "label": "Rebuild: audit.db, ledger",
        "argv": [PY, "scoreboard/score.py"],
        "then": [[PY, "scoreboard/build_ledger.py"]]}
    return jobs


JOBS = build_jobs()

STATE = {"busy": False, "current": None, "done": [], "started": None}
LOCK = threading.Lock()
PROC: subprocess.Popen | None = None


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def save_keys(new: dict[str, str]) -> dict:
    env = load_env()
    for k, v in new.items():
        if k not in ALLOWED_KEYS:
            return {"error": f"unknown key name {k!r}"}
        v = v.strip()
        if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in v):
            # a newline here would inject an arbitrary line into .env, and
            # from there an arbitrary env var into every pipeline subprocess
            return {"error": f"{k}: control characters are not allowed"}
        if v:
            env[k] = v
        else:
            env.pop(k, None)          # empty value = remove the key
    body = "".join(f"{k}={v}\n" for k, v in env.items())
    tmp = ENV_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    os.replace(tmp, ENV_FILE)         # never a 0644 window, never truncated
    return {"keys": masked()}


def masked() -> dict:
    env = load_env()
    return {k: (f"****{env[k][-4:]}" if k in env and len(env[k]) > 7 else None)
            for k in ALLOWED_KEYS}


def theoria_queue() -> list[dict]:
    """The pickable claims: id and current verdict, from the adapter's files."""
    cj = PACK.judge_dir / "theoria_claims.json"
    vj = PACK.judge_dir / "verdicts.theoria.json"
    if not cj.exists():
        return []
    verdicts = {}
    if vj.exists():
        verdicts = {v["candidate_id"]: v.get("verdict")
                    for v in json.loads(vj.read_text(encoding="utf-8"))
                    if "candidate_id" in v}
    return [{"id": c["candidate_id"], "seed": c.get("seed_id"),
             "steps": c.get("n_computation_steps"),
             "verdict": verdicts.get(c["candidate_id"])}
            for c in json.loads(cj.read_text(encoding="utf-8"))]


def run_sequence(ids: list[str], claims: list[str]) -> None:
    try:
        _run_sequence(ids, claims)
    finally:
        # whatever happened — missing venv, permission error, crash — the
        # panel must not be wedged "busy" with a dead worker behind it.
        with LOCK:
            STATE["busy"] = False
            STATE["current"] = None


def _run_sequence(ids: list[str], claims: list[str]) -> None:
    global PROC
    LOG.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **load_env()}
    with LOG.open("w") as log:
        for jid in ids:
            job = JOBS[jid]
            argvs = [list(job["argv"])] + [list(t) for t in job.get("then", [])]
            if job.get("claims"):
                argvs[0] += ["--only", ",".join(claims)]
            for argv in argvs:
                with LOCK:
                    if not STATE["busy"]:            # stopped
                        return
                    STATE["current"] = jid
                log.write(f"\n=== {time.strftime('%H:%M:%S')}  {job['label']}"
                          f"\n=== {' '.join(Path(a).name for a in argv)}\n")
                log.flush()
                PROC = subprocess.Popen(
                    argv, cwd=HUB, env=env, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True)
                rc = PROC.wait()
                if rc != 0:
                    log.write(f"\n=== {jid} exited {rc} — sequence stopped\n")
                    break
            with LOCK:
                STATE["done"].append({"id": jid, "rc": rc})
            if rc != 0:
                break
    with LOCK:
        PROC = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(PANEL), **kw)

    def log_message(self, *a):        # quiet; the run log is the log
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = min(int(self.headers.get("Content-Length", 0)), 65536)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def _file(self, path: Path, ctype: str):
        if not path.is_file():
            return self._json({"error": f"{path.name} not built"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/pack.json":
            return self._json(build_data.pack_json(local=True))
        if route == "/data.json":
            try:
                return self._json(build_data.data_json())
            except (sqlite3.Error, OSError, KeyError) as e:
                return self._json({"error": f"no results yet: {e}"}, 404)
        if route == "/ledger.json":
            return self._file(PACK.ledger, "application/json")
        if route == "/findings.html":
            return self._file(PACK.outputs_dir / "panel" / "findings.html",
                              "text/html; charset=utf-8")
        if route.startswith("/fonts/") and not (PANEL / route[1:]).exists():
            # licensed fonts are optional; the CSS falls back without noise
            self.send_response(204)
            self.end_headers()
            return None
        if self.path.startswith("/api/status"):
            with LOCK:
                s = {**STATE, "keys": masked(),
                     "jobs": {k: {"label": v["label"],
                                  "warn": v.get("warn"),
                                  "needs": v.get("needs") or [],
                                  **({"claims": theoria_queue()}
                                     if v.get("claims") else {})}
                              for k, v in JOBS.items()}}
            return self._json(s)
        if self.path.startswith("/api/log"):
            txt = LOG.read_text()[-20000:] if LOG.exists() else ""
            return self._json({"log": txt})
        # cache killer for the iteration loop: everything revalidates
        self.protocol_version = "HTTP/1.1"
        return super().do_GET()

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _cross_origin(self) -> bool:
        # loopback binding is not authentication: any page in the user's
        # browser can POST to 127.0.0.1. Require the Host to be loopback and,
        # when an Origin is present, require it to be this same server.
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return True
        origin = self.headers.get("Origin")
        if origin is not None:
            from urllib.parse import urlparse
            oh = urlparse(origin).hostname
            if oh not in ("127.0.0.1", "localhost"):
                return True
        return False

    def do_POST(self):
        if self._cross_origin():
            return self._json({"error": "cross-origin request refused"}, 403)
        if self.path == "/api/keys":
            data = self._body()
            out = save_keys({k: str(v) for k, v in data.items()
                             if isinstance(v, str)})
            return self._json(out, 400 if "error" in out else 200)
        if self.path == "/api/run":
            body = self._body()
            ids = [i for i in body.get("jobs", []) if i in JOBS]
            if not ids:
                return self._json({"error": "no runnable jobs selected"}, 400)
            blocked = [f"{i} needs {', '.join(JOBS[i]['needs'])}"
                       for i in ids if JOBS[i].get("needs")]
            if blocked:
                return self._json({"error": "; ".join(blocked)}, 400)
            claims: list[str] = []
            if any(JOBS[i].get("claims") for i in ids):
                known = {c["id"] for c in theoria_queue()}
                claims = [c for c in body.get("claims", [])
                          if isinstance(c, str) and c in known]
                if not claims:
                    return self._json(
                        {"error": "theoria verifies only claims named "
                                  "explicitly — pick at least one"}, 400)
            with LOCK:
                if STATE["busy"]:
                    return self._json({"error": "a run is already in "
                                       "progress"}, 409)
                STATE.update(busy=True, current=ids[0], done=[],
                             started=time.strftime("%H:%M:%S"))
            threading.Thread(target=run_sequence, args=(ids, claims),
                             daemon=True).start()
            return self._json({"started": ids, "claims": claims})
        if self.path == "/api/stop":
            with LOCK:
                STATE["busy"] = False
            if PROC and PROC.poll() is None:
                os.killpg(os.getpgid(PROC.pid), signal.SIGTERM)
            return self._json({"stopped": True})
        return self._json({"error": "unknown endpoint"}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"Conjecture run panel for pack '{PACK.name}' on "
          f"http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
