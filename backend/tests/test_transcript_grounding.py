from app.analysis.grounding import Grounder, similarity, text_mentioned
from app.analysis.transcript import NumberedTranscript

TRANSCRIPT = """Meeting: Mobile offline sync
Participants: Ana, Ben

[00:01:10] Ana: We will store drafts in SQLite on the device.
Ben (iOS): Conflict resolution uses last-write-wins per field.
Ana: The sync service must retry with exponential backoff.

Ana: Ben, can you prototype the background sync job by Friday?
Ben: Sure, I'll take that.
Ana: Sync, sync, sync. Everything here is about sync.
Ben: Sync again."""


def test_blank_lines_are_skipped_and_numbering_is_dense() -> None:
    numbered = NumberedTranscript(TRANSCRIPT)
    line = numbered.get(3)
    assert line.source_line == 4  # original position, used for display
    assert line.speaker == "Ana"
    assert line.content == "We will store drafts in SQLite on the device."
    assert [ln.number for ln in numbered.lines] == list(range(1, len(numbered.lines) + 1))


def test_speakers_parse_timestamps_and_roles_but_not_headers() -> None:
    numbered = NumberedTranscript(TRANSCRIPT)
    assert numbered.speakers == ["Ana", "Ben"]
    assert numbered.get(1).speaker is None  # "Meeting:" header
    assert numbered.get(4).speaker == "Ben"  # "Ben (iOS):"


def test_chunks_respect_budget_and_overlap() -> None:
    long = "\n".join(f"Ana: line number {n} with some words in it" for n in range(1, 301))
    chunks = NumberedTranscript(long).chunks(max_tokens=400, overlap_lines=5)

    assert len(chunks) > 1
    for chunk in chunks:
        assert sum(len(line.text) for line in chunk.lines) <= 400 * 3.2 + 50
    assert chunks[1].first == chunks[0].last - 4  # 5 lines of overlap
    assert chunks[-1].last == 300
    assert chunks[0].render().startswith("L1: Ana: line number 1")


def test_short_transcript_is_one_chunk() -> None:
    assert len(NumberedTranscript(TRANSCRIPT).chunks(8000)) == 1


def test_grounding_accepts_supported_and_rejects_unsupported() -> None:
    grounder = Grounder(NumberedTranscript(TRANSCRIPT))

    supported = grounder.ground("Store drafts in SQLite on the device", [3])
    assert supported is not None and not supported.reanchored
    assert grounder.ground("Migrate the billing database to Oracle", [3]) is None


def test_words_common_to_the_meeting_do_not_count_as_support() -> None:
    grounder = Grounder(NumberedTranscript(TRANSCRIPT))
    # "sync" appears on many lines, so it alone cannot ground a claim.
    assert grounder.ground("Sync dashboards for finance", [8]) is None


def test_grounding_reanchors_near_misses() -> None:
    grounder = Grounder(NumberedTranscript(TRANSCRIPT))
    result = grounder.ground("Retry with exponential backoff", [6])
    assert result is not None and result.reanchored
    assert result.lines[0].source_line == 6


def test_badly_cited_claim_is_found_elsewhere_only_if_clearly_stated() -> None:
    long = "\n".join(
        [f"Ana: filler about lunch number {n}" for n in range(1, 40)]
        + ["Ben: We agreed to store drafts in SQLite on the device."]
    )
    grounder = Grounder(NumberedTranscript(long))
    found = grounder.ground("Store drafts in SQLite on the device", [2])
    assert found is not None and found.lines[0].number == 40
    # A claim that only shares a word or two is not rescued.
    assert grounder.ground("Store invoices in Oracle", [2]) is None


def test_text_mentioned_and_similarity() -> None:
    assert text_mentioned("Ben", TRANSCRIPT)
    assert text_mentioned("by Friday", TRANSCRIPT)
    assert not text_mentioned("Charlie", TRANSCRIPT)
    assert similarity("Store drafts in SQLite", "Drafts are stored in SQLite") >= 0.5
    assert similarity("Store drafts in SQLite", "Retry with backoff") == 0.0


