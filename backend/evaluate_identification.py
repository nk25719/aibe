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
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    top1 = 0
    topk = 0
    results = []
    with SessionLocal() as db:
        for item in cases:
            image_path = Path(__file__).resolve().parent / item["image"]
            with image_path.open("rb") as fh:
                upload = UploadFile(filename=image_path.name, file=fh, headers={"content-type": "image/jpeg"})
                response = await create_identification_case(
                    db,
                    CaseInput(
                        manufacturer=item["manufacturer"],
                        equipment_model=item.get("equipment_model"),
                        description=item.get("description"),
                        visible_markings=item.get("visible_markings"),
                        top_k=5,
                    ),
                    [upload],
                )
            ranked = [candidate["official_part_number"] for candidate in response["candidates"]]
            expected = item["expected_part_number"]
            top1 += int(bool(ranked) and ranked[0] == expected)
            topk += int(expected in ranked)
            results.append({"label": item["label"], "expected": expected, "ranked": ranked})
    print(
        json.dumps(
            {
                "cases": len(cases),
                "top_1": top1 / len(cases),
                "top_k": topk / len(cases),
                "note": "Small non-confidential fixture; not proof of production accuracy.",
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
