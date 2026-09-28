"""The adapter contract: how an engine or a judge plugs into the hub.

An adapter is a directory with a manifest and, once built, one module:

    engines/<dir>/engine.yaml    what it is (schema/adapter.schema.json)
    engines/<dir>/adapter.py     def generate(req: EngineRequest) -> str | dict
    judge/<dir>/judge.yaml
    judge/<dir>/adapter.py       def judge(req: JudgeRequest) -> str | list

A manifest without adapter.py is an engine that is designed but not
built; it still appears in the status table, with its blocker. Adapters
outside the hub are found through $CONJECTURE_ADAPTER_PATH.

The adapter's job is narrow on purpose. An engine adapter turns a
question into an answer: raw model text, or a HOF dict if the engine has
its own output shape. Everything around that is the hub's, so it is the
same for every engine: the shared prompt, the corpus server and its call
log, HOF extraction and normalisation, citation checks, where runs are
saved. A judge adapter turns a batch of candidates into verdicts, and
the hub checks them against schema/verdict.schema.json.

An adapter that needs an agent outside the hub (a Claude Code subagent,
a person) raises Pending with the task; the same call collects the
answer once it has been written to req.raw_path.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent
SCHEMA_DIR = HUB / "schema"
ROOTS = {"engine": HUB / "engines", "judge": HUB / "judge"}
PY = sys.executable

sys.path.insert(0, str(HUB))
sys.path.insert(0, str(HUB / "engines"))


class Pending(Exception):
    """The answer has to come from outside the hub; str(e) is the task."""


# -- manifests ---------------------------------------------------------

@dataclass
class Manifest:
    path: Path
    data: dict

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def kind(self) -> str:
        return self.data["kind"]

    @property
    def adapter_path(self) -> Path:
        return self.dir / "adapter.py"

    @property
    def built(self) -> bool:
        return self.adapter_path.is_file()

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def missing(self) -> list[str]:
        """Requirements this machine does not meet, for a skip reason."""
        req = self.data.get("requires") or {}
        out = [f"command {c}" for c in req.get("commands") or []
               if shutil.which(c) is None]
        out += [f"${e}" for e in req.get("env") or [] if not os.environ.get(e)]
        any_ = req.get("env_any") or []
        if any_ and not any(os.environ.get(e) for e in any_):
            out.append("one of " + ", ".join(f"${e}" for e in any_))
        return out


def check_manifest(data: dict) -> list[str]:
    import jsonschema
    schema = json.loads((SCHEMA_DIR / "adapter.schema.json").read_text())
    probs = [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
             for e in jsonschema.Draft202012Validator(schema)
             .iter_errors(data)]
    if data.get("corpus_access") == "connector" and not data.get("connector"):
        probs.append("corpus_access connector needs a connector: entry")
    return probs


def read_manifest(path: Path) -> Manifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    probs = check_manifest(data)
    if probs:
        raise ValueError(f"{path}: " + "; ".join(probs))
    want = {"engine.yaml": "engine", "judge.yaml": "judge"}[path.name]
    if data["kind"] != want:
        raise ValueError(f"{path}: kind {data['kind']!r} in {path.name}")
    return Manifest(path, data)


def roots(kind: str) -> list[Path]:
    """The hub's own adapter directory, then any on $CONJECTURE_ADAPTER_PATH
    (os.pathsep-separated), so adapters can live outside the hub."""
    extra = [Path(d).expanduser() for d in
             os.environ.get("CONJECTURE_ADAPTER_PATH", "").split(os.pathsep)
             if d]
    return [ROOTS[kind], *extra]


def discover(kind: str | None = None) -> list[Manifest]:
    kinds = [kind] if kind else ["engine", "judge"]
    out = []
    for k in kinds:
        for root in roots(k):
            for p in sorted(root.glob(f"*/{k}.yaml")):
                out.append(read_manifest(p))
    names = [(m.kind, m.name) for m in out]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"duplicate adapter names: {sorted(dup)}")
    return out


def get(kind: str, name: str) -> Manifest:
    for m in discover(kind):
        if m.name == name:
            return m
    known = ", ".join(m.name for m in discover(kind))
    raise KeyError(f"no {kind} named {name!r} (known: {known})")


def load_adapter(m: Manifest):
    if not m.built:
        raise LookupError(f"{m.name} is designed, not built: "
                          f"{m.get('blocker') or 'no adapter.py'}")
    spec = importlib.util.spec_from_file_location(
        f"conjecture_adapter_{m.kind}_{m.name.replace('-', '_')}",
        m.adapter_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    entry = "generate" if m.kind == "engine" else "judge"
    if not callable(getattr(mod, entry, None)):
        raise TypeError(f"{m.adapter_path} defines no {entry}()")
    return mod


# -- corpus access handed to adapters ------------------------------------

def mcp_config(call_log: Path | None) -> dict:
    """How to start the corpus MCP server for the active pack."""
    from pack import PACK
    env = {"CONJECTURE_PACK": str(PACK.path)}
    if call_log is not None:
        env["CONJECTURE_CALL_LOG"] = str(call_log)
    return {"command": PY, "args": [str(HUB / "mcp_server.py")], "env": env}


def read_calls(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in
            path.read_text(encoding="utf-8").splitlines() if x.strip()]


# -- engines -----------------------------------------------------------

@dataclass
class EngineRequest:
    seed_id: str
    seed: dict                 # the seed brief (seeds/<id>.json)
    prompt: str                # the shared prompt, for engines that take one
    config_hash: str
    manifest: Manifest
    raw_path: Path             # where the adapter keeps its raw output
    mcp: dict                  # command/args/env for the corpus server
    timeout: int = 900
    hub: Path = HUB


def run_engine(m: Manifest, seed_id: str, *, timeout: int = 900) -> dict:
    """One question through one engine; returns a result record.

    Raises Pending for handoff engines whose answer is not in yet.
    """
    from collect import extract_json, normalise, save
    from corpus_api import Corpus
    from hof import validate
    from pack import PACK
    from prompt import build

    access = m["corpus_access"]
    handoff = m["invocation"] == "handoff"
    raw_dir = PACK.runs_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{seed_id}.{m.name}.txt"
    calls = raw_dir / f"{seed_id}.{m.name}.calls.jsonl"
    py = PY
    if handoff and access == "cli":
        # the dispatched agent's shell is not ours: name the pack and the
        # call log in the command itself (config_hash is unaffected)
        py = (f"CONJECTURE_PACK={shlex.quote(str(PACK.path))} "
              f"CONJECTURE_CALL_LOG={shlex.quote(str(calls))} {py}")
    prompt, chash = build(seed_id, m.name, m["backend"], python_bin=py,
                          access=access if access in ("cli", "mcp") else
                          "cli")
    seed = json.loads((PACK.seeds_dir / f"{seed_id}.json").read_text())
    adapter = load_adapter(m)

    if not handoff:              # a fresh run: no stale output survives
        calls.unlink(missing_ok=True)
        raw_path.unlink(missing_ok=True)
    # CLI engines inherit the log path through the environment; MCP
    # engines get it in the server config. Either way the hub counts.
    old = os.environ.get("CONJECTURE_CALL_LOG")
    os.environ["CONJECTURE_CALL_LOG"] = str(calls)
    t0 = time.time()
    try:
        out = adapter.generate(EngineRequest(
            seed_id=seed_id, seed=seed, prompt=prompt, config_hash=chash,
            manifest=m, raw_path=raw_path, mcp=mcp_config(calls),
            timeout=timeout))
    finally:
        if old is None:
            os.environ.pop("CONJECTURE_CALL_LOG", None)
        else:
            os.environ["CONJECTURE_CALL_LOG"] = old
    elapsed = round(time.time() - t0, 1)

    if isinstance(out, str):
        if not raw_path.exists():    # adapters may keep a fuller record
            raw_path.write_text(out, encoding="utf-8")
        payload = extract_json(out)
    else:
        payload = out
    result = {"seed_id": seed_id, "engine": m.name, "elapsed_s": elapsed,
              "raw_path": str(raw_path),
              "corpus_calls_observed": len(read_calls(calls))}
    if payload is None:
        return {**result, "ok": False, "error": "no parseable HOF in output"}
    extra = {} if handoff else {"elapsed_s": elapsed}
    payload = normalise(payload, m.name, seed_id, m["backend"], chash,
                        **extra)
    if not handoff:
        payload["run"]["corpus_calls_observed"] = \
            result["corpus_calls_observed"]
    path = save(payload, PACK.runs_dir, seed_id, m.name)
    return {**result, "ok": True, "path": str(path), "payload": payload,
            "n": len(payload.get("hypotheses", [])),
            "problems": validate(payload, corpus=Corpus())}


# -- judges ------------------------------------------------------------


@dataclass
class JudgeRequest:
    items: list[dict]          # candidates, cited abstracts inlined
    prompt: str                # certify.JUDGE_PROMPT, then the items
    manifest: Manifest
    label: str                 # verdicts.<label>.json; several passes of
    raw_path: Path             # one judge get distinct labels
    timeout: int = 1200
    hub: Path = HUB


def judge_prompt(items: list[dict]) -> str:
    sys.path.insert(0, str(HUB / "judge"))
    from certify import JUDGE_PROMPT
    return (JUDGE_PROMPT + "\n"
            + json.dumps(items, indent=1, ensure_ascii=False))


def extract_verdicts(text: str) -> list | None:
    """Largest JSON array of verdict objects in a model's answer."""
    best = None
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            arr, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if (isinstance(arr, list) and arr and isinstance(arr[0], dict)
                and "candidate_id" in arr[0]):
            if best is None or len(arr) > len(best):
                best = arr
    return best


