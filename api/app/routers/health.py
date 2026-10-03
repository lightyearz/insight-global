from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import HealthResponse
from app.store import utcnow

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    model, model_lite = settings.model_names
    return HealthResponse(
        llm_provider=settings.llm_provider,
        data_mode=settings.data_mode,
        model=model,
        model_lite=model_lite,
        time=utcnow(),
    )
