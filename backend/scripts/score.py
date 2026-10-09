"""Score analyses against hand-labelled answer keys, by transcript line.

An answer key (tests/evaluation/keys/*.json) lists what a meeting really
contains: each item has the categories it may appear as, the transcript
lines that state it, and optionally the strength it was stated with ("must",
"should"), words a complete version must keep, and its owner. It also lists
things that must NOT be extracted (an answered question as an open question).

An extracted item matches a key item when it cites one of the key item's
lines and shares enough words with it. Matching by line, not by wording, keeps
the score from rewarding a particular phrasing.

    .venv/Scripts/python scripts/score.py                      # latest saved run of every keyed meeting
    .venv/Scripts/python scripts/score.py --run data/runs/X.json
    .venv/Scripts/python scripts/score.py --all-runs           # every saved run, one line each
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
KEYS = _BACKEND / "tests" / "evaluation" / "keys"
RUNS = _BACKEND / "data" / "runs"

CATEGORIES = ("decision", "requirement", "task", "risk", "open_question")
# Share of a key item's words an extracted item must contain to be the same item
# (only among items citing the same lines, so it can be low).
_MIN_WORD_SHARE = 0.25

_STOP = frozenset(
    """a an the and or but for to of in on at as is are be been was were it its this that these
    those with from by we our they their there then than so if not no do does did have has had
    will would should must can could may might need needs i i'd i'll you he she him her them
    what when which who how why yes just also only any all each every some more most into
    about after before until because while""".split()
)


def _stem(w: str) -> str:
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suffix) and len(w) - len(suffix) >= 4:
            return w[: len(w) - len(suffix)] + keep
    return w


def words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9_]+", text.lower()):
        if w in _STOP or len(w) < 2:
            continue
        out.add(_stem(w))
    return out


def share(key_text: str, item_text: str) -> float:
    """How much the two texts are about the same thing (either direction).

    Two-way so that a terse item ("Use outbox-based event publication") still
    matches a fuller key item, and a long item matches a terse key item.
    """
    k, i = words(key_text), words(item_text)
    if not k or not i:
        return 0.0
    common = len(k & i)
    return max(common / len(k), common / len(i))


_STRENGTH = (
    ("never", re.compile(r"\bnever\b", re.I)),
    ("must not", re.compile(r"\b(?:must not|mustn't|cannot|can't|prohibit\w*|forbid\w*)\b", re.I)),
    ("should not", re.compile(r"\b(?:should not|shouldn't)\b", re.I)),
    ("must", re.compile(r"\b(?:must|mandatory|required|requires?|has to|have to)\b", re.I)),
    ("should", re.compile(r"\b(?:should|preferred|ideally)\b", re.I)),
)


def strength(text: str) -> str | None:
    for name, pattern in _STRENGTH:
        if pattern.search(text):
            return name
    return None


# ---------------------------------------------------------------------- data


@dataclass
class KeyItem:
    id: str
    text: str
    categories: list[str]
    lines: set[int]
    strength: str | None = None
    must_include: list[str] = field(default_factory=list)
    owner: str | None = None
    optional: bool = False


@dataclass
class Forbidden:
    text: str
    categories: list[str]
    lines: set[int]
    why: str
    # A rejected option is forbidden only when stated as if adopted: "Use
    # Kafka for webhooks" is wrong, "Do not use Kafka for webhooks" is right.
    if_affirmed: bool = False


_NEGATION = re.compile(
    r"\b(?:do not|don't|not|no|never|without|out of scope|reject\w*|instead of|avoid)\b", re.I
)


@dataclass
class Extracted:
    category: str
    id: str
    text: str
    lines: set[int]
    owner: str | None = None


def _lines(spec: list) -> set[int]:
    out: set[int] = set()
    for part in spec:
        if isinstance(part, str) and "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def load_key(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = [
        KeyItem(
            id=i["id"],
            text=i["text"],
            categories=i["categories"],
            lines=_lines(i["lines"]),
            strength=i.get("strength"),
            must_include=i.get("must_include", []),
            owner=i.get("owner"),
            optional=i.get("optional", False),
        )
        for i in raw["items"]
    ]
    forbidden = [
        Forbidden(
            text=f["text"],
            categories=f["categories"],
            lines=_lines(f["lines"]),
            why=f["why"],
            if_affirmed=f.get("if_affirmed", False),
        )
        for f in raw.get("forbidden", [])
    ]
    return {
        "name": raw["name"],
        "match_title": raw["match_title"],
        "items": items,
        "forbidden": forbidden,
        "forbidden_terms": raw.get("forbidden_terms", []),
    }


def extracted_items(analysis: dict) -> list[Extracted]:
    out: list[Extracted] = []

    def refs(item: dict) -> list[dict]:
        return item.get("source_references") or ([item["source_reference"]] if item.get("source_reference") else [])

    def lines(item: dict) -> set[int]:
        got: set[int] = set()
        for ref in refs(item):
            if ref.get("line_start") is not None:
                got.update(range(ref["line_start"], (ref.get("line_end") or ref["line_start"]) + 1))
        return got

    for d in analysis.get("decisions", []):
        out.append(Extracted("decision", d["id"], d["statement"], lines(d)))
    for r in analysis.get("requirements", []):
        out.append(Extracted("requirement", r["id"], r["statement"], lines(r)))
    for t in analysis.get("tasks", []):
        out.append(Extracted("task", t["id"], f"{t['title']}. {t['description']}", lines(t), t.get("owner")))
    for k in analysis.get("risks", []):
        out.append(Extracted("risk", k["id"], k["description"], lines(k)))
    for q in analysis.get("open_questions", []):
        out.append(Extracted("open_question", q["id"], q["question"], lines(q)))
    return out


# ---------------------------------------------------------------------- scoring


@dataclass
class Result:
    correct: list[tuple[Extracted, KeyItem]] = field(default_factory=list)
    wrong_category: list[tuple[Extracted, KeyItem]] = field(default_factory=list)
    duplicate: list[tuple[Extracted, KeyItem]] = field(default_factory=list)
    forbidden: list[tuple[Extracted, Forbidden]] = field(default_factory=list)
    unlabelled: list[Extracted] = field(default_factory=list)
    missed: list[KeyItem] = field(default_factory=list)
    fidelity: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)


def _best(item: Extracted, candidates, text_of) -> tuple[float, object] | None:
    best = None
    for c in candidates:
        if not (item.lines & c.lines):
            continue
        s = share(text_of(c), item.text)
        if s >= _MIN_WORD_SHARE and (best is None or s > best[0]):
            best = (s, c)
    return best


def score(analysis: dict, key: dict, plan: dict | None = None) -> Result:
    res = Result()
    found: dict[str, set[str]] = {}  # key id -> categories it was found in
    for item in extracted_items(analysis):
        negated = bool(_NEGATION.search(item.text))
        candidates = [
            f for f in key["forbidden"] if item.category in f.categories and not (f.if_affirmed and negated)
        ]
        bad = _best(item, candidates, lambda f: f.text)
        # Several key items can cite the same line ("prepare two options" and
        # "which option?" both cite L64): prefer one this category may be.
        fits = _best(item, [k for k in key["items"] if item.category in k.categories], lambda k: k.text)
        match = fits or _best(item, key["items"], lambda k: k.text)
        if bad and (match is None or bad[0] > match[0]):
            res.forbidden.append((item, bad[1]))
            continue
        if match is None:
            res.unlabelled.append(item)
            continue
        k: KeyItem = match[1]
        if item.category not in k.categories:
            res.wrong_category.append((item, k))
            continue
        if item.category in found.get(k.id, set()):
            res.duplicate.append((item, k))
            continue
        found.setdefault(k.id, set()).add(item.category)
        res.correct.append((item, k))
        if k.strength:
            got = strength(item.text)
            if got != k.strength:
                res.fidelity.append(f"{item.id}: said '{k.strength}', extracted as '{got or 'no modal'}'")
        missing = [w for w in k.must_include if w.lower() not in item.text.lower()]
        if missing:
            res.fidelity.append(f"{item.id}: leaves out {', '.join(missing)}")
        if k.owner and (item.owner or "").lower() != k.owner.lower():
            res.fidelity.append(f"{item.id}: owner {item.owner!r}, expected {k.owner!r}")
    res.missed = [k for k in key["items"] if not k.optional and k.id not in found]

    texts = [i.text for i in extracted_items(analysis)]
    if plan:
        texts += [plan.get("summary", "")] + [f"{s['title']} {s['description']}" for s in plan.get("steps", [])]
    for term in key["forbidden_terms"]:
        if any(term.lower() in t.lower() for t in texts):
            res.terms.append(term)
    return res


_KIND_TO_CATEGORY = {"open question": "open_question", "open_question": "open_question"}


def wrongly_dropped(dropped: list[dict], res: Result, key: dict) -> list[str]:
    """Items a check removed that look like a key item the result is missing.

    Dropped items carry no line numbers, so this matches by wording only and
    needs a closer match than line-backed scoring.
    """
    out = []
    missed = {k.id: k for k in res.missed}
    for d in dropped:
        category = _KIND_TO_CATEGORY.get(d.get("kind", ""), d.get("kind", ""))
        best = None
        for k in missed.values():
            if category not in k.categories:
                continue
            s = share(k.text, d.get("text", ""))
            if s >= 0.5 and (best is None or s > best[0]):
                best = (s, k)
        if best:
            out.append(f"{category}: {d['text'][:90]}  <{d.get('reason')}>  looks like {best[1].id}")
    return out


def summary_line(res: Result, key: dict) -> str:
    extracted = len(res.correct) + len(res.wrong_category) + len(res.duplicate) + len(res.forbidden) + len(res.unlabelled)
    required = [k for k in key["items"] if not k.optional]
    precision = len(res.correct) / extracted if extracted else 0.0
    recall = (len(required) - len(res.missed)) / len(required) if required else 0.0
    return (
        f"precision {precision:.0%} recall {recall:.0%} | correct {len(res.correct)} "
        f"wrong-category {len(res.wrong_category)} forbidden {len(res.forbidden)} "
        f"duplicate {len(res.duplicate)} unlabelled {len(res.unlabelled)} missed {len(res.missed)} "
        f"fidelity {len(res.fidelity)} terms {len(res.terms)}"
    )


def per_category(res: Result, key: dict) -> list[str]:
    rows = []
    for cat in CATEGORIES:
        correct = sum(1 for e, _ in res.correct if e.category == cat)
        bad = (
            sum(1 for e, _ in res.wrong_category if e.category == cat)
            + sum(1 for e, _ in res.forbidden if e.category == cat)
            + sum(1 for e, _ in res.duplicate if e.category == cat)
            + sum(1 for e in res.unlabelled if e.category == cat)
        )
        expected = [k for k in key["items"] if not k.optional and k.categories[0] == cat]
        missed = sum(1 for k in res.missed if k.categories[0] == cat)
        p = f"{correct / (correct + bad):.0%}" if correct + bad else "  -"
        r = f"{(len(expected) - missed) / len(expected):.0%}" if expected else "  -"
        rows.append(f"  {cat:14} precision {p:>4}  recall {r:>4}  ({correct} right, {bad} wrong, {missed} missed)")
    return rows


def report(res: Result, key: dict, source: str) -> str:
    out = [f"## {key['name']}  [{source}]", summary_line(res, key), *per_category(res, key)]

    def item(e: Extracted) -> str:
        return f"{e.category} {e.id} (L{min(e.lines) if e.lines else '?'}) {e.text[:90]}"

    if res.forbidden:
        out.append("\nShould not be there:")
        out += [f"  - {item(e)}\n      why: {f.why}" for e, f in res.forbidden]
    if res.wrong_category:
        out.append("\nWrong category:")
        out += [f"  - {item(e)}\n      is {k.id} ({'/'.join(k.categories)}): {k.text}" for e, k in res.wrong_category]
    if res.duplicate:
        out.append("\nDuplicates:")
        out += [f"  - {item(e)}  (again {k.id})" for e, k in res.duplicate]
    if res.fidelity:
        out.append("\nWording:")
        out += [f"  - {f}" for f in res.fidelity]
    if res.terms:
        out.append("\nTerms the meeting never used: " + ", ".join(res.terms))
    if res.missed:
        out.append("\nMissed:")
        out += [f"  - {k.id} ({'/'.join(k.categories)}) L{min(k.lines)}: {k.text}" for k in res.missed]
    if res.unlabelled:
        out.append("\nNot in the key (check by hand; counted as wrong):")
        out += [f"  - {item(e)}" for e in res.unlabelled]
    return "\n".join(out)


# ---------------------------------------------------------------------- cli


def _runs_for(key: dict) -> list[dict]:
    runs = []
    for p in RUNS.glob("*.json"):
        run = json.loads(p.read_text(encoding="utf-8"))
        if run.get("analysis") and run.get("title", "").startswith(key["match_title"]):
            runs.append(run)
    return sorted(runs, key=lambda r: r["created_at"])


def main() -> None:
    # The Windows console defaults to cp1252, which cannot print "₹".
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, help="a saved run or scripts/analyze.py output")
    parser.add_argument("--key", help="only this key (file stem)")
    parser.add_argument("--all-runs", action="store_true", help="one line per saved run")
    args = parser.parse_args()

    keys = [load_key(p) for p in sorted(KEYS.glob("*.json")) if not args.key or p.stem == args.key]
    if args.run:
        data = json.loads(args.run.read_text(encoding="utf-8"))
        title = data.get("title", "")
        key = next((k for k in keys if title.startswith(k["match_title"])), keys[0] if len(keys) == 1 else None)
        if key is None:
            sys.exit("pass --key: cannot tell which meeting this run is")
        res = score(data["analysis"], key, data.get("plan"))
        print(report(res, key, args.run.name))
        dropped = data.get("dropped") or data.get("dropped_items") or []
        lost = wrongly_dropped(dropped, res, key)
        if lost:
            print("\nRemoved by a check but looks like a missed key item:")
            print("\n".join(f"  - {line}" for line in lost))
        return
    for key in keys:
        runs = _runs_for(key)
        if not runs:
            print(f"## {key['name']}: no saved run")
            continue
        if args.all_runs:
            print(f"## {key['name']}")
            for run in runs:
                print(f"  {run['created_at'][:16]}  {summary_line(score(run['analysis'], key, run.get('plan')), key)}")
        else:
            run = runs[-1]
            print(report(score(run["analysis"], key, run.get("plan")), key, run["created_at"][:16]))
        print()


if __name__ == "__main__":
    main()
