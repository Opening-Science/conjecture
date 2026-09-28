"""Route our hypotheses' checkable claims through theoria itself.

Everywhere else in this repo, "theoria-style" means we implemented its
discipline. Here we actually run it: the upstream pipeline (solver →
interpreter → formalizer → per-step judges → pedantry filter → convention
lift) over claims extracted from our candidates, and its own certify-or-
decline verdict comes back as a third verifier.

What theoria is good at is not what our judges are good at, which is the
point of adding it. Our judges audit whether a cited paper supports the
step that cites it — a question about this corpus. theoria audits whether
a chain of reasoning is *valid*: it re-derives arithmetic from scratch,
web-searches cited results to check they exist and are applied correctly,
and rejects any step resting on an unstated premise. That is precisely
the failure class our own run turned up on the physics side (three
hypotheses predicting 300-349 nm emission from carbonyls whose energies
cannot reach it).

So we extract the *computational* content of a hypothesis — the steps
its own author marked as computation, plus the estimand — and pose each
as a self-contained proposition. theoria never sees the hypothesis's
citations or its provenance; it sees a claim and is asked whether it
holds.

    python theoria_adapter.py --prepare              # extract claims
    python theoria_adapter.py --run --only C001,C003 # verify named claims
    python theoria_adapter.py --run --all            # sweep the whole queue
    python theoria_adapter.py --collect              # -> verdicts.theoria.json

Each claim is a full solve-and-audit — roughly half an hour of gpt-5.5 at
xhigh effort — so --run refuses to start without an explicit statement of
scope: either the claims named with --only, or --all said out loud.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
sys.path.insert(0, str(HUB))
from pack import PACK  # noqa: E402

VENDOR = HUB / "vendor" / "theoria"
CONFIG = HUB / "theoria_codex.yaml"
CLAIMS = PACK.judge_dir / "theoria_claims.json"
OUT = PACK.judge_dir / "verdicts.theoria.json"
PY = sys.executable
NUM = re.compile(r"\d")


def extract_claims() -> list[dict]:
    """One self-contained proposition per candidate that has arithmetic.

    A hypothesis with no computation step has nothing for theoria to
    verify — it is an empirical proposal, not a derivation — and is
    skipped rather than fed in and trivially passed.
    """
    cands = json.loads((PACK.judge_dir / "mechanical.json").read_text(encoding="utf-8"))
    claims = []
    for c in cands:
        h = c["hypothesis"]
        comp = [s for s in (h.get("rationale") or [])
                if s.get("justification_type") == "computation"
                and NUM.search(s.get("step", ""))]
        if not comp:
            continue
        scope = h.get("scope") or {}
        body = "\n".join(f"  {i + 1}. {s['step']}" for i, s in enumerate(comp))
        problem = (
            "The following quantitative reasoning is taken from a proposed "
            f"{PACK.verifier_setting}.\n\n"
            f"Setting: {scope.get('population', '')}. "
            f"{scope.get('condition', '')}\n\n"
            f"Reasoning steps as stated by the author:\n{body}\n\n"
            f"Quantity the experiment would measure: {h.get('estimand', '')}\n\n"
            "Determine whether this quantitative reasoning is correct: "
            "recompute every number from scratch, check that any physical "
            "constant, threshold or relationship invoked is real and "
            "correctly applied, and identify any step that depends on a "
            "premise which is not stated. Answer CORRECT if the arithmetic "
            "and the physics both hold as stated, or INCORRECT together "
            "with the specific error. End your response with a final line "
            "in exactly this form: VERDICT: CORRECT or VERDICT: INCORRECT "
            "or VERDICT: INCONCLUSIVE (if it cannot be determined).")
        claims.append({
            "candidate_id": c["candidate_id"],
            "seed_id": c["seed_id"],
            "n_computation_steps": len(comp),
            "problem": problem,
        })
    return claims


# theoria answers in free text. A substring test is not safe here:
# "NOT CORRECT" contains CORRECT, "not incorrect" contains INCORRECT, and
# "CORRECTNESS is uncertain" contains CORRECT — each would be misread. We
# match on word boundaries, treat a negated verdict as its opposite, and
# call anything ambiguous (both present, or a hedge) INCONCLUSIVE rather
# than guess. A trailing "ANSWER = X" / "VERDICT: X" line, which the prompt
# now asks for, is authoritative when present.
_NEG = re.compile(r"\b(not|isn'?t|is not|non-?)\s+(in)?correct\b", re.I)
_FINAL = re.compile(r"(?:ANSWER\s*=|VERDICT\s*:?)\s*\**\s*(CORRECT|INCORRECT|INCONCLUSIVE)\b", re.I)
_CORRECT = re.compile(r"\bCORRECT\b", re.I)
_INCORRECT = re.compile(r"\bINCORRECT\b", re.I)


def classify_answer(answer: str, verified: bool) -> str:
    """Map theoria's proof-verified flag + free-text answer to our verdict.

    `verified` is theoria's audit of its OWN proof, not a ruling on the
    hypothesis. Only a verified proof yields a ruling; the direction of the
    ruling is the answer. verified must be exactly True — a schema-drifted
    string "false" is not truthiness we accept.
    """
    if verified is not True:
        return "inconclusive"
    a = (answer or "").strip()
    if not a:
        return "inconclusive"
    # authoritative final line wins
    finals = _FINAL.findall(a)
    if finals:
        last = finals[-1].upper()
        return {"CORRECT": "certified", "INCORRECT": "declined",
                "INCONCLUSIVE": "inconclusive"}[last]
    neg = bool(_NEG.search(a))
    has_inc = bool(_INCORRECT.search(a))
    # "not incorrect" -> a correctness claim; "not correct" -> incorrectness
    if neg:
        m = _NEG.search(a)
        return "certified" if m.group(2) else "declined"
    has_cor = bool(_CORRECT.search(a)) and not has_inc  # INCORRECT contains CORRECT
    if has_inc and has_cor:
        return "inconclusive"          # both asserted, unresolved
    if has_inc:
        return "declined"
    if has_cor:
        return "certified"
    return "inconclusive"


def run_claim(claim: dict, timeout: int = 3600) -> dict:
    tag = f"hyp_{claim['candidate_id']}"
    proc = subprocess.run(
        [PY, "cli.py", "custom", claim["problem"], "--id",
         claim["candidate_id"], "--no-docker", "--no-watch",
         "--config", str(CONFIG), "--tag", tag],
        cwd=VENDOR, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout
    m = re.search(r"saved to (runs/\S+\.json)", out)
    verdict, answer, verified, run_path = "error", "", None, None
    if m:
        run_path = VENDOR / m.group(1)
        try:
            data = json.loads(run_path.read_text(encoding="utf-8"))
            rec = data[0] if isinstance(data, list) else data
            # `verified` is theoria's statement about ITS OWN proof, not
            # about our hypothesis. The hypothesis verdict lives in
            # `answer`. Conflating the two inverts the result: a run that
            # soundly proves "INCORRECT" is a DECLINE of the hypothesis,
            # even though theoria's own audit passed.
            verified = rec.get("verified") is True
            answer = str(rec.get("answer", ""))[:400]
            verdict = classify_answer(answer, verified)
        except Exception as exc:                      # noqa: BLE001
            verdict, answer = "error", f"unparseable run json: {exc}"
    reason = (f"theoria: proof {'verified' if verified else 'not verified'}"
              f", answer {answer[:150] or 'n/a'} "
              f"({claim['n_computation_steps']} computation steps)")
    return {"candidate_id": claim["candidate_id"], "judge": "theoria",
            "verdict": verdict, "theoria_answer": answer,
            "theoria_proof_verified": verified,
            "run_json": str(run_path) if run_path else None,
            "reason": reason}



def recollect() -> None:
    """Rebuild verdicts.theoria.json from the latest saved run per candidate.

    The run JSONs hold theoria's actual answer and proof-verified flag; the
    verdict is a pure function of those. So a fix to classify_answer can be
    applied to work already done, rather than paying for the run again.
    """
    claims = {c["candidate_id"]: c
              for c in json.loads(CLAIMS.read_text(encoding="utf-8"))}
    runs = sorted((VENDOR / "runs").glob("custom_hyp_*.json"))
    latest: dict[str, Path] = {}
    for r in runs:
        # custom_hyp_<CID>_<timestamp>.json ; keep the newest per CID
        cid = r.stem.split("_")[2]
        latest[cid] = r                                  # sorted asc -> last wins
    out = []
    for cid, path in latest.items():
        if cid not in claims:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rec = data[0] if isinstance(data, list) else data
        except Exception:                                 # noqa: BLE001
            continue
        verified = rec.get("verified") is True
        answer = str(rec.get("answer", ""))[:400]
        verdict = classify_answer(answer, verified)
        out.append({
            "candidate_id": cid, "judge": "theoria", "verdict": verdict,
            "theoria_answer": answer, "theoria_proof_verified": verified,
            "run_json": str(path),
            "reason": f"theoria: proof {'verified' if verified else 'not verified'}"
                      f", answer {answer[:150] or 'n/a'} "
                      f"({claims[cid].get('n_computation_steps', '?')} "
                      f"computation steps)"})
    out.sort(key=lambda v: v["candidate_id"])
    _atomic_write(OUT, out)
    tally: dict[str, int] = {}
    for v in out:
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    print(f"  re-derived {len(out)} verdicts from saved runs -> {OUT.name}  {tally}")


def _atomic_write(path: Path, obj) -> None:
    """Write via a temp file + os.replace so an interrupt cannot leave a
    truncated JSON that crashes the next load."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--recollect", action="store_true",
                    help="re-derive verdicts from saved run JSONs "
                         "(applies the current classifier without re-running)")
    ap.add_argument("--only",
                    help="comma-separated candidate ids to verify; --run "
                         "refuses to start without this or --all")
    ap.add_argument("--all", action="store_true",
                    help="explicitly sweep every claim still in the queue")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()

    if a.recollect:
        recollect()
        return

    if a.prepare or not CLAIMS.exists():
        claims = extract_claims()
        CLAIMS.write_text(json.dumps(claims, indent=1, ensure_ascii=False),
                          encoding="utf-8")
        print(f"  {len(claims)} candidates carry checkable arithmetic "
              f"-> {CLAIMS.name}")
        if not a.run:
            return

    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    done = {}
    if OUT.exists():
        done = {v["candidate_id"]: v
                for v in json.loads(OUT.read_text(encoding="utf-8"))}
    _TERMINAL = {"certified", "declined", "inconclusive"}
    todo = [c for c in claims
            if done.get(c["candidate_id"], {}).get("verdict") not in _TERMINAL]
    if a.only:
        ids = [s.strip() for s in a.only.split(",") if s.strip()]
        bad = sorted(set(ids) - {c["candidate_id"] for c in claims})
        if bad:
            sys.exit(f"unknown claim id(s): {', '.join(bad)} — "
                     f"the queue is {CLAIMS.name}")
        open_ids = {c["candidate_id"] for c in todo}
        for i in ids:
            if i not in open_ids:
                print(f"  {i} is already {done[i]['verdict']} — skipped "
                      f"(delete its entry in {OUT.name} to re-verify)")
        todo = [c for c in todo if c["candidate_id"] in set(ids)]
    elif a.run and not a.all:
        sys.exit("each claim is ~30 min of gpt-5.5 solve-and-audit; refusing "
                 "to sweep the whole queue implicitly. Name the claims with "
                 "--only C001,C003 or state --all.")
    if a.limit:
        todo = todo[:a.limit]

    if a.run:
        for i, c in enumerate(todo, 1):
            print(f"  [{i}/{len(todo)}] {c['candidate_id']} …", flush=True)
            try:
                v = run_claim(c, timeout=a.timeout)
            except subprocess.TimeoutExpired:
                v = {"candidate_id": c["candidate_id"], "judge": "theoria",
                     "verdict": "error", "reason": "timeout"}
            done[c["candidate_id"]] = v
            _atomic_write(OUT, list(done.values()))
            print(f"      {v['verdict']}: {v.get('reason', '')[:110]}")

    if a.collect or a.run:
        vs = list(done.values())
        tally: dict[str, int] = {}
        for v in vs:
            tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
        print(f"  {len(vs)} theoria verdicts -> {OUT.name}  {tally}")


if __name__ == "__main__":
    main()
