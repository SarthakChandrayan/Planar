"""Export recorded runs of the sample meetings for the website demo.

For every meeting with an answer key (tests/evaluation/keys), takes the latest
successful run from data/runs whose title matches, and writes:

    site/demo/runs.json            list shown on the demo home page
    site/demo/runs/<id>.json       the full run the demo UI opens
    site/demo/reports/<id>.md      the Markdown export (Copy / Download)
    site/demo/accuracy.json        each exported run scored against its key

Only keyed sample meetings are exported, so a real meeting can never end up
on the website. Re-run after analysing the samples again in the app.

    .venv/Scripts/python scripts/build_demo.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
for path in (_BACKEND, _BACKEND / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import score  # noqa: E402
from app.report import render_markdown  # noqa: E402
from app.runs import Run  # noqa: E402

SITE_DEMO = _BACKEND.parent / "site" / "demo"
RUNS = _BACKEND / "data" / "runs"


def _latest_runs() -> dict[str, Run]:
    runs: dict[str, Run] = {}
    for p in RUNS.glob("*.json"):
        try:
            run = Run.model_validate_json(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if run.status != "succeeded" or run.analysis is None:
            continue
        runs[run.id] = run
    return runs


def main() -> None:
    runs = _latest_runs()
    if SITE_DEMO.exists():
        shutil.rmtree(SITE_DEMO)
    (SITE_DEMO / "runs").mkdir(parents=True)
    (SITE_DEMO / "reports").mkdir()

    listing, accuracy = [], []
    for key_path in sorted(score.KEYS.glob("*.json")):
        key = score.load_key(key_path)
        matches = [r for r in runs.values() if r.title.startswith(key["match_title"])]
        if not matches:
            print(f"skip  {key_path.stem}: no successful run in the app yet")
            continue
        run = max(matches, key=lambda r: r.created_at)
        demo_id = key_path.stem
        public = run.model_copy(update={"id": demo_id, "plan_job": None, "dropped_items": []})
        data = json.loads(public.model_dump_json())
        (SITE_DEMO / "runs" / f"{demo_id}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        (SITE_DEMO / "reports" / f"{demo_id}.md").write_text(render_markdown(public), encoding="utf-8")
        listing.append(json.loads(public.summary().model_dump_json()))

        res = score.score(data["analysis"], key, data.get("plan"))
        extracted = len(res.correct) + len(res.wrong_category) + len(res.duplicate) + len(res.forbidden) + len(res.unlabelled)
        required = [k for k in key["items"] if not k.optional]
        accuracy.append({
            "id": demo_id,
            "title": run.title,
            "recorded": run.created_at.isoformat(),
            "correct": len(res.correct),
            "extracted": extracted,
            "found": len(required) - len(res.missed),
            "expected": len(required),
            "precision": round(len(res.correct) / extracted, 3) if extracted else 0,
            "recall": round((len(required) - len(res.missed)) / len(required), 3) if required else 0,
            "invented": len(res.forbidden) + len(res.unlabelled),
        })
        print(f"wrote {demo_id}: {run.title} ({run.created_at:%Y-%m-%d %H:%M}) {score.summary_line(res, key)[:40]}")

    listing.sort(key=lambda r: r["title"])
    (SITE_DEMO / "runs.json").write_text(json.dumps(listing, ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE_DEMO / "accuracy.json").write_text(json.dumps(accuracy, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(listing)} runs exported to {SITE_DEMO}")


if __name__ == "__main__":
    main()
