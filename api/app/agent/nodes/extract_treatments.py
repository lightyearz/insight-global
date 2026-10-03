"""extract_treatments: one lite-model call per source (item_key = source.id)."""

from __future__ import annotations

import asyncio
import re

from app.agent import prompts
from app.agent.deps import AgentDeps, NodeResult, one_line
from app.agent.llm_outputs import ExtractTreatmentsOutput, LLMRequest, normalize_for_grounding
from app.agent.state import BriefingState
from app.schemas import Briefing, Condition, Source


def named_in(name: str, *texts: str) -> bool:
    """True if the organisation (or its parenthesised acronym, e.g. 'KDIGO') is named in the source text."""
    haystack = normalize_for_grounding(" ".join(texts)).lower()

    def found(part: str) -> bool:
        candidates = [part, *re.findall(r"\(([^)]+)\)", part), re.sub(r"\s*\([^)]*\)", "", part)]
        return any(len(c.strip()) >= 3 and normalize_for_grounding(c).lower() in haystack for c in candidates)

    # "X and Y" (joint guidelines) is accepted when every body is named.
    return found(name) or all(found(p) for p in re.split(r"\s+and\s+(?:the\s+)?", name) if p.strip())


async def run(deps: AgentDeps, state: BriefingState) -> NodeResult:
    bid = state["briefing_id"]
    condition = Condition.model_validate(state["condition"])
    region = state["region"]
    sources = [Source.model_validate(s) for s in state["sources"]]

    async def one(source: Source) -> tuple[Source, ExtractTreatmentsOutput | None]:
        request = LLMRequest(
            step="extract_treatments",
            system=prompts.EXTRACT_SYSTEM,
            prompt=prompts.extract_prompt(condition.label, region, source),
            item_key=source.id,
            fixture_slug=state.get("fixture_slug"),
        )
        try:
            result = await deps.call_llm(bid, request, ExtractTreatmentsOutput)
        except Exception as exc:
            await deps.events.emit(
                bid,
                "extract_treatments",
                "progress",
                f"{source.id}: skipped ({one_line(exc, 160)})",
                {"source_id": source.id, "treatments": 0, "skipped": True},
            )
            return source, None
        out = result.parsed
        n = len(out.treatments) if out.is_relevant else 0
        await deps.events.emit(
            bid,
            "extract_treatments",
            "progress",
            f"{source.id}: {n} treatment(s)" + ("" if out.is_relevant else " (not relevant)"),
            {"source_id": source.id, "treatments": n},
        )
        return source, out

    results = await asyncio.gather(*(one(s) for s in sources))
    extractions: dict[str, dict] = {}
    for source, out in results:
        if out is None:
            continue
        if not out.is_relevant:
            out = out.model_copy(update={"treatments": []})
        extractions[source.id] = out.model_dump(mode="json")
        if (
            source.issuing_body is None
            and out.issuing_body
            and named_in(out.issuing_body, source.excerpt, source.title)
        ):
            source.issuing_body = out.issuing_body.strip()
        if source.region is None and out.region:
            # Hint only: an injected source could claim any region, and region feeds the conflict policy.
            source.region = out.region
            source.region_inferred = True

    if not extractions:
        raise RuntimeError("Treatment extraction failed for every source")

    n_treat = sum(len(e["treatments"]) for e in extractions.values())
    skipped = len(sources) - len(extractions)

    def patch(b: Briefing) -> None:
        b.sources = sources

    detail = f"{n_treat} treatments from {len(extractions)} of {len(sources)} sources"
    if skipped:
        detail += f" ({skipped} skipped)"
    return NodeResult(
        update={"extractions": extractions, "sources": [s.model_dump(mode="json") for s in sources]},
        message=f"Extracted {detail}",
        detail=detail,
        data={"treatments": n_treat, "sources": len(extractions), "skipped": skipped},
        patch=patch,
    )
