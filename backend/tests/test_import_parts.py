from app.db.models import Part
from app.services.import_parts import import_parts_spreadsheet
from app.services.normalization import normalize_key


def test_parts_import_is_idempotent(db_session):
    first = import_parts_spreadsheet(db_session)
    first_count = db_session.query(Part).count()
    second = import_parts_spreadsheet(db_session)
    second_count = db_session.query(Part).count()

    assert first.rejected == 0
    assert first_count == 123
    assert second_count == first_count
    assert second.inserted == 0
    assert second.rejected == 0


def test_part_number_normalization_prevents_duplicate_parts():
    assert normalize_key(" M1115795-S ") == normalize_key("m1115795-s")
