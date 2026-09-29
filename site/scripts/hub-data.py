# SPDX-License-Identifier: AGPL-3.0-or-later
"""Collect what the website shows from the hub and the active pack.

Writes app/data/hub.json (engines and judges from their manifests, the
pack's questions and results) and exports the read-only run panel for
the pack to public/panel/<pack>/. Both are generated, never committed:
run this before `npm run generate` (CI does).

    CONJECTURE_PACK=/path/to/pack.yaml python site/scripts/hub-data.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
HUB = SITE.parent
sys.path.insert(0, str(HUB))
sys.path.insert(0, str(HUB / "panel"))

import build_data  # noqa: E402
from pack import PACK  # noqa: E402


def plain(text: str | None) -> str | None:
    """The brand's copy rule: no long dashes. Pack and manifest text may
    carry them; the site shows them as commas."""
    if text is None:
        return None
    for dash in (" \u2014 ", " \u2013 ", "\u2014", "\u2013"):
        text = text.replace(dash, ", " if dash.startswith(" ") else ", ")
    return text


def adapter(a: dict) -> dict:
    keys = a["requires"].get("env") or a["requires"].get("env_any") or []
    return {"id": a["id"], "name": plain(a["name"]),
            "summary": plain(a["summary"]),
            "built": a["built"], "state": a["state"], "ran": a["ran"],
            "access": a["access"], "invocation": a["invocation"],
            "licence": ("hub (AGPL-3.0-or-later)"
                        if a["licence"].startswith("n/a") else a["licence"]),
            "gated": a["gated"],
            "conformance": a["conformance"], "blocker": plain(a["blocker"]),
            "keys": keys}


def main() -> None:
    pj = build_data.pack_json(local=False)
    d = build_data.data_json()
    engines = [adapter(e) for e in pj["engines"]]
    judges = [adapter(j) for j in pj["judges"]]
    out = {
        "engines": engines,
        "judges": judges,
        "pack": {
            "name": PACK.name, "title": plain(PACK.title),
            "n_works": PACK.n_works,
            "questions": [[q, plain(t)] for q, t in pj["questions"]],
            "hypotheses": sum(d["hypotheses"].values()),
            "engines_run": sorted(d["hypotheses"]),
            "candidates": d["n_candidates"], "certified": d["certified"],
            "novel": d["novel"], "conflicts": d["conflicts"],
            "selfpref": {k: round(v["delta"] * 100)
                         for k, v in d["selfpref"].items()},
        },
    }
    data = SITE / "app" / "data" / "hub.json"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"  {data.relative_to(HUB)}: {len(engines)} engines, "
          f"{len(judges)} judges, pack {PACK.name}")
    subprocess.run([sys.executable, str(HUB / "panel" / "export.py"),
                    "--out", str(SITE / "public" / "panel" / PACK.name),
                    "--font-base", "/fonts/"], check=True)


if __name__ == "__main__":
    main()
