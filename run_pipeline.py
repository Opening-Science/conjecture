"""Run the stages that need no human in the loop.

Generation and judging need model inference, which arrives either from a
self-driving CLI (Codex) or from agents dispatched in a Claude Code
session. Everything between and after those steps is deterministic and
runs here, so a full pipeline is:

    python build_seeds.py                       # seeds from the questions
    python run_engine.py codex-solo --all       # self-driving generation
    python run_engine.py baseline-claude        # handoff: tasks for agents
    python run_pipeline.py                      # merge -> mechanical -> batch
    python run_judge.py codex                   # judges over judge/chunks/
    python judge/collect_verdicts.py
    python run_pipeline.py --score              # verdicts -> audit.db -> page

Stages are separate on purpose: each one leaves an inspectable artifact,
so a bad run can be diagnosed at the stage that produced it rather than
re-run from the top.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(script: str, *args: str) -> None:
    path = HERE / script
    print(f"\n=== {script} {' '.join(args)}")
    r = subprocess.run([PY, str(path), *args], cwd=path.parent)
    if r.returncode != 0:
        sys.exit(f"{script} failed with {r.returncode}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true",
                    help="post-judging: score verdicts and build the page")
    a = ap.parse_args()
    if a.score:
        run("scoreboard/score.py")
        run("scoreboard/build_page.py")
    else:
        run("merge/merge.py", "--prepare")
        run("judge/certify.py", "--prepare")
        print("\nNext: run judges over judge/chunks/ (python run_judge.py "
              "codex; run_judge.py claude-subagent --as claude-a prints "
              "agent tasks), then python judge/collect_verdicts.py and "
              "python run_pipeline.py --score")


if __name__ == "__main__":
    main()
