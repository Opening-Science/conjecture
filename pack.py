"""The domain pack the hub is hydrated with.

The hub is field-agnostic: engines, judges, merge and scoreboard work on
any literature corpus. Everything that ties a run to one field (where its
corpus lives, its open questions and their entry queries, the domain
framing in prompts, the measurement areas experiment cards map to) comes
from one pack.yaml.

Which pack: $CONJECTURE_PACK if set (path to a pack.yaml), otherwise the
nearest pack.yaml found walking up from this directory.

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


def load(path: Path | None = None) -> Pack:
    path = path or locate()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
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