def test_long_lines_are_trimmed_to_supporting_sentences() -> None:
    recap = (
        "Ana: Let me recap the whole meeting for everyone here today. "
        "We use SQLite for drafts on both platforms. "
        "Photos upload separately through a resumable queue. "
        "Conflicts resolve with last-write-wins per field on server time. "
        "The storage cap stays open until we have the fleet data from MDM."
    )
    numbered = NumberedTranscript(recap)
    grounder = Grounder(numbered)
    excerpt = grounder.excerpt(numbered.get(1), "Photos upload through a resumable queue")
    assert excerpt == "… Photos upload separately through a resumable queue. …"


def test_evidence_is_one_passage_not_scattered_lines() -> None:
    numbered = NumberedTranscript(TRANSCRIPT)
    grounder = Grounder(numbered)
    # Cites the right line plus an unrelated far-away line.
    result = grounder.ground("Store drafts in SQLite on the device", [3, 9])
    assert result is not None
    assert [line.number for line in result.lines] == [3]


def test_markdown_formatting_is_stripped_and_speakers_found() -> None:
    numbered = NumberedTranscript(
        "## 10. Action Items\n"
        "**Sarah:** Finalize the **premium** feature list.\n"
        "* Ananya — CEO\n"
        "- __Rahul__: Prepare the campaign.\n"
        "2. The discount is `15%` for 30 days."
    )
    lines = numbered.lines
    assert lines[0].text == "10. Action Items"
    assert (lines[1].speaker, lines[1].content) == ("Sarah", "Finalize the premium feature list.")
    assert lines[2].text == "Ananya — CEO" and lines[2].speaker is None
    assert lines[3].speaker == "Rahul"
    assert lines[4].text == "2. The discount is 15% for 30 days."


def test_meeting_notes_bracket_names_are_speakers_not_timestamps() -> None:
    numbered = NumberedTranscript(
        "[Ellie Sarmadi] Monetize Chat: Develop tiered monetization levels.\n"
        "[The group] Select pilot features: Brainstorm the features.\n"
        "[00:12:03] Maya: We will ship it.\n"
        "[12] Footnote style reference."
    )
    lines = numbered.lines
    assert lines[0].speaker == "Ellie Sarmadi"
    assert lines[0].content == "Monetize Chat: Develop tiered monetization levels."
    assert lines[1].speaker == "The group"
    assert lines[2].speaker == "Maya"
    assert lines[3].speaker is None


def test_notes_headings_with_two_colons_are_not_speakers() -> None:
    numbered = NumberedTranscript(
        "Monetization Layers: Subscriptions, Workouts, and Live Streams: Ellie outlined it.\n"
        "Maya: We will ship on Friday."
    )
    assert numbered.lines[0].speaker is None
    assert numbered.lines[1].speaker == "Maya"


def test_hedged_lines_and_coverage() -> None:
    from app.analysis.grounding import coverage, is_hedged

    assert is_hedged("Karan estimated the team could support approximately 50 accounts.")
    assert is_hedged("Maybe we should add Redis.")
    assert not is_hedged("The sync API must accept per-field timestamps.")
    # Firm wording wins even when the line also hedges.
    assert not is_hedged("Payments could fail, so the handler must retry.")
    assert coverage("launch on November 4", "The November 4 launch date") == 1.0
    assert coverage("refund policy", "The November 4 launch date") == 0.0


def test_joined_evidence_never_doubles_ellipses() -> None:
    from app.analysis.analyzer import _source
    from app.analysis.grounding import Grounding

    long_line = "Ana: " + " ".join(f"Filler sentence number {n}." for n in range(12)) + " Pricing caused confusion."
    numbered = NumberedTranscript(long_line + "\n" + long_line.replace("Pricing", "Value"))
    grounder = Grounder(numbered)
    ref = _source(Grounding(tuple(numbered.lines), 2.0, False), grounder, "pricing confusion value")
    assert "… …" not in ref.excerpt
    assert ref.excerpt.count("…") >= 1
