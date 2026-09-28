"""Conformance: does an adapter keep the contract, on a corpus it cannot know?

Every built engine and judge is run against the toy pack (toy_pack/, a
fictional field of 50 works) and checked for the things the hub relies
on. It says nothing about whether an engine's hypotheses are good; that
is the scoreboard's job. It says whether the engine can be scored at all.

Engine checks (on each toy question):
  hof          produced a parseable HOF payload with at least one hypothesis
  schema       the payload validates against schema/hof.schema.json
  citations    every cited work_id exists in the toy corpus
  corpus_used  the hub logged the engine's own corpus calls (cli/mcp only)
  no_outside   no cited id outside the toy corpus, no web tool, curl or
               wget in the raw transcript
Judge checks (on toy_pack candidates, one deliberately miscited):
  parsed       returned a verdict array
  verdicts     it validates against schema/verdict.schema.json, one
               verdict per candidate
  miscitation  (information only) whether it declined the planted C2

    python conformance/conformance.py --offline      # adapters needing no model
    python conformance/conformance.py codex-solo codex-mcp --judge codex
    python conformance/conformance.py --status       # rewrite the STATUS table

Results land in conformance/results/<kind>.<name>.json with the commit
and the manifest and adapter hashes they were produced against; the
status table marks a result stale once either file changes. Handoff
adapters (Claude subagents) print their task on the first call and are
collected by running the same command again once the answer is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
TOY_SRC = HERE / "toy_pack"
WORK = HERE / "work"                   # built toy pack + its runs; ignored
RESULTS = HERE / "results"
STATUS = HUB / "connectors" / "STATUS.md"
PY = sys.executable
TOY_SEEDS = ("T1",)
OUTSIDE = re.compile(r"\bweb_search\b|\bcurl\s|\bwget\s|https?://(?!localhost)")

sys.path.insert(0, str(HUB))


# -- toy pack ----------------------------------------------------------

def build_toy() -> Path:
    """Fresh toy corpus in WORK; runs/ from earlier calls survive."""
    WORK.mkdir(exist_ok=True)
    for f in ("pack.yaml", "questions.md"):
        shutil.copy2(TOY_SRC / f, WORK / f)
    subprocess.run([PY, str(TOY_SRC / "build.py"), "--out", str(WORK)],
                   check=True)
    return WORK / "pack.yaml"


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]


def commit() -> str:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HUB,
                       capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "."],
                           cwd=HUB, capture_output=True, text=True).stdout
    # results/ and STATUS.md are outputs of this very run
    dirty = [x for x in dirty.splitlines()
             if "conformance/results/" not in x and "STATUS.md" not in x]
    return (r.stdout.strip() or "unknown") + ("+dirty" if dirty else "")


# -- worker: runs inside the toy pack (CONJECTURE_PACK set) ------------

def check(name: str, ok: bool | None, detail: str = "") -> dict:
    return {"check": name, "ok": ok, "detail": detail}


def engine_checks(m, seed_id: str) -> tuple[str, list[dict], dict]:
    import contract
    from hof import validate
    from pack import PACK
    try:
        r = contract.run_engine(m, seed_id, timeout=1500)
    except contract.Pending:
        raw = PACK.runs_dir / "raw" / f"{seed_id}.{m.name}.txt"
        return "pending", [], {"task_for": str(raw)}
    except subprocess.TimeoutExpired:
        return "fail", [check("hof", False, "timeout")], {}
    if not r["ok"]:
        return "fail", [check("hof", False, r["error"])], {}
    p = r["payload"]
    n = r["n"]
    schema = [x for x in validate(p) if x.startswith("schema[")]
    missing = [x for x in r["problems"] if "is not in the corpus" in x]
    cited = sorted({w for h in p["hypotheses"]
                    for w in h.get("cited_work_ids") or []})
    raw = Path(r["raw_path"]).read_text(encoding="utf-8") \
        if Path(r["raw_path"]).exists() else ""
    web = sorted(set(OUTSIDE.findall(raw)))
    calls = r["corpus_calls_observed"]
    checks = [
        check("hof", n > 0, f"{n} hypotheses"),
        check("schema", not schema, "; ".join(schema[:3])),
        check("citations", not missing,
              f"{len(cited)} distinct works cited"
              + (f"; {len(missing)} unresolved" if missing else "")),
        check("corpus_used",
              calls > 0 if m["corpus_access"] in ("cli", "mcp") else None,
              f"{calls} calls logged by the hub"
              if m["corpus_access"] in ("cli", "mcp")
              else "not observable for this access mode"),
        check("no_outside", not missing and not web,
              "raw transcript mentions " + ", ".join(web) if web else
              "only toy-corpus ids cited; no web tool, curl or wget"),
    ]
    other = [x for x in r["problems"]
             if not x.startswith("schema[") and x not in missing]
    info = {"elapsed_s": r["elapsed_s"], "n_hypotheses": n,
            "corpus_calls": calls, "hof_warnings": other[:10]}
    return "pass" if all(c["ok"] is not False for c in checks) else "fail", \
        checks, info


def judge_checks(m) -> tuple[str, list[dict], dict]:
    import contract
    from pack import PACK
    items = json.loads((PACK.state_dir / "candidates.json").read_text())
    try:
        r = contract.run_judge(m, items, label=f"conformance-{m.name}",
                               tag="toy", timeout=1500,
                               raw_dir=PACK.state_dir / "judge_raw")
    except contract.Pending:
        raw = PACK.state_dir / "judge_raw" / f"conformance-{m.name}.toy.txt"
        return "pending", [], {"task_for": str(raw)}
    except subprocess.TimeoutExpired:
        return "fail", [check("parsed", False, "timeout")], {}
    if not r["ok"]:
        return "fail", [check("parsed", False, r["error"])], {}
    v = {x.get("candidate_id"): x for x in r["verdicts"]}
    c2 = (v.get("C2") or {}).get("verdict")
    checks = [check("parsed", True, f"{len(r['verdicts'])} verdicts"),
              check("verdicts", not r["problems"],
                    "; ".join(r["problems"][:3])),
              check("miscitation", None,
                    f"planted miscitation C2 was {c2 or 'not judged'}")]
    info = {"elapsed_s": r["elapsed_s"],
            "verdicts": {k: x.get("verdict") for k, x in v.items()}}
    return "pass" if not r["problems"] else "fail", checks, info


def worker(kind: str, name: str, out: Path) -> None:
    import contract
    m = contract.get(kind, name)
    base = {"kind": kind, "name": name, "pack": "toy", "commit": commit(),
            "date": dt.date.today().isoformat(),
            "manifest_sha": digest(m.path),
            "adapter_sha": digest(m.adapter_path)}
    if not m.built:
        res = {**base, "status": "designed", "checks": [],
               "detail": m.get("blocker") or "no adapter.py"}
    elif m.missing():
        res = {**base, "status": "skipped", "checks": [],
               "detail": "needs " + ", ".join(m.missing())}
    else:
        try:
            contract.load_adapter(m)
        except Exception as e:  # an adapter that will not load fails
            res = {**base, "status": "fail",
                   "checks": [check("adapter", False, repr(e))]}
        else:
            if kind == "engine":
                statuses, checks, info = [], [], {}
                for s in TOY_SEEDS:
                    st, ch, inf = engine_checks(m, s)
                    statuses.append(st)
                    checks += [{**c, "seed": s} for c in ch]
                    info[s] = inf
                status = ("pending" if "pending" in statuses else
                          "fail" if "fail" in statuses else "pass")
            else:
                status, checks, info = judge_checks(m)
            res = {**base, "status": status, "checks": checks,
                   "info": info}
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")


# -- parent ------------------------------------------------------------

def run(kind: str, name: str, pack_yaml: Path) -> dict:
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{kind}.{name}.json"
    tmp = WORK / f"result.{kind}.{name}.json"
    env = {**os.environ, "CONJECTURE_PACK": str(pack_yaml)}
    env.pop("CONJECTURE_CALL_LOG", None)
    p = subprocess.run([PY, str(Path(__file__)), "--worker", kind, name,
                        "--out", str(tmp)], env=env, cwd=HUB)
    if p.returncode != 0 or not tmp.exists():
        res = {"kind": kind, "name": name, "status": "fail",
               "checks": [check("worker", False,
                                f"exit {p.returncode}")]}
    else:
        res = json.loads(tmp.read_text(encoding="utf-8"))
        tmp.unlink()
    if res["status"] != "pending":     # a pending run keeps the last result
        out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res


def report(res: dict) -> None:
    print(f"{res['kind']:<6} {res['name']:<18} {res['status'].upper()}"
          + (f"  ({res['detail']})" if res.get("detail") else ""))
    for c in res.get("checks", []):
        mark = {True: "ok  ", False: "FAIL", None: "info"}[c["ok"]]
        seed = f"[{c['seed']}] " if c.get("seed") else ""
        print(f"    {mark} {seed}{c['check']:<12} {c['detail']}")
    if res["status"] == "pending":
        for v in (res.get("info") or {}).values():
            if isinstance(v, dict) and v.get("task_for"):
                print(f"    pending: write the answer to {v['task_for']}")
        if res.get("info", {}).get("task_for"):
            print(f"    pending: write the answer to "
                  f"{res['info']['task_for']}")


# -- status table ------------------------------------------------------

BEGIN = "<!-- BEGIN GENERATED: conformance/conformance.py --status -->"
END = "<!-- END GENERATED -->"


def has_run(m) -> str:
    from pack import PACK
    if m.kind == "engine":
        n = files = 0
        for f in PACK.runs_dir.glob(f"*.{m.name}.json"):
            files += 1
            n += len(json.loads(f.read_text()).get("hypotheses", []))
        return f"**yes**, {n} hypotheses on {files} questions" if files \
            else "no"
    n = 0
    for label in m.get("labels") or [m.name]:
        f = PACK.judge_dir / f"verdicts.{label}.json"
        if f.exists():
            data = json.loads(f.read_text())
            n += len(data if isinstance(data, list)
                     else data.get("verdicts", []))
    return f"**yes**, {n} verdict{'s' if n != 1 else ''}" if n else "no"


def conformance_cell(m) -> str:
    f = RESULTS / f"{m.kind}.{m.name}.json"
    if not m.built:
        return "designed, no adapter"
    if not f.exists():
        return "not yet run"
    r = json.loads(f.read_text())
    stale = (r.get("manifest_sha") != digest(m.path)
             or r.get("adapter_sha") != digest(m.adapter_path))
    word = {"pass": "**pass**", "fail": "**FAIL**",
            "skipped": "skipped"}.get(r["status"], r["status"])
    extra = f" ({r['detail']})" if r.get("detail") else ""
    return (f"{word}{extra}, {r.get('date', '?')} @ {r.get('commit', '?')}"
            + (" (stale: adapter changed since)" if stale else ""))


def status_table() -> str:
    import contract
    from pack import PACK
    reg = contract.Registry.load()
    ran = f"Has run on pack `{PACK.name}`"

    def up(m) -> str:
        u = m["upstream"]
        if not u["repo"]:
            return u.get("homepage") or "native"
        repo = u["repo"].removeprefix("https://github.com/") \
            .removesuffix(".git")
        return f"{repo} @ {u['commit'][:7]}" if u["commit"] else repo

    def block(m) -> str:
        b = m.get("blocker") or ""
        miss = m.missing() if m.built else []
        if miss:
            b = (b + "; " if b else "") + "needs " + ", ".join(miss)
        return b or "-"

    def access(m) -> str:
        a = m["corpus_access"]
        return f"connector `{m['connector'].split('.')[-1]}`" \
            if a == "connector" else a

    lines = ["| Engine | Access | Invocation | Upstream | Licence | "
             f"Conformance (toy pack) | {ran} | Blocker |",
             "|---|---|---|---|---|---|---|---|"]
    for m in reg.engines:
        lines.append(
            f"| {m['title']} (`{m.name}`) | {access(m)} | "
            f"{m['invocation']} | {up(m)} | {m['upstream']['licence']} | "
            f"{conformance_cell(m)} | {has_run(m)} | {block(m)} |")
    lines += ["", "| Judge | Invocation | Upstream | Licence | "
              f"Conformance (toy pack) | {ran} | Blocker |",
              "|---|---|---|---|---|---|---|"]
    for m in reg.judges:
        lines.append(
            f"| {m['title']} (`{m.name}`) | {m['invocation']} | {up(m)} | "
            f"{m['upstream']['licence']} | {conformance_cell(m)} | "
            f"{has_run(m)} | {block(m)} |")
    return "\n".join(lines)


def write_status() -> None:
    text = STATUS.read_text(encoding="utf-8")
    table = f"{BEGIN}\n{status_table()}\n{END}"
    if BEGIN in text:
        pre, rest = text.split(BEGIN, 1)
        text = pre + table + rest.split(END, 1)[1]
    else:
        raise SystemExit(f"{STATUS}: no {BEGIN!r} marker")
    STATUS.write_text(text, encoding="utf-8")
    print(f"wrote {STATUS.relative_to(HUB)}")


def main() -> None:
    global WORK, RESULTS
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("engines", nargs="*")
    ap.add_argument("--judge", action="append", default=[])
    ap.add_argument("--offline", action="store_true",
                    help="every built adapter that needs no model")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--work", type=Path, default=WORK,
                    help="where the toy pack is built (default: work/)")
    ap.add_argument("--results", type=Path, default=RESULTS,
                    help="where results are written (default: results/)")
    ap.add_argument("--worker", nargs=2, metavar=("KIND", "NAME"),
                    help=argparse.SUPPRESS)
    ap.add_argument("--out", type=Path, help=argparse.SUPPRESS)
    a = ap.parse_args()
    WORK, RESULTS = a.work, a.results
    if a.worker:
        worker(*a.worker, a.out)
        return
    if a.status and not (a.engines or a.judge or a.offline):
        write_status()
        return

    import contract
    todo = [("engine", e) for e in a.engines] + \
        [("judge", j) for j in a.judge]
    if a.offline:
        todo += [(m.kind, m.name) for m in contract.discover()
                 if m.built and m["cost"]["billing"] == "free"]
    todo = list(dict.fromkeys(todo))
    if not todo:
        ap.error("name adapters, or pass --offline or --status")
    pack_yaml = build_toy()
    results = [run(k, n, pack_yaml) for k, n in todo]
    for r in results:
        report(r)
    if a.status:
        write_status()
    sys.exit(1 if any(r["status"] == "fail" for r in results) else 0)


if __name__ == "__main__":
    main()
