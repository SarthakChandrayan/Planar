"""Analyze a transcript file end to end with the local model, from the terminal.

Writes <out>/<name>.json (analysis + plan + timings) and <name>.md, and
prints progress as it goes. With --score, also scores the analysis against
the Payment Platform Redesign answer key.

    .venv/Scripts/python scripts/analyze.py ../samples/payment_platform_redesign.txt
    .venv/Scripts/python scripts/analyze.py ../samples/payment_platform_redesign.txt --score
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.dependencies import build_analyzer, build_provider, get_settings  # noqa: E402
from app.observability import configure_logging  # noqa: E402
from app.planning import ImplementationPlanner, PlanValidationError  # noqa: E402
from app.report import render_markdown  # noqa: E402
from app.runs import Run, RunStatus  # noqa: E402


class _ConsoleProgress:
    def __init__(self) -> None:
        self._started = time.monotonic()
        self._stage_started = self._started
        self.stage_seconds: dict[str, float] = {}
        self._label: str | None = None
        self._tokens = 0

    def stage(self, label: str, step: int, total: int) -> None:
        self._close()
        self._label = label
        self._stage_started = time.monotonic()
        self._tokens = 0
        print(f"[{self._elapsed()}] {step}/{total} {label} ...", file=sys.stderr, flush=True)

    def tokens(self, count: int) -> None:
        self._tokens = count

    def finish(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._label is not None:
            seconds = time.monotonic() - self._stage_started
            self.stage_seconds[self._label] = round(seconds, 1)
            print(
                f"[{self._elapsed()}]     done in {seconds:.0f}s, {self._tokens} tokens",
                file=sys.stderr,
                flush=True,
            )
            self._label = None

    def _elapsed(self) -> str:
        seconds = int(time.monotonic() - self._started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--out", type=Path, default=_BACKEND / "data" / "cli")
    parser.add_argument("--no-plan", action="store_true")
    parser.add_argument("--score", action="store_true", help="score vs the payment answer key")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("WARNING", settings.log_format)
    transcript = args.transcript.read_text(encoding="utf-8").strip()
    llm = build_provider(settings)
    llm.check_ready()
    analyzer = build_analyzer(llm, settings)
    progress = _ConsoleProgress()
    print(
        f"model={settings.ollama_model} chars={len(transcript):,} "
        f"stages={analyzer.stage_count(transcript) + (0 if args.no_plan else 1)}",
        file=sys.stderr,
    )

    started = time.monotonic()
    outcome = analyzer.run(transcript, progress, extra_stages=0 if args.no_plan else 1)
    plan = None
    warnings = list(outcome.warnings)
    if not args.no_plan:
        total = analyzer.stage_count(transcript) + 1
        progress.stage("Implementation plan", total, total)
        try:
            plan = ImplementationPlanner(llm).plan(outcome.analysis, progress=progress)
        except PlanValidationError as exc:
            warnings.append(f"Plan failed: {exc}")
    progress.finish()
    total_seconds = round(time.monotonic() - started, 1)

    run = Run(
        id="cli",
        title=args.transcript.stem,
        status=RunStatus.SUCCEEDED,
        created_at=datetime.now(UTC),
        transcript_chars=len(transcript),
        transcript=transcript,
        analysis=outcome.analysis,
        plan=plan,
        warnings=warnings,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    base = args.out / args.transcript.stem
    base.with_suffix(".md").write_text(render_markdown(run), encoding="utf-8")
    base.with_suffix(".json").write_text(
        json.dumps(
            {
                "model": settings.ollama_model,
                "total_seconds": total_seconds,
                "stage_seconds": progress.stage_seconds,
                "warnings": warnings,
                "analysis": outcome.analysis.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json") if plan else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    a = outcome.analysis
    print(
        f"\nDone in {total_seconds / 60:.1f} min: {len(a.decisions)} decisions, "
        f"{len(a.requirements)} requirements, {len(a.tasks)} tasks, {len(a.risks)} risks, "
        f"{len(a.open_questions)} open questions, "
        f"{len(plan.steps) if plan else 0} plan steps"
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Report: {base.with_suffix('.md')}")

    if args.score:
        from tests.evaluation.evaluator import evaluate
        from tests.evaluation.run_payment_platform_redesign_evaluation import render_report

        print()
        print(render_report(evaluate(a), source="this run"))


if __name__ == "__main__":
    main()
