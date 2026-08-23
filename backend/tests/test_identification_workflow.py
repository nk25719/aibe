from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
IMAGE = Path("backend/images/755534-HEL 1.jpeg")


def _submit(fields=None, image=IMAGE, filename="part.jpeg", mime="image/jpeg"):
    fields = fields or {"manufacturer": "GE Healthcare"}
    with image.open("rb") as fh:
        return client.post(
            "/api/identification/cases",
            data=fields,
            files=[("files", (filename, fh, mime))],
        )


def test_image_only_submission_requires_manufacturer():
    with IMAGE.open("rb") as fh:
        response = client.post("/api/identification/cases", files=[("files", ("part.jpeg", fh, "image/jpeg"))])

    assert response.status_code == 422


def test_manufacturer_plus_image_returns_candidates():
    response = _submit({"manufacturer": "GE Healthcare"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"]
    assert payload["candidates"][0]["verification_status"] in {"candidate", "probable_match"}


def test_manufacturer_model_plus_image_returns_supported_factors():
    response = _submit({"manufacturer": "GE Healthcare", "equipment_model": "E-sCaiO"})

    assert response.status_code == 200
    factors = response.json()["candidates"][0]["match_factors"]
    assert any(factor["type"] in {"manufacturer", "equipment_model"} for factor in factors)


def test_partial_part_number_search_in_identification():
    response = _submit({"manufacturer": "GE Healthcare", "visible_markings": "755534"})

    assert response.status_code == 200
    assert any(candidate["official_part_number"] == "755534-HEL" for candidate in response.json()["candidates"])


def test_multiple_candidates_and_evidence_citations():
    response = _submit({"manufacturer": "GE Healthcare", "description": "filter fan"})

    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert candidates
    assert candidates[0]["source_evidence"]
    assert candidates[0]["normalized_part_id"]
    assert candidates[0]["data_origin"] != "legacy_parts_db_fallback"


def test_no_match_returns_follow_up_questions():
    response = _submit({"manufacturer": "Nonexistent Maker", "visible_markings": "ZZZ-UNKNOWN"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["follow_up_questions"]


def test_invalid_files_are_rejected():
    response = client.post(
        "/api/identification/cases",
        data={"manufacturer": "GE Healthcare"},
        files=[("files", ("bad.txt", b"not image", "text/plain"))],
    )

    assert response.status_code == 415


def test_conflicting_compatibility_is_displayed():
    response = _submit({"manufacturer": "GE Healthcare", "equipment_model": "Unrelated Model", "description": "calibration gas"})

    assert response.status_code == 200
    assert response.json()["candidates"][0]["contradicting_evidence"]


def test_confirmation_and_rejection_are_recorded():
    case = _submit({"manufacturer": "GE Healthcare", "visible_markings": "755534"}).json()
    candidate_id = case["candidates"][0]["candidate_id"]
    confirm = client.post(
        f"/api/identification/cases/{case['case_id']}/candidates/{candidate_id}/action",
        json={"action": "confirm", "user": "nk", "notes": "label matches"},
    )
    reject = client.post(
        f"/api/identification/cases/{case['case_id']}/candidates/{candidate_id}/action",
        json={"action": "reject", "user": "nk", "notes": "testing rejection audit"},
    )

    assert confirm.status_code == 200
    assert confirm.json()["status"] == "verified_match"
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected_candidate"


def test_api_failure_for_missing_candidate():
    response = client.post(
        "/api/identification/cases/999/candidates/999/action",
        json={"action": "confirm", "user": "nk"},
    )

    assert response.status_code == 404
