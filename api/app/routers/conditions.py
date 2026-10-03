from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.connectors.clinical_tables import suggest_conditions
from app.schemas import ConditionSuggestion, ReplayManifest

router = APIRouter(prefix="/api", tags=["conditions"])


@router.get("/conditions/suggest", response_model=list[ConditionSuggestion])
async def suggest(request: Request, q: Annotated[str, Query(max_length=200)] = "") -> list[ConditionSuggestion]:
    q = q.strip()
    if len(q) < 2:
        return []
    state = request.app.state
    if state.settings.data_mode == "replay":
        return state.replay.suggest(q)
    return await suggest_conditions(state.http, q)


@router.get("/replay/conditions", response_model=list[ReplayManifest])
async def replay_conditions(request: Request) -> list[ReplayManifest]:
    return request.app.state.replay.manifests()
