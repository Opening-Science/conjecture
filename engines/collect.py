"""Pull a HOF payload out of whatever a model actually returned.

Models wrap JSON in prose, fences, and occasionally commentary after the
closing brace. Rather than demanding obedience, we scan for the largest
parseable object that looks like HOF. Failures are recorded, not
silently dropped: an engine that cannot emit valid HOF is a finding
about that engine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def extract_json(text: str) -> dict | None:
    """Largest parseable JSON object containing an 'hypotheses' key."""
    # fenced blocks first, they are the common case
    candidates: list[str] = []
    for m in re.finditer(r"```(?:json)?\s*(.+?)```", text, re.S):
        candidates.append(m.group(1))
    candidates.append(text)

    best = None
    for blob in candidates:
        for start in (m.start() for m in re.finditer(r"\{", blob)):
            try:
                obj, _ = json.JSONDecoder().raw_decode(blob[start:])
            except ValueError:
                continue
            if isinstance(obj, dict) and "hypotheses" in obj:
                if best is None or len(json.dumps(obj)) > len(
                        json.dumps(best)):
                    best = obj
        if best is not None:
            return best
    return best


def normalise(payload: dict, engine: str, seed_id: str, backend: str,
              config_hash: str, **run_extra) -> dict:
    """Fill in run metadata the model may have mangled or omitted."""
    payload.setdefault("hof_version", "1.0")
    payload["hof_version"] = "1.0"
    run = payload.setdefault("run", {})
    run.update({"engine": engine, "seed_id": seed_id, "backend": backend,
                "config_hash": config_hash})
    run.update(run_extra)
    for i, h in enumerate(payload.get("hypotheses", [])):
        h.setdefault("id", f"{seed_id}-{i + 1}")
        # models sometimes emit a bare string where a list is required
        cw = h.get("cited_work_ids")
        if isinstance(cw, str):
            h["cited_work_ids"] = re.findall(r"W\d+", cw)
        elif cw is None:
            h["cited_work_ids"] = []
        # harvest ids mentioned in rationale steps but omitted up top
        for step in h.get("rationale") or []:
            for wid in step.get("work_ids") or []:
                if wid not in h["cited_work_ids"]:
                    h["cited_work_ids"].append(wid)
    return payload


def save(payload: dict, out_dir: Path, seed_id: str, engine: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{seed_id}.{engine}.json"
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    return path
