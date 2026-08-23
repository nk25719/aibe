import asyncio
import json
from pathlib import Path

from fastapi import UploadFile

from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.services.identification import CaseInput, create_identification_case


FIXTURE = Path(__file__).resolve().parent / "eval_fixture.json"


async def main() -> None:
    Base.metadata.create_all(bind=engine)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"] if isinstance(fixture, dict) else fixture
    top1 = top3 = top5 = no_match = manufacturer_filter = model_filter = unsupported_confirmation = 0
    reciprocal_rank_sum = 0.0
    by_category = {}
    results = []
    with SessionLocal() as db:
        for item in cases:
            image_paths = item.get("image_paths") or [item.get("image")]
            uploads = []
            handles = []
            try:
                for rel_path in image_paths:
                    image_path = Path(__file__).resolve().parent / rel_path
                    fh = image_path.open("rb")
                    handles.append(fh)
                    uploads.append(UploadFile(filename=image_path.name, file=fh, headers={"content-type": "image/jpeg"}))
                response = await create_identification_case(
                    db,
                    CaseInput(
                        manufacturer=item["manufacturer"],
                        equipment_model=item.get("equipment_model"),
                        description=item.get("text_query") or item.get("description"),
                        visible_markings=item.get("partial_part_number") or item.get("visible_markings"),
                        top_k=5,
                    ),
                    uploads,
                )
            finally:
                for handle in handles:
                    handle.close()
            ranked = [candidate["official_part_number"] for candidate in response["candidates"]]
            expected = item.get("expected_part") or item.get("expected_part_number")
            acceptable = set(item.get("acceptable_candidates") or ([expected] if expected else []))
            rank = next((index + 1 for index, part in enumerate(ranked) if part in acceptable), None)
            has_contradiction = any(candidate["contradicting_evidence"] for candidate in response["candidates"])
            top1 += int(rank == 1)
            top3 += int(bool(rank and rank <= 3))
            top5 += int(bool(rank and rank <= 5))
            reciprocal_rank_sum += 1 / rank if rank else 0
            no_match += int(expected is None and response["status"] == "insufficient_evidence")
            manufacturer_filter += int(all(candidate.get("manufacturer") == item["manufacturer"] for candidate in response["candidates"]) or expected is None)
            if item.get("equipment_model"):
                model_filter += int(any(item["equipment_model"] in candidate.get("compatible_equipment_models", []) for candidate in response["candidates"]) or has_contradiction)
            unsupported_confirmation += int(all(candidate["verification_status"] != "verified_match" for candidate in response["candidates"]))
            category = item["category"]
            bucket = by_category.setdefault(category, {"cases": 0, "top_1_hits": 0, "top_5_hits": 0})
            bucket["cases"] += 1
            bucket["top_1_hits"] += int(rank == 1)
            bucket["top_5_hits"] += int(bool(rank and rank <= 5))
            results.append(
                {
                    "case_id": item["case_id"],
                    "category": category,
                    "expected": expected,
                    "rank": rank,
                    "ranked": ranked,
                    "has_contradiction": has_contradiction,
                    "status": response["status"],
                }
            )
    total = len(cases) or 1
    for bucket in by_category.values():
        bucket["top_1_accuracy"] = bucket["top_1_hits"] / bucket["cases"]
        bucket["top_5_accuracy"] = bucket["top_5_hits"] / bucket["cases"]
    print(
        json.dumps(
            {
                "dataset": fixture.get("dataset", {}) if isinstance(fixture, dict) else {},
                "cases": len(cases),
                "top_1_accuracy": top1 / total,
                "top_3_accuracy": top3 / total,
                "top_5_accuracy": top5 / total,
                "mean_reciprocal_rank": reciprocal_rank_sum / total,
                "no_match_correctness": no_match / max(1, sum(1 for case in cases if not case.get("expected_part"))),
                "manufacturer_filter_accuracy": manufacturer_filter / total,
                "model_compatibility_accuracy": model_filter / max(1, sum(1 for case in cases if case.get("equipment_model"))),
                "unsupported_confirmation_rate": unsupported_confirmation / total,
                "confidence_calibration": "not_computed_small_fixture_no_engineer_verified_probability_bins",
                "per_category": by_category,
                "note": "Small non-confidential curated/synthetic fixture; not proof of production accuracy.",
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
