from fastapi import Header, HTTPException, status

from app.config import settings


def require_admin(x_aibe_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Administrative API is disabled until AIBE_API_KEY is configured.",
        )
    if x_aibe_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid administrative API key.")