def check_verdicts(verdicts, items: list[dict]) -> list[str]:
    import jsonschema
    schema = json.loads((SCHEMA_DIR / "verdict.schema.json").read_text())
    probs = [f"verdicts[{'/'.join(map(str, e.path))}]: {e.message}"
             for e in jsonschema.Draft202012Validator(schema)
             .iter_errors(verdicts)]
    if not isinstance(verdicts, list):
        return probs
    want = [c["candidate_id"] for c in items]
    got = [v.get("candidate_id") for v in verdicts if isinstance(v, dict)]
    probs += [f"no verdict for {c}" for c in want if c not in got]
    probs += [f"verdict for unknown candidate {c}" for c in got
              if c not in want]
    probs += [f"{c} judged {got.count(c)} times" for c in set(got)
              if got.count(c) > 1]
    return probs


def run_judge(m: Manifest, items: list[dict], *, label: str | None = None,
              tag: str = "batch", timeout: int = 1200,
              raw_dir: Path | None = None) -> dict:
    """One batch through one judge; raises Pending for handoff judges."""
    from pack import PACK
    label = label or m.name
    raw_dir = raw_dir or PACK.judge_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{label}.{tag}.txt"
    adapter = load_adapter(m)
    t0 = time.time()
    out = adapter.judge(JudgeRequest(
        items=items, prompt=judge_prompt(items), manifest=m, label=label,
        raw_path=raw_path, timeout=timeout))
    elapsed = round(time.time() - t0, 1)
    if isinstance(out, str):
        raw_path.write_text(out, encoding="utf-8")
        out = extract_verdicts(out)
    if out is None:
        return {"ok": False, "error": "no parseable verdict array",
                "elapsed_s": elapsed}
    return {"ok": True, "verdicts": out, "elapsed_s": elapsed,
            "problems": check_verdicts(out, items)}


@dataclass
class Registry:
    """Adapters grouped for display: built first, then designed."""
    engines: list[Manifest] = field(default_factory=list)
    judges: list[Manifest] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Registry":
        key = lambda m: (not m.built, m.name)  # noqa: E731
        return cls(sorted(discover("engine"), key=key),
                   sorted(discover("judge"), key=key))
