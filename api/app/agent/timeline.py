"""Deterministic timeline assembly for the report (docs/CONTRACT.md section 7.4)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from app.agent.policy import slugify
from app.schemas import DataMode, Source, TimelineEvent, TimelineKind, TreatmentOption, date_precision_of

_KIND_ORDER: dict[TimelineKind, int] = {
    "guideline_published": 0,
    "evidence_published": 1,
    "treatment_milestone": 2,
    "research_conducted": 3,
}


def _truncate(text: str, n: int = 80) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


_ACRONYM_RE = re.compile(r"\(([A-Z][A-Za-z]{1,9})\)")


def short_name(source: Source) -> str:
    """Compact name for chart labels: an acronym in parentheses ('KDIGO'), a known acronym, else a short
    issuing body / publisher name."""
    who = source.issuing_body or ""
    m = _ACRONYM_RE.search(who)
    if m:
        return m.group(1)
    if who:
        initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", who) if w[0].isupper())
        return who if len(who) <= 16 else (initials if 2 <= len(initials) <= 6 else who[:15].rstrip() + "…")
    if source.connector == "medlineplus":
        return "MedlinePlus"
    pub = re.sub(r"\s*\(.*?\)", "", source.publisher).strip() or source.publisher
    return pub if len(pub) <= 16 else pub[:15].rstrip() + "…"


def build_timeline(
    report_sources: Sequence[Source],
    selected_options: Sequence[TreatmentOption],
    all_sources: Sequence[Source],
    data_mode: DataMode,
    research_conducted_at: datetime,
) -> list[TimelineEvent]:
    citing: dict[str, list[str]] = {}
    for opt in selected_options:
        cited = {e.source_id for e in opt.evidence} | {m.source_id for m in opt.milestones}
        for sid in cited:
            citing.setdefault(sid, []).append(opt.id)

    events: list[TimelineEvent] = []
    for s in report_sources:
        if not s.published_at:
            continue
        kind: TimelineKind = "guideline_published" if s.source_type == "clinical_guideline" else "evidence_published"
        who = s.issuing_body or s.publisher
        label = f"{who}: {_truncate(s.title)}"
        option_ids = citing.get(s.id, [])
        events.append(
            TimelineEvent(
                id=f"tl-src-{slugify(s.id)}",
                date=s.published_at,
                date_precision=date_precision_of(s.published_at),
                kind=kind,
                label=label,
                short_label=f"{short_name(s)} {s.published_at[:4]}",
                description=f"{'Guideline' if kind == 'guideline_published' else 'Evidence'} published "
                f"({s.source_type.replace('_', ' ')}, reliability tier {s.reliability_tier}).",
                source_ids=[s.id],
                treatment_option_ids=option_ids,
            )
        )
        if s.updated_at and s.updated_at != s.published_at:
            events.append(
                TimelineEvent(
                    id=f"tl-upd-{slugify(s.id)}",
                    date=s.updated_at,
                    date_precision=date_precision_of(s.updated_at),
                    kind=kind,
                    label=f"{label} (updated)",
                    short_label=f"{short_name(s)} upd. {s.updated_at[:4]}",
                    description=f"Source last updated by {who}.",
                    source_ids=[s.id],
                    treatment_option_ids=option_ids,
                )
            )

    for opt in selected_options:
        n = 0
        for m in opt.milestones:
            if not m.grounded:
                continue
            n += 1
            events.append(
                TimelineEvent(
                    id=f"tl-ms-{opt.id.removeprefix('opt-')}-{n}",
                    date=m.date,
                    date_precision=m.date_precision,
                    kind="treatment_milestone",
                    label=f"{opt.name}: {m.label}",
                    short_label=_truncate(opt.name, 22),
                    description=m.quote,
                    source_ids=[m.source_id],
                    treatment_option_ids=[opt.id],
                )
            )

    events.sort(key=lambda e: (e.date, _KIND_ORDER[e.kind]))

    retrieved = [s.retrieved_at for s in all_sources]
    lo = min(retrieved) if retrieved else research_conducted_at
    hi = max(retrieved) if retrieved else research_conducted_at
    events.append(
        TimelineEvent(
            id="tl-research",
            date=research_conducted_at.date().isoformat(),
            date_precision="day",
            kind="research_conducted",
            label=(
                "Research conducted (evidence snapshot)"
                if data_mode == "live"
                else "Evidence snapshot recorded (replay of an earlier retrieval)"
            ),
            short_label="Research",
            description=(f"{len(all_sources)} sources retrieved ({data_mode}) between {_fmt(lo)} and {_fmt(hi)}"),
            source_ids=[],
            treatment_option_ids=[],
        )
    )
    return events


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
