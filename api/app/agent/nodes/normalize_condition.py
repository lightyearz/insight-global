"""normalize_condition: MeSH lookup (live) or condition.json (replay)."""

from __future__ import annotations

from app.agent.deps import AgentDeps, NodeResult
from app.agent.state import BriefingState
from app.connectors.mesh import normalize_condition as mesh_normalize
from app.schemas import Briefing


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    typed = state["condition_input"]
    slug = state.get("fixture_slug")
    if deps.settings.data_mode == "replay":
        if not slug:
            raise RuntimeError("Replay mode requires a fixture for this condition")
        condition = deps.replay.condition(slug, typed)
        method = "replay_fixture"
    else:
        assert deps.http is not None
        condition, method = await mesh_normalize(deps.http, typed)

    def patch(b: Briefing) -> None:
        b.condition = condition

    mesh = f" (MeSH {condition.mesh_id})" if condition.mesh_id else " (no MeSH match; searching the typed text)"
    return NodeResult(
        update={"condition": condition.model_dump(mode="json"), "normalisation": method},
        message=f"Condition normalised to '{condition.label}'{mesh}",
        detail=f"{condition.label}{mesh}",
        data={"label": condition.label, "mesh_id": condition.mesh_id, "method": method},
        patch=patch,
    )
