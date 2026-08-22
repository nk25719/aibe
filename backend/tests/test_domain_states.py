import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import IdentificationCandidate, IdentificationStatus, PartSupersession


def test_identification_candidate_states_are_explicit(db_session):
    candidate = IdentificationCandidate(
        case_id=1,
        status=IdentificationStatus.candidate,
        score=0.73,
        method="image_similarity",
    )

    assert candidate.status == IdentificationStatus.candidate
    assert IdentificationStatus.verified_match.value == "verified_match"
    assert IdentificationStatus.insufficient_evidence.value == "insufficient_evidence"


def test_supersession_cannot_reference_same_part(db_session):
    db_session.add(
        PartSupersession(
            old_part_id=1,
            new_part_id=1,
            relationship_type="replaces",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()
