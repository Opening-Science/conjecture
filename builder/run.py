"""Build a pack's corpus: seed bibliography -> field map -> knowledgebase.

Runs the builder's stages in dependency order for the active pack
(pack.yaml, as for every hub script; see config.py for its build: block):

    A      seed_resolve.py        seeds -> OpenAlex work ids           network
    B      expand.py              citation expansion -> the universe   network, heavy
    C      build_db.py            universe -> fieldmap.sqlite          cache
    E      openness.py            abstracts + openness overlay         network, cached
    index  build_full_index.py    ranked paper index (+ core_topic)    local
    I      harvest_oa_pdfs.py     open-access PDFs -> literature/      network, hours
    J      extract_fulltext.py    text + mined statements              local, CPU
    K      build_knowledgebase.py the knowledgebase the hub serves     local
    refs   ingest_reference_works.py  curated works outside the field  local

Every stage is cached or resumable, so a rerun costs little and an
interrupted one continues. Clustering, contact data and a pack's claim
register are not the builder's: engines never read the first, a shared
tool must never collect the second, and the third is a pack's own
curation, which the knowledgebase stage carries over on rebuild.

    python builder/run.py                  # every stage
    python builder/run.py C index K        # just these, in this order
    python builder/run.py --from I         # I and everything after it
    python builder/run.py --list

OPENALEX_API_KEY and OPENALEX_MAILTO come from the environment. The
builder's dependencies, PyMuPDF (AGPL) and Unidecode (GPL-2.0+) among
them, are in requirements-builder.txt.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES = [
    ("A", "seed_resolve.py", "resolve the seed bibliography"),
    ("B", "expand.py", "expand by citation into the universe"),
    ("C", "build_db.py", "build the field map database"),
    ("E", "openness.py", "fetch abstracts, score openness"),
    ("index", "build_full_index.py", "rank and index every paper"),
    ("I", "harvest_oa_pdfs.py", "harvest open-access PDFs"),
    ("J", "extract_fulltext.py", "extract full text, mine statements"),
    ("K", "build_knowledgebase.py", "build the knowledgebase"),
    ("refs", "ingest_reference_works.py", "add the pack's curated works"),
]
NAMES = [s[0] for s in STAGES]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("stages", nargs="*", help=f"any of {', '.join(NAMES)}")
    ap.add_argument("--from", dest="start", choices=NAMES)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for name, script, what in STAGES:
            print(f"  {name:<6} {script:<27} {what}")
        return
    bad = [s for s in a.stages if s not in NAMES]
    if bad:
        ap.error(f"unknown stage(s) {bad}; known: {', '.join(NAMES)}")
    if a.stages:
        todo = [s for s in STAGES if s[0] in a.stages]
    elif a.start:
        todo = STAGES[NAMES.index(a.start):]
    else:
        todo = STAGES
    for name, script, what in todo:
        print(f"\n=== {name}: {what} ({script})", flush=True)
        r = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE)
        if r.returncode != 0:
            sys.exit(f"stage {name} failed with exit {r.returncode}; fix and "
                     f"rerun with --from {name}")


if __name__ == "__main__":
    main()
