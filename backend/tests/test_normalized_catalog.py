import io

import pytest
from fastapi import UploadFile

from app.db.models import (
    DataQualityIssue,
    DataQualityIssueStatus,
    Manufacturer,
    Part,
    PartAlias,
    PartSupersession,
)
from app.services.catalog import get_catalog_options
from app.services.catalog_query import CatalogSearchParams, search_catalog
from app.services.identification import CaseInput, create_identification_case
from app.services.import_parts import import_parts_spreadsheet, resolve_data_quality_issue, validate_supersession


def seed(db_session):
    import_parts_spreadsheet(db_session)


def test_exact_normalized_part_number_search_uses_normalized_data(db_session):
    seed(db_session)

    response = search_catalog(db_session, CatalogSearchParams(q="755534hel", manufacturer="GE Healthcare"))

    assert response["source"] == "normalized_catalog"
    assert response["legacy_fallback_used"] is False
    assert response["results"][0]["part_number"] == "755534-HEL"
    assert response["results"][0]["normalized_part_id"]


def test_alias_search_finds_canonical_part(db_session):
    seed(db_session)

    response = search_catalog(db_session, CatalogSearchParams(q="1009-3064-000"))

    assert response["results"][0]["part_number"]
    assert any(alias["alias"] == "1009-3064-000" for alias in response["results"][0]["aliases"])


def test_partial_number_search_ranks_prefix_above_general_matches(db_session):
    seed(db_session)

    response = search_catalog(db_session, CatalogSearchParams(q="755", manufacturer="GE Healthcare", limit=5))

    assert response["results"]
    assert response["results"][0]["part_number"].startswith("755")
    assert response["results"][0]["rank_score"] >= response["results"][-1]["rank_score"]


def test_manufacturer_filter_and_model_compatibility(db_session):
    seed(db_session)

    compatible = search_catalog(db_session, CatalogSearchParams(q="755534", manufacturer="GE Healthcare", equipment_model="E-sCaiO"))
    incompatible = search_catalog(db_session, CatalogSearchParams(q="755534", manufacturer="GE Healthcare", equipment_model="Unrelated Model"))

    assert compatible["results"][0]["part_number"] == "755534-HEL"
    assert any(factor["type"] == "equipment_model" for factor in compatible["results"][0]["match_factors"])
    assert incompatible["results"][0]["contradicting_evidence"]


def test_superseded_part_returns_replacement(db_session):
    maker = Manufacturer(name="Maker", normalized_name="maker")
    old = Part(part_number="OLD-1", normalized_part_number="OLD1", description="Old", manufacturer=maker)
    new = Part(part_number="NEW-1", normalized_part_number="NEW1", description="New", manufacturer=maker)
    db_session.add_all([maker, old, new])
    db_session.flush()
    db_session.add(PartSupersession(old_part_id=old.id, new_part_id=new.id, relationship_type="replaced_by"))
    db_session.commit()

    response = search_catalog(db_session, CatalogSearchParams(q="OLD-1"))

    assert response["results"][0]["supersession"]["is_superseded"] is True
    assert response["results"][0]["supersession"]["replacements"][0]["part_number"] == "NEW-1"


def test_legacy_fallback_is_disabled_by_default_and_labeled_when_enabled(db_session):
    disabled = search_catalog(db_session, CatalogSearchParams(q="filter"))
    enabled = search_catalog(db_session, CatalogSearchParams(q="filter", enable_legacy_fallback=True, limit=1))

    assert disabled["legacy_fallback_used"] is False
    assert disabled["results"] == []
    assert enabled["legacy_fallback_used"] is True
    assert enabled["results"][0]["data_origin"] == "legacy_parts_db_fallback"


@pytest.mark.anyio
async def test_identification_uses_normalized_candidates_and_snapshot_is_stable(db_session):
    seed(db_session)
    upload = UploadFile(filename="fixture.jpg", file=io.BytesIO(b"not really used"), headers={"content-type": "image/jpeg"})

    # Use a valid sample image payload by loading the repository fixture.
    from pathlib import Path

    image = Path("backend/images/755534-HEL 1.jpeg")
    with image.open("rb") as fh:
        upload = UploadFile(filename=image.name, file=fh, headers={"content-type": "image/jpeg"})
        response = await create_identification_case(
            db_session,
            CaseInput(manufacturer="GE Healthcare", visible_markings="755534", top_k=3),
            [upload],
        )

    candidate = response["candidates"][0]
    part = db_session.get(Part, candidate["normalized_part_id"])
    part.description = "Edited after case creation"
    db_session.commit()

    assert candidate["data_origin"] != "legacy_parts_db_fallback"
    assert candidate["official_description"] != "Edited after case creation"


def test_data_quality_resolution_changes_later_search_and_preserves_source_rows(db_session):
    seed(db_session)
    part = db_session.query(Part).filter_by(part_number="755534-HEL").one()
    issue = DataQualityIssue(
        issue_type="test_canonical_description",
        entity_type="part",
        entity_id=str(part.id),
        severity="medium",
        suggested_resolution="test",
        fingerprint="test-resolution-755534",
    )
    db_session.add(issue)
    db_session.commit()

    before_rows = part.raw_values.copy()
    resolve_data_quality_issue(
        db_session,
        issue.id,
        status=DataQualityIssueStatus.resolved,
        resolution_selected="canonical_description",
        resolution_notes="Reviewed canonical regulator description",
        resolved_by="tester",
        evidence={"canonical_description": "Reviewed canonical regulator description"},
    )
    response = search_catalog(db_session, CatalogSearchParams(q="Reviewed canonical regulator"))

    assert response["results"][0]["part_number"] == "755534-HEL"
    assert db_session.get(Part, part.id).raw_values == before_rows


def test_invalid_cross_manufacturer_resolution_and_supersession_loop_fail(db_session):
    a = Manufacturer(name="A", normalized_name="a")
    b = Manufacturer(name="B", normalized_name="b")
    p1 = Part(part_number="P-1", normalized_part_number="P1", manufacturer=a)
    p2 = Part(part_number="P-2", normalized_part_number="P2", manufacturer=b)
    db_session.add_all([a, b, p1, p2])
    db_session.flush()
    issue = DataQualityIssue(issue_type="merge", entity_type="part", entity_id=str(p1.id), severity="high", suggested_resolution="merge", fingerprint="merge-p1")
    db_session.add(issue)
    db_session.commit()

    with pytest.raises(ValueError):
        resolve_data_quality_issue(
            db_session,
            issue.id,
            status=DataQualityIssueStatus.resolved,
            resolution_selected="canonical_part_number",
            resolution_notes="bad merge",
            resolved_by="tester",
            evidence={"canonical_part_number": "P-2"},
        )
    with pytest.raises(ValueError):
        validate_supersession(db_session, p1.id, p1.id)


def test_catalog_dropdowns_use_stable_normalized_ids(db_session):
    seed(db_session)

    options = get_catalog_options(db_session)

    assert options["manufacturers"][0]["id"]
    assert options["manufacturers"][0]["value"] == str(options["manufacturers"][0]["id"])
    assert all(option["value"] for option in options["equipment_models"])
