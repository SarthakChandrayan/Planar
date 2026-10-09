"""Run the analysis on every meeting that has an answer key, and score it.

Uses the real local model (Ollama must be running). Each meeting takes a few
minutes. Results are saved to data/eval/<name>/<meeting>.json so they can be
re-scored later with scripts/score.py --run, and a summary is printed.

    .venv/Scripts/python scripts/evaluate.py --name current
    .venv/Scripts/python scripts/evaluate.py --name no-second-look --no-second-look --only checkout_event_architecture
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
for path in (_BACKEND, _BACKEND / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import score  # noqa: E402
from app.dependencies import build_analyzer, build_provider, get_settings  # noqa: E402
from app.observability import configure_logging  # noqa: E402

_ROOT = _BACKEND.parent


class _Quiet:
    def stage(self, label: str, step: int, total: int) -> None:
        print(f"    {step}/{total} {label}", file=sys.stderr, flush=True)

    def tokens(self, count: int) -> None:
        pass

    def finish(self) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="results folder under data/eval")
    parser.add_argument("--no-second-look", action="store_true", help="skip the second look")
    parser.add_argument("--only", action="append", help="key file stem(s) to run")
    args = parser.parse_args()

    settings = get_settings().model_copy(update={"analysis_second_look": not args.no_second_look})
    configure_logging("WARNING", settings.log_format)
    llm = build_provider(settings)
    llm.check_ready()
    analyzer = build_analyzer(llm, settings)
    out_dir = _BACKEND / "data" / "eval" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = []
    for key_path in sorted(score.KEYS.glob("*.json")):
        if args.only and key_path.stem not in args.only:
            continue
        key = score.load_key(key_path)
        transcript = (_ROOT / json.loads(key_path.read_text(encoding="utf-8"))["transcript"]).read_text(encoding="utf-8")
        print(f"== {key['name']} ({args.name})", file=sys.stderr, flush=True)
        started = time.monotonic()
        outcome = analyzer.run(transcript, _Quiet())
        seconds = round(time.monotonic() - started)
        data = {
            "title": key["match_title"],
            "name": args.name,
            "model": settings.ollama_model,
            "seconds": seconds,
            "analysis": outcome.analysis.model_dump(mode="json"),
            "dropped": outcome.dropped,
            "warnings": outcome.warnings,
        }
        (out_dir / f"{key_path.stem}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        result = score.score(data["analysis"], key)
        line = f"{key_path.stem:34} {seconds // 60:2d}m{seconds % 60:02d}s  {score.summary_line(result, key)}"
        lines.append(line)
        print(line, flush=True)
    print("\n".join(["", f"Summary ({args.name}):", *lines]))


if __name__ == "__main__":
    main()
