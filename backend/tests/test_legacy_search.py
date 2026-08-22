from app.services.legacy_search import search_parts


def test_legacy_search_returns_existing_parts():
    rows = search_parts("filter", limit=3)

    assert len(rows) == 3
    assert rows[0]["part_number"]
