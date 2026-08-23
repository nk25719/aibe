import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image

from app.schemas.api import ImageMatchResponse
from app.security import require_admin
from app.services.image_index import embed_pil, image_index, read_validated_image_upload

router = APIRouter()


@router.post("/match-image", response_model=ImageMatchResponse)
async def match_image(file: UploadFile = File(...), top_k: int = Query(5, ge=1, le=50)):
    if image_index.M is None or image_index.M.shape[0] == 0:
        raise HTTPException(503, "Image index missing or empty. Generate embeddings first.")
    raw = await read_validated_image_upload(file)
    img = Image.open(io.BytesIO(raw))
    q = embed_pil(img)
    matches = image_index.topk(q, top_k)
    return {"ok": True, "matches": matches, "status": "candidate"}


@router.post("/reload", dependencies=[Depends(require_admin)])
def api_reload():
    image_index.reload()
    return {"ok": True, "image_index": image_index.status()}
