from fastapi import APIRouter, Query

from app.schemas.api import SearchResponse
from app.services.legacy_search import search_parts

router = APIRouter()


@router.get("/search", response_model=SearchResponse)
def api_search(
    q: str = Query("", description="query", max_length=200),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    hits = search_parts(q, limit, offset)
    return {"ok": True, "count": len(hits), "limit": limit, "offset": offset, "results": hits}
