"""Answer keys stay consistent with their transcripts."""

import json
from pathlib import Path

import pytest

KEYS = Path(__file__).parent / "keys"
ROOT = Path(__file__).resolve().parents[3]
CATEGORIES = {"decision", "requirement", "task", "risk", "open_question"}


def _lines(spec: list) -> set[int]:
    out: set[int] = set()
    for part in spec:
        if isinstance(part, str) and "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


@pytest.mark.parametrize("path", sorted(KEYS.glob("*.json")), ids=lambda p: p.stem)
def test_key_cites_real_lines_and_known_categories(path: Path) -> None:
    key = json.loads(path.read_text(encoding="utf-8"))
    transcript = (ROOT / key["transcript"]).read_text(encoding="utf-8").splitlines()
    ids = [item["id"] for item in key["items"]]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for item in key["items"] + key.get("forbidden", []):
        assert set(item["categories"]) <= CATEGORIES, item
        lines = _lines(item["lines"])
        assert lines and max(lines) <= len(transcript), item
        assert any(transcript[n - 1].strip() for n in lines), f"only blank lines: {item}"
