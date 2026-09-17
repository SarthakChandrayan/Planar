import pytest

from app.analysis.parsing import parse_json_object


def test_parse_plain_json_object() -> None:
    assert parse_json_object('{"decisions": []}') == {"decisions": []}


def test_parse_json_inside_think_and_fences() -> None:
    text = """
    <think>planning the extraction</think>
    ```json
    {"risks": []}
    ```
    """
    assert parse_json_object(text) == {"risks": []}


def test_parse_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_json_object('["not", "an", "object"]')


def test_parse_rejects_prose() -> None:
    with pytest.raises(ValueError):
        parse_json_object("The team decided to use Stripe.")
