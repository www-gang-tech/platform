"""Timeline capping keeps the current end of a chronology."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.ask.timeline import build_timeline, gaps, to_payload


def _dated(day, document_id):
    return {
        "document_id": document_id,
        "title": document_id,
        "updated": f"2026-01-{day:02d}",
        "excerpts": [document_id],
    }


def test_a_long_timeline_keeps_the_newest_documents():
    rows = [_dated(day, f"d{day}") for day in range(1, 26)]
    items = build_timeline(rows, limit=20)

    assert [item.document_id for item in items] == [f"d{day}" for day in range(6, 26)]
    assert items.omitted == 5
    assert gaps(items) == []


def test_undated_documents_fill_only_the_room_after_dated_ones():
    rows = [_dated(day, f"d{day}") for day in range(1, 19)]
    rows.extend(
        {"document_id": f"u{i}", "title": f"u{i}", "excerpts": ["note"]}
        for i in range(1, 5)
    )
    items = build_timeline(rows, limit=20)

    assert [item.document_id for item in items[:18]] == [f"d{day}" for day in range(1, 19)]
    assert [item.document_id for item in items[18:]] == ["u1", "u2"]
    assert items.omitted == 2


def test_a_capped_timeline_does_not_call_itself_complete():
    rows = [_dated(day, f"d{day}") for day in range(1, 26)]
    payload = to_payload(build_timeline(rows, limit=20))

    assert "Do not infer intermediate events" in payload["rule"]
    assert "newest window" in payload["rule"]
    assert "5 older retrieved document" in payload["rule"]
    assert payload["items"][-1]["document_id"] == "d25"


def test_a_short_timeline_is_unchanged():
    rows = [
        _dated(1, "a"),
        {"document_id": "undated", "title": "Undated", "excerpts": ["note"]},
        _dated(10, "b"),
    ]
    items = build_timeline(rows, limit=20)

    assert [item.document_id for item in items] == ["a", "b", "undated"]
    assert items.omitted == 0
    assert "complete chronology" in to_payload(items)["rule"]
