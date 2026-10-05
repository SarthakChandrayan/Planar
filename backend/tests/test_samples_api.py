from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_settings
from app.main import app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    (tmp_path / "short_one.txt").write_text("Meeting: Short sync\nLin: Ship it.", encoding="utf-8")
    (tmp_path / "longer.txt").write_text("Lin: " + "word " * 50, encoding="utf-8")
    (tmp_path / "notes.md").write_text("not a sample", encoding="utf-8")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, samples_dir=tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lists_txt_samples_shortest_first(client: TestClient) -> None:
    body = client.get("/api/samples").json()
    assert [s["id"] for s in body] == ["short_one", "longer"]
    assert body[0]["title"] == "Short sync"
    assert body[1]["title"] == "Longer"
    assert "transcript" not in body[0]


def test_get_sample_returns_transcript(client: TestClient) -> None:
    body = client.get("/api/samples/short_one").json()
    assert body["transcript"].startswith("Meeting: Short sync")


def test_unknown_or_path_like_ids_are_404(client: TestClient) -> None:
    assert client.get("/api/samples/missing").status_code == 404
    assert client.get("/api/samples/..%2Fsecrets").status_code == 404
    assert client.get("/api/samples/notes").status_code == 404


def test_real_samples_folder_has_samples() -> None:
    ids = {p.stem for p in Settings(_env_file=None).samples_dir.glob("*.txt")}
    assert {"mobile_offline_sync", "payment_platform_redesign"} <= ids
