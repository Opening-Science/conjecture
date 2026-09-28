"""The domain pack the hub is hydrated with.

The hub is field-agnostic: engines, judges, merge and scoreboard work on
any literature corpus. Everything that ties a run to one field (where its
corpus lives, its open questions and their entry queries, the domain
framing in prompts, the measurement areas experiment cards map to) comes
from one pack.yaml.

Which pack: $CONJECTURE_PACK if set (path to a pack.yaml), otherwise the
nearest pack.yaml found walking up from this directory. A pack.yaml can
extend another and override parts of it (see read_raw).

    from pack import PACK
    PACK.knowledgebase          # Path
    PACK.entry_queries["Q1"]    # list[str]
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parent
SUPPORTED_VERSION = 1


def locate() -> Path:
    env = os.environ.get("CONJECTURE_PACK")
    if env:
        p = Path(env).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"CONJECTURE_PACK={env} is not a file")
        return p
    for d in (HUB, *HUB.parents):
        if (d / "pack.yaml").is_file():
            return d / "pack.yaml"
    raise FileNotFoundError(
        "no pack.yaml above the hub; set CONJECTURE_PACK")


@dataclass(frozen=True)
class Pack:
    path: Path
    name: str
    title: str
    knowledgebase: Path
    fieldmap: Path | None
    n_works: int
    questions_source: Path
    entry_queries: dict[str, list[str]]
    domain: str
    causal_levels: str
    causal_level_labels: dict[str, str]
    verifier_setting: str
    measurement_areas: list[tuple[str, str]]
    outputs_dir: Path
    inventory: Path | None
    # where build_ledger writes the per-candidate ledger for a run panel
    ledger: Path
    # where this pack's run state lives: everything a run writes, so the
    # hub directory holds code only
    state_dir: Path

    @property
    def seeds_dir(self) -> Path:
        return self.state_dir / "seeds"

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def merge_dir(self) -> Path:
        return self.state_dir / "merge"

    @property
    def judge_dir(self) -> Path:
        return self.state_dir / "judge"

    @property
    def bench_dir(self) -> Path:
        return self.state_dir / "verifier_bench"

    @property
    def audit_db(self) -> Path:
        return self.state_dir / "audit.db"

    @property
    def scoreboard(self) -> Path:
        return self.state_dir / "scoreboard.json"


# fields holding paths: resolved against the file that sets them, so an
# overlay's paths are relative to the overlay and a base's to the base
PATH_FIELDS = [("corpus", "knowledgebase"), ("corpus", "fieldmap"),
               ("questions", "source"), ("outputs", "dir"),
               ("outputs", "inventory"), ("outputs", "ledger"), ("state",),
               # the corpus builder's (builder/config.py)
               ("build", "seeds"),
               *(("build", "paths", k) for k in
                 ("workdir", "cache", "exports", "literature", "index",
                  "run_log"))]


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = (_merge(base[k], v) if isinstance(v, dict)
                  and isinstance(base.get(k), dict) else v)
    return out


def read_raw(path: Path, _seen: tuple = ()) -> dict:
    """A pack file as a dict, path fields absolute, overlays applied.

    A pack file may start with `extends: <path to another pack.yaml>` and
    set only what differs; dicts merge key by key, anything else
    replaces. The use: a maintainer's workspace points a published pack
    at a local corpus (full text the release cannot carry) while runs,
    questions and outputs stay in the pack.
    """
    path = path.resolve()
    if path in _seen:
        raise ValueError(f"{path}: extends loop")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for keys in PATH_FIELDS:
        node = raw
        for k in keys[:-1]:
            node = node.get(k) if isinstance(node, dict) else None
        if isinstance(node, dict) and node.get(keys[-1]):
            node[keys[-1]] = str((path.parent / node[keys[-1]]).resolve())
    parent = raw.pop("extends", None)
    if parent:
        raw = _merge(read_raw(path.parent / parent, _seen + (path,)), raw)
    return raw


def load(path: Path | None = None) -> Pack:
    path = (path or locate()).resolve()
    raw = read_raw(path)
    if raw.get("pack_version") != SUPPORTED_VERSION:
        raise ValueError(f"{path}: pack_version {raw.get('pack_version')!r}"
                         f", hub supports {SUPPORTED_VERSION}")
    base = path.parent

    def rel(p: str | None) -> Path | None:
        return (base / p).resolve() if p else None

    corpus, q = raw["corpus"], raw["questions"]
    prompts, out = raw["prompts"], raw["outputs"]
    return Pack(
        path=path,
        name=raw["name"],
        title=raw["title"],
        knowledgebase=rel(corpus["knowledgebase"]),
        fieldmap=rel(corpus.get("fieldmap")),
        n_works=int(corpus["n_works"]),
        questions_source=rel(q["source"]),
        entry_queries={k: list(v) for k, v in
                       (q.get("entry_queries") or {}).items()},
        domain=prompts["domain"],
        causal_levels=prompts["causal_levels"],
        causal_level_labels=dict(prompts.get("causal_level_labels") or {}),
        verifier_setting=prompts["verifier_setting"],
        measurement_areas=[(a["pattern"], a["area"])
                           for a in raw.get("measurement_areas") or []],
        outputs_dir=rel(out["dir"]),
        inventory=rel(out.get("inventory")),
        ledger=rel(out.get("ledger")) or rel(out["dir"]) / "ledger.json",
        state_dir=rel(raw["state"]),
    )


PACK = load()
