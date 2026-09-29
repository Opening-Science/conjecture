"""Write a read-only, static copy of the run panel for the active pack.

The local panel (server.py) can start runs; this copy cannot, by
construction: it is plain files, so any static host (GitHub Pages, a
bucket, python -m http.server) can serve it and nothing on it executes
anything. What it shows is the pack's data at export time: questions,
engines and judges with their status, results, the ledger, and the
pack's findings. The Run page still builds the command list; its trigger
says it is a read-only copy.

Never exported: the licensed fonts (panel/fonts/), keys, logs, and any
local path (command hints use placeholders).

    python panel/export.py --out /tmp/panel-site
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PANEL = Path(__file__).resolve().parent
sys.path.insert(0, str(PANEL.parent))
sys.path.insert(0, str(PANEL))

import build_data  # noqa: E402
from pack import PACK  # noqa: E402

STATIC = ("index.html", "app.js", "style.css")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--font-base", default=None,
                    help="where the site serves the licensed fonts, e.g. "
                         "/fonts/ (default: fonts/ next to the page)")
    a = ap.parse_args()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    for f in STATIC:
        shutil.copy2(PANEL / f, out / f)
    if a.font_base:       # served from the host site's own font directory
        css = out / "style.css"
        css.write_text(css.read_text(encoding="utf-8").replace(
            'url("fonts/', f'url("{a.font_base}'), encoding="utf-8")
    shutil.copytree(PANEL / "img", out / "img", dirs_exist_ok=True)

    pj = build_data.pack_json(local=False)
    pj["static"] = True
    # the pack's findings travel inside pack.json: a loose HTML fragment
    # would be served, and checked, as if it were a page of its own
    findings = PACK.outputs_dir / "panel" / "findings.html"
    if findings.is_file():
        pj["findings_html"] = findings.read_text(encoding="utf-8")
    (out / "pack.json").write_text(json.dumps(pj, indent=1,
                                              ensure_ascii=False) + "\n")
    try:
        data = build_data.data_json()
    except Exception as e:  # a pack that has not run yet: the page says so
        print(f"  no results to export yet ({e})")
    else:
        (out / "data.json").write_text(json.dumps(data, indent=1,
                                                  ensure_ascii=False) + "\n")
    if PACK.ledger.is_file():
        shutil.copy2(PACK.ledger, out / "ledger.json")
    (out / "findings.html").unlink(missing_ok=True)   # from older exports

    leaked = [p.name for p in out.rglob("*") if p.is_file()
              and str(Path.home()) in p.read_text(errors="ignore")]
    if leaked:
        sys.exit(f"refusing: a local path is in {leaked}")
    print(f"  static panel for pack '{PACK.name}' -> {out}")


if __name__ == "__main__":
    main()
