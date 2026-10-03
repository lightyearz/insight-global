"""suggest_relevance: AI pre-selection; the human decides at review (selected = suggested initially)."""

from __future__ import annotations

from app.agent import prompts
from app.agent.deps import AgentDeps, NodeResult
from app.agent.llm_outputs import LLMRequest, SuggestRelevanceOutput
from app.agent.state import BriefingState
from app.schemas import Briefing, Condition, TreatmentOption
from app.store import utcnow


def apply_suggestions(options: list[TreatmentOption], output: SuggestRelevanceOutput) -> list[TreatmentOption]:
    by_id = {}
    for s in output.suggestions:
        by_id.setdefault(s.option_id, s)
    for o in options:
        s = by_id.get(o.id)
        o.suggested = bool(s and s.suggested)
        o.suggestion_reason = s.reason if s else "No suggestion returned by model"
        o.selected = o.suggested
    return options


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    options = [TreatmentOption.model_validate(o) for o in state["options"]]
    request = LLMRequest(
        step="suggest_relevance",
        system=prompts.RELEVANCE_SYSTEM,
        prompt=prompts.relevance_prompt(condition.label, state["region"], options),
        fixture_slug=state.get("fixture_slug"),
    )
    result = await deps.call_llm(bid, request, SuggestRelevanceOutput)
    options = apply_suggestions(options, result.parsed)
    n = sum(1 for o in options if o.suggested)

    def patch(b: Briefing) -> None:
        b.treatment_options = options
        b.research_completed_at = utcnow()

    return NodeResult(
        update={"options": [o.model_dump(mode="json") for o in options]},
        message=f"Suggested {n} of {len(options)} options for the report",
        detail=f"{n} of {len(options)} options suggested",
        data={"suggested": n},
        patch=patch,
    )
