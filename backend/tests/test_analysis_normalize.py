from app.analysis.normalize import normalize_extracted_payload


def test_normalizes_qwen_task_and_open_question_statement_shape() -> None:
    payload = normalize_extracted_payload(
        {
            "decisions": [],
            "requirements": [],
            "tasks": [
                {
                    "statement": "Audit the Stripe webhook handler.",
                    "source_reference": {"excerpt": "Please add a dead-letter queue"},
                }
            ],
            "risks": [{"statement": "Double capture", "source_reference": {"excerpt": "two writers"}}],
            "open_questions": [
                {
                    "statement": "Retention window is unclear.",
                    "source_reference": {"excerpt": "Legal has not answered"},
                }
            ],
        }
    )

    task = payload["tasks"][0]
    assert task["title"] == "Audit the Stripe webhook handler."
    assert task["description"] == "Audit the Stripe webhook handler."
    assert task["priority"] == "medium"
    assert task["source_references"] == [{"excerpt": "Please add a dead-letter queue"}]

    risk = payload["risks"][0]
    assert risk["description"] == "Double capture"
    assert risk["severity"] == "medium"

    question = payload["open_questions"][0]
    assert question["question"] == "Retention window is unclear."
    assert question["context"] == "Retention window is unclear."
