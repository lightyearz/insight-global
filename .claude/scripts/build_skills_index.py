#!/usr/bin/env python3
"""Regenerate the generated block of .claude/skills/README.md from frontmatter.

The README's hand-written sections stay as they are; only the text between
<!-- BEGIN GENERATED SKILL INDEX --> and <!-- END GENERATED SKILL INDEX --> is
rewritten. Each skill's one-line summary comes from SUMMARIES below, or, for a
skill not listed there, from the first sentence of its `description`.

Skill directories that git ignores (private, local-only skills kept next to the
published ones) are left out, so regenerating the index in a working copy never
writes their names into the committed README.

Usage:
    python3 .claude/scripts/build_skills_index.py           # rewrite README
    python3 .claude/scripts/build_skills_index.py --check   # exit 1 if stale
    python3 .claude/scripts/build_skills_index.py --print   # print the block only
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# No __pycache__ next to the scripts: compiled files embed absolute local paths.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_lint import split_frontmatter  # noqa: E402

BEGIN = "<!-- BEGIN GENERATED SKILL INDEX -->"
END = "<!-- END GENERATED SKILL INDEX -->"

# Category assignment, in display order. Skills not listed land in "Other";
# names listed here that do not exist are skipped.
CATEGORIES: dict[str, list[str]] = {
    "Application engineering": [
        "python-developer",
        "backend-architect",
        "frontend-developer",
        "ui-ux-designer",
    ],
    "Testing and quality": [
        "testing-qa",
        "backend-test-runner",
        "frontend-test-runner",
    ],
    "AI and LLM engineering": [
        "ai-ml-engineering",
        "llm-models-expert",
        "llm-guardrails",
        "llm-evaluation",
        "agentic-ai-resources",
    ],
    "Cloud and operations": [
        "devops-infrastructure",
        "cloud-run-deploy",
        "cloud-costs-optimization",
    ],
    "Harness and process": [
        "harness-engineering",
        "project-manager",
    ],
}
# Short "use it for" lines shown in the index. A skill missing here falls back
# to the first sentence of its description; add a line when adding a skill.
SUMMARIES: dict[str, str] = {
    "python-developer": "Python 3.12 standards: typing, Pydantic v2, SOLID layering, async correctness, config and secrets, logging, Ruff",
    "backend-architect": "FastAPI service architecture on Cloud Run: boundaries, API conventions, SQLAlchemy and Alembic, service-to-service auth",
    "frontend-developer": "Next.js App Router, React, strict TypeScript, Tailwind; calling private Cloud Run backends; chat and streaming UI",
    "ui-ux-designer": "Token-based design system, component states, WCAG 2.2 AA accessibility, dashboard patterns",
    "testing-qa": "Test strategy and quality gates across backend and front end, CI wiring, coverage targets",
    "backend-test-runner": "Running and writing pytest suites for FastAPI services: fixtures, async tests, isolation, mocking",
    "frontend-test-runner": "Type-check, ESLint, component tests, Playwright E2E, and accessibility scans",
    "ai-ml-engineering": "Gemini on Vertex AI via ADC, prompts, structured output, embeddings and pgvector retrieval",
    "llm-models-expert": "Comparing LLM providers and models on capability, context window, and price; choosing a model",
    "llm-guardrails": "Input and output safety for LLM features: prompt injection, PII, moderation, fail-closed pipelines",
    "llm-evaluation": "Evaluating LLM features: eval sets, LLM-as-judge, regression benchmarks",
    "agentic-ai-resources": "Theory and reading list on agents: the agent loop, design patterns, tool use, MCP, JSON-RPC",
    "devops-infrastructure": "GCP infrastructure reference: Cloud Run, Cloud SQL, Secret Manager, IAM, GitHub Actions with WIF",
    "cloud-run-deploy": "Deploying, verifying, and rolling back Cloud Run services",
    "cloud-costs-optimization": "Analysing GCP spend and right-sizing Cloud Run, builds, and storage",
    "harness-engineering": "Improving this harness: guides vs sensors, context budget, the audit checklist, the lint and hooks",
    "project-manager": "Organising docs, tracking progress, and writing status reports",
}
# Skills kept for reference but no longer extended; tagged in the index.
RETIRED: set[str] = set()

TABLE_HEADER = [
    "| Skill | Use it for |",
    "|---|---|",
]


def git_ignored(paths: list[Path], cwd: Path) -> set[Path]:
    """Return the subset of paths git ignores; empty when git is unavailable."""
    if not paths:
        return set()
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=cwd,
            input="\n".join(str(p) + "/" for p in paths),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()
    if proc.returncode not in (0, 1):  # 128: not a git repo, or git error
        return set()
    return {Path(line.rstrip("/")) for line in proc.stdout.splitlines() if line}


def first_sentence(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    s = m.group(1) if m else text
    s = s.replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 3].rstrip() + "..."


def collect(skills_dir: Path) -> dict[str, tuple[str, int, int]]:
    """Map skill name -> (summary, body lines, number of extra files)."""
    entries: dict[str, tuple[str, int, int]] = {}
    dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    ignored = git_ignored(dirs, skills_dir)
    if ignored:
        print(
            f"skipping {len(ignored)} git-ignored skill dir(s)",
            file=sys.stderr,
        )
    for d in dirs:
        if d in ignored:
            continue
        md = d / "SKILL.md"
        if not md.exists():
            continue
        fm, body, _ = split_frontmatter(
            md.read_text(encoding="utf-8", errors="replace")
        )
        desc = (fm or {}).get("description", "") or "(no description)"
        extra = sum(1 for f in d.rglob("*") if f.is_file()) - 1
        summary = SUMMARIES.get(d.name) or first_sentence(desc)
        entries[d.name] = (summary, len(body.splitlines()), extra)
    return entries


def row(name: str, entry: tuple[str, int, int]) -> str:
    summary, _lines, _extra = entry
    tag = " *(retired, frozen)*" if name in RETIRED else ""
    return f"| `{name}`{tag} | {summary} |"


def build(skills_dir: Path) -> str:
    entries = collect(skills_dir)
    placed: set[str] = set()
    out: list[str] = [
        BEGIN,
        "",
        f"_{len(entries)} skills. Regenerate this block with `.claude/scripts/build_skills_index.py`; "
        "edit frontmatter, not this table._",
        "",
    ]
    for category, names in CATEGORIES.items():
        present = [n for n in names if n in entries]
        if not present:
            continue
        out += [f"### {category}", "", *TABLE_HEADER]
        out += [row(n, entries[n]) for n in present]
        out.append("")
        placed.update(present)
    rest = sorted(set(entries) - placed)
    if rest:
        out += ["### Other", "", *TABLE_HEADER]
        out += [row(n, entries[n]) for n in rest]
        out.append("")
    out.append(END)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="exit 1 if the README block is stale"
    )
    mode.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="print the block, write nothing",
    )
    args = parser.parse_args(argv)
    skills_dir = args.root.resolve() / ".claude" / "skills"
    if not skills_dir.is_dir():
        print(
            f"no skills directory at {skills_dir}; pass --root <repo root>",
            file=sys.stderr,
        )
        return 2
    dirs = [p for p in skills_dir.iterdir() if p.is_dir()]
    if dirs and len(git_ignored(dirs, skills_dir)) == len(dirs):
        print(
            "every skill dir is git-ignored; un-ignore the published skills "
            "(.gitignore or .git/info/exclude) before building the index",
            file=sys.stderr,
        )
        return 2
    block = build(skills_dir)
    if args.print_only:
        print(block)
        return 0
    readme = skills_dir / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    if BEGIN in text and END in text:
        new = text[: text.index(BEGIN)] + block + text[text.index(END) + len(END) :]
    else:
        new = text.rstrip() + "\n\n## Skill index\n\n" + block + "\n"
    if args.check:
        if new != text:
            print(
                "skills README index is stale; run python3 .claude/scripts/build_skills_index.py"
            )
            return 1
        print("skills README index is up to date")
        return 0
    readme.write_text(new, encoding="utf-8")
    print(f"wrote {readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
