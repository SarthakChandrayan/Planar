"""Example transcripts the UI offers, read from ``samples_dir`` (*.txt)."""

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import Settings
from app.dependencies import get_settings

router = APIRouter(prefix="/api/samples", tags=["samples"])

_SAMPLE_ID = re.compile(r"^[a-z0-9_-]{1,80}$")
_TITLE_PREFIXES = ("meeting:", "title:", "subject:")


class SampleSummary(BaseModel):
    id: str
    title: str
    words: int


class Sample(SampleSummary):
    transcript: str


def _title(sample_id: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(_TITLE_PREFIXES):
            title = stripped.split(":", 1)[1].strip()
            if title:
                return title
    return sample_id.replace("_", " ").replace("-", " ").capitalize()


def _load(path: Path) -> Sample:
    text = path.read_text(encoding="utf-8").strip()
    return Sample(id=path.stem, title=_title(path.stem, text), words=len(text.split()), transcript=text)


def _paths(settings: Settings) -> list[Path]:
    if not settings.samples_dir.is_dir():
        return []
    return sorted(p for p in settings.samples_dir.glob("*.txt") if _SAMPLE_ID.match(p.stem))


@router.get("", response_model=list[SampleSummary])
def list_samples(settings: Annotated[Settings, Depends(get_settings)]) -> list[SampleSummary]:
    samples = [_load(path) for path in _paths(settings)]
    return [SampleSummary(**s.model_dump(exclude={"transcript"})) for s in sorted(samples, key=lambda s: s.words)]


@router.get("/{sample_id}", response_model=Sample)
def get_sample(sample_id: str, settings: Annotated[Settings, Depends(get_settings)]) -> Sample:
    # Only names from the samples folder itself: never a path the client builds.
    for path in _paths(settings):
        if path.stem == sample_id:
            return _load(path)
    raise HTTPException(status_code=404, detail="Sample not found.")
