"""Turn the field's seven open questions into structured seed briefs.

A seed is what every engine receives instead of a bare prompt: the
question in the field's own words, the verbatim evidence sentences the
field used to state it (with provenance), the registry claims already at
stake, and the corpus entry points. Engines differ in what they do with
a seed; they must not differ in what they were given.

The registry claims are included as CONTEXT, never as answers: an engine
is told which claims exist so it does not merely restate them, and the
scoring side keeps the verified evidence hidden so rediscovery can be
measured blind.

    python build_seeds.py          # writes seeds/Q1.json .. Q7.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pack import PACK  # noqa: E402

KB = PACK.knowledgebase
QUESTIONS_MD = PACK.questions_source
SEEDS = PACK.seeds_dir
# corpus entry-point queries per question (pack.yaml), so every engine
# starts from the same retrieval surface rather than inventing its own
ENTRY_QUERIES = PACK.entry_queries

def parse_questions(md: str) -> list[dict]:
    """Split the questions document into per-question briefs."""
    blocks = re.split(r"\n## (Q\d)\. ", md)
    out = []
    for i in range(1, len(blocks), 2):
        qid, body = blocks[i], blocks[i + 1]
        title = body.split("\n", 1)[0].strip()
        # verbatim evidence bullets carry the provenance the field itself
        # used to state the question
        quotes = []
        # bullets wrap across lines and use several dash conventions; take
        # the quoted span, then whatever attribution follows it
        for m in re.finditer(r'-\s+"(.+?)"(.*?)(?=\n-\s|\n\n|\Z)',
                             body, re.S):
            attrib = re.sub(r"^\s*[—–-]\s*", "", m.group(2).strip())
            quotes.append({"quote": " ".join(m.group(1).split())[:400],
                           "source": " ".join(attrib.split())[:120]})
        # the closing directive is phrased differently per question
        # ("What would settle it", "Why this is tractable now", ...)
        settle = ""
        ms = re.search(
            r"\*\*(?:What would settle it|What would close it|"
            r"Why this is tractable now)[:\*]*\*\*(.+?)(?=\n##|\n\*\*|$)",
            body, re.S)
        if ms:
            settle = " ".join(ms.group(1).split())
        claims = []
        mc = re.search(r"\*Competing claims → (.+?)\*", body, re.S)
        if mc:
            claims = re.findall(r"H\d+[a-z]?(?:\.\w+)?", mc.group(1))
        out.append({"seed_id": qid, "title": title, "quotes": quotes[:8],
                    "what_would_settle_it": settle,
                    "claims_mentioned": sorted(set(claims))})
    return out


def registry_context(kb: sqlite3.Connection, claim_ids: list[str]) -> list[dict]:
    """The scoped claims already on the register, as context not answers."""
    rows = kb.execute(
        "SELECT id, level, claim, null, estimand FROM hypotheses_v2").fetchall()
    out = []
    for rid, level, claim, null, estimand in rows:
        base = rid.split(".")[0]
        if claim_ids and rid not in claim_ids and base not in claim_ids:
            continue
        out.append({"id": rid, "level": level, "claim": claim,
                    "null": null, "estimand": estimand})
    return out


def main() -> None:
    sys.path.insert(0, str(HERE))
    from corpus_api import Corpus

    kb = sqlite3.connect(f"file:{KB}?mode=ro", uri=True)
    corpus = Corpus()
    SEEDS.mkdir(exist_ok=True)
    md = QUESTIONS_MD.read_text(encoding="utf-8")
    briefs = parse_questions(md)
    if len(briefs) != 7:
        print(f"WARNING: parsed {len(briefs)} questions, expected 7")

    all_claims = registry_context(kb, [])
    for b in briefs:
        qid = b["seed_id"]
        queries = ENTRY_QUERIES.get(qid, [b["title"]])
        entry = corpus.search_many(queries, limit=8)
        b["entry_queries"] = queries
        b["entry_points"] = [w.brief() for w in entry[:20]]
        b["registry_claims_at_stake"] = registry_context(
            kb, b["claims_mentioned"])
        b["registry_all_claim_statements"] = [
            {"id": c["id"], "level": c["level"], "claim": c["claim"]}
            for c in all_claims]
        b["instructions_to_engine"] = (
            "Propose falsifiable hypotheses that ADVANCE this question. A "
            "hypothesis that merely restates a registry claim scores zero "
            "for novelty; a hypothesis that cannot be measured with a "
            "named instrument scores zero for usefulness. Ground every "
            "claim in works retrieved through the corpus API, cite them by "
            "work_id, and state the measurement that would settle it.")
        path = SEEDS / f"{qid}.json"
        path.write_text(json.dumps(b, indent=1, ensure_ascii=False),
                        encoding="utf-8")
        print(f"  {qid}: {len(b['quotes'])} field quotes, "
              f"{len(b['entry_points'])} entry works, "
              f"{len(b['registry_claims_at_stake'])} claims at stake "
              f"-> {path.name}")


if __name__ == "__main__":
    main()
