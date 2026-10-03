#!/usr/bin/env python3
"""Lint the Claude Code harness: skills, agents, rules, hooks, and CLAUDE.md.

A computational "sensor" for the harness itself (see the harness-engineering
skill). It enforces the limits Anthropic documents for skills and subagents,
checks that hooks wired in settings.json exist and are executable, and flags
stale, non-portable, or secret-looking content, so drift is caught by a
script instead of by a human reading every file.

Usage:
    python3 .claude/scripts/harness_lint.py            # lint everything
    python3 .claude/scripts/harness_lint.py --strict   # warnings fail too
    python3 .claude/scripts/harness_lint.py --paths .claude/skills/foo
    python3 .claude/scripts/harness_lint.py --json

Exit code 1 when any error is found (or any warning with --strict).
No third-party dependencies: frontmatter is parsed with a small YAML subset.

Suppress a marker warning inside one file with an HTML comment:
    <!-- harness-lint: allow <marker-id>[, <marker-id> ...] -->
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Anthropic-documented limits.
SKILL_NAME_MAX = 64
SKILL_DESC_MAX = 1024
SKILL_DESC_LISTING_MAX = 1536  # description + when_to_use, Claude Code listing cap
SKILL_BODY_MAX_LINES = 500
REFERENCE_TOC_MIN_LINES = 100
AGENT_DESC_WARN_CHARS = 1200
AGENT_DESC_TOTAL_MAX_TOKENS = 15_000
CLAUDE_MD_MAX_LINES = 200
UNSCOPED_RULE_MAX_LINES = 50
CHARS_PER_TOKEN = 4

SKILL_FRONTMATTER_KEYS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}
AGENT_FRONTMATTER_KEYS = {
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "permissionMode",
    "maxTurns",
    "skills",
    "mcpServers",
    "hooks",
    "memory",
    "effort",
    "background",
    "isolation",
    "color",
    "initialPrompt",
    "omitClaudeMd",
    "experimental",
}
RESERVED_NAME_WORDS = ("anthropic", "claude")

# Vendor-managed skills that are overwritten on upgrade: validate frontmatter
# only, skip body, reference, and marker checks. Add directory names here.
THIRD_PARTY_SKILLS: set[str] = set()

# Marker id -> (regex, hint). A hit is a warning; suppress it per file with
# <!-- harness-lint: allow <marker-id> -->.
#
# The defaults keep a public harness portable and free of environment details.
# Add project-specific entries the day something is renamed or retired, e.g.
#     "old-service": (r"\bold-service\b", "merged into new-service; update the reference"),
MARKERS: dict[str, tuple[str, str]] = {
    "local-path": (
        r"(?<![\w.~])/(?:Users|home)/(?!runner/)[A-Za-z0-9._-]+/",
        "machine-specific absolute path; use a repo-relative path or ${CLAUDE_PROJECT_DIR}",
    ),
    "sa-email": (
        r"\b[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com\b",
        "real service-account email; use <SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com",
    ),
    "run-url": (
        r"https?://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.run\.app\b",
        "real Cloud Run URL; use https://<SERVICE>-<HASH>.<REGION>.run.app or resolve it with gcloud",
    ),
}

# Credential shapes. A hit is an error: secrets never belong in the harness.
SECRET_PATTERNS: dict[str, str] = {
    "google-api-key": r"AIza[0-9A-Za-z_\-]{35}",
    "private-key": r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----",
    "sa-key-json": r"\"private_key_id\"\s*:\s*\"[0-9a-f]{20,}\"",
    "github-token": r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    "aws-access-key": r"\bAKIA[0-9A-Z]{16}\b",
    "anthropic-key": r"\bsk-ant-[A-Za-z0-9_\-]{20,}",
    "openai-key": r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}",
    "slack-token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
}

FIRST_PERSON = re.compile(
    r"^\s*(I can|I will|I help|You can use|Use me)\b", re.IGNORECASE
)
WHEN_TO_USE = re.compile(r"\b(use when|use for|use this|use it|trigger)", re.IGNORECASE)
XML_TAG = re.compile(r"<[A-Za-z/][^>]*>")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
ALLOW_COMMENT = re.compile(r"<!--\s*harness-lint:\s*allow\s+([\w,\s-]+?)\s*-->")
HOOK_SCRIPT = re.compile(r"\.claude/hooks/[\w./-]+")


@dataclass
class Finding:
    level: str  # "error" | "warning"
    code: str
    file: str
    message: str

    def render(self) -> str:
        return f"{self.level.upper():7} {self.code} {self.file}: {self.message}"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def error(self, code: str, file: Path, message: str) -> None:
        self.findings.append(Finding("error", code, str(file), message))

    def warn(self, code: str, file: Path, message: str) -> None:
        self.findings.append(Finding("warning", code, str(file), message))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]


def _unescape_double_quoted(value: str) -> str:
    escapes = {"n": "\n", "t": "\t"}
    return re.sub(
        r"\\([\"\\/nt])", lambda m: escapes.get(m.group(1), m.group(1)), value
    )


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, str, int]:
    """Return (frontmatter, body, body_start_line). frontmatter is None if absent.

    Supports the YAML subset used by skills, agents, and rules: scalars, double
    and single quoted strings, block scalars (> and |), and simple `- item`
    lists (joined with commas). Nested maps are kept as their raw text.
    """
    if not text.startswith("---"):
        return None, text, 1
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None, text, 1
    fm: dict[str, str] = {}
    i = 1
    while i < end:
        line = lines[i]
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in (">", "|", ">-", "|-"):
            buf: list[str] = []
            i += 1
            while i < end and (lines[i].startswith(" ") or lines[i].strip() == ""):
                buf.append(lines[i].strip())
                i += 1
            fm[key] = (
                " ".join(b for b in buf if b) if val.startswith(">") else "\n".join(buf)
            )
            continue
        if val == "":
            items: list[str] = []
            raw: list[str] = []
            i += 1
            while i < end and (lines[i].startswith(" ") or lines[i].strip() == ""):
                raw.append(lines[i])
                lm = re.match(r"^\s*-\s*(.+)$", lines[i])
                if lm:
                    items.append(lm.group(1).strip().strip("\"'"))
                i += 1
            fm[key] = ", ".join(items) if items else "\n".join(raw)
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            inner = val[1:-1]
            val = _unescape_double_quoted(inner) if val[0] == '"' else inner
        fm[key] = val
        i += 1
    body = "\n".join(lines[end + 1 :])
    return fm, body, end + 2


def allowed_markers(text: str) -> set[str]:
    allowed: set[str] = set()
    for m in ALLOW_COMMENT.finditer(text):
        allowed.update(x.strip() for x in m.group(1).split(","))
    return allowed


def check_content(report: Report, file: Path, text: str, marker_code: str) -> None:
    """Secret patterns (errors) and marker patterns (warnings) for one file."""
    for secret_id, pattern in SECRET_PATTERNS.items():
        if re.search(pattern, text):
            report.error(
                "E901",
                file,
                f"looks like a credential ({secret_id}); remove it, rotate it, and use a placeholder",
            )
    allowed = allowed_markers(text)
    for marker_id, (pattern, hint) in MARKERS.items():
        if marker_id in allowed:
            continue
        hits = len(re.findall(pattern, text))
        if hits:
            report.warn(marker_code, file, f"{hits}x marker '{marker_id}': {hint}")


def check_description(report: Report, file: Path, desc: str | None, kind: str) -> None:
    if not desc or not desc.strip():
        report.error(f"E{kind}03", file, "description is missing or empty")
        return
    if len(desc) > SKILL_DESC_MAX:
        report.error(
            f"E{kind}03",
            file,
            f"description is {len(desc)} chars (max {SKILL_DESC_MAX})",
        )
    if XML_TAG.search(desc):
        report.error(f"E{kind}03", file, "description contains XML tags")
    if FIRST_PERSON.match(desc):
        report.warn(f"W{kind}05", file, "description is not in third person")
    if kind == "1" and not WHEN_TO_USE.search(desc):
        report.warn(
            f"W{kind}05", file, "description does not say when to use the skill"
        )


def lint_skill(report: Report, skill_dir: Path, root: Path, readme_text: str) -> None:
    skill_md = skill_dir / "SKILL.md"
    rel = skill_md.relative_to(root)
    if not skill_md.exists():
        report.error("E001", rel, "SKILL.md is missing")
        return
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    fm, body, _ = split_frontmatter(text)
    if fm is None:
        report.error("E001", rel, "no YAML frontmatter (name + description required)")
        fm = {}
    name = fm.get("name")
    if not name:
        report.error("E002", rel, f"name is missing (should be '{skill_dir.name}')")
    else:
        if name != skill_dir.name:
            report.error(
                "E002",
                rel,
                f"name '{name}' does not match directory '{skill_dir.name}'",
            )
        if len(name) > SKILL_NAME_MAX or not re.fullmatch(r"[a-z0-9-]+", name):
            report.error(
                "E002",
                rel,
                "name must be lowercase letters, digits, hyphens, <= 64 chars",
            )
        if any(w in name for w in RESERVED_NAME_WORDS):
            report.error(
                "E002", rel, "name contains a reserved word (anthropic/claude)"
            )
    check_description(report, rel, fm.get("description"), "1")
    listing = (fm.get("description") or "") + (fm.get("when_to_use") or "")
    if len(listing) > SKILL_DESC_LISTING_MAX:
        report.warn(
            "W103",
            rel,
            f"description + when_to_use is {len(listing)} chars; listing truncates at {SKILL_DESC_LISTING_MAX}",
        )
    for key in fm:
        if key not in SKILL_FRONTMATTER_KEYS:
            report.warn(
                "W106", rel, f"unknown frontmatter key '{key}' (ignored by Claude Code)"
            )
    if skill_dir.name in THIRD_PARTY_SKILLS:
        return
    body_lines = len(body.splitlines())
    if body_lines > SKILL_BODY_MAX_LINES:
        report.warn(
            "W101",
            rel,
            f"body is {body_lines} lines (guideline: <= {SKILL_BODY_MAX_LINES}); move detail to reference files",
        )
    check_content(report, rel, text, "W104")
    # Reference files: one level deep, TOC when long.
    for ref in sorted(skill_dir.rglob("*.md")):
        if ref == skill_md:
            continue
        rrel = ref.relative_to(root)
        rtext = ref.read_text(encoding="utf-8", errors="replace")
        rlines = len(rtext.splitlines())
        if rlines > REFERENCE_TOC_MIN_LINES and not re.search(
            r"^##?\s*(contents|table of contents)", rtext, re.I | re.M
        ):
            report.warn(
                "W107",
                rrel,
                f"reference file has {rlines} lines but no '## Contents' table of contents",
            )
        for link in MD_LINK.findall(rtext):
            if (
                link.endswith(".md")
                and not link.startswith(("http", "/"))
                and "SKILL.md" not in link
            ):
                target = (ref.parent / link).resolve()
                if target.exists() and target != skill_md.resolve():
                    report.warn(
                        "W102",
                        rrel,
                        f"links to another reference file ({link}); keep references one level deep from SKILL.md",
                    )
        check_content(report, rrel, rtext, "W104")
    # Relative links from SKILL.md must resolve.
    for link in MD_LINK.findall(body):
        if link.startswith(("http", "mailto:", "#")) or "$" in link or "<" in link:
            continue
        if not (skill_dir / link).exists() and not (root / link).exists():
            report.warn("W108", rel, f"link target does not exist: {link}")
    if readme_text and f"`{skill_dir.name}`" not in readme_text:
        report.warn("W109", rel, "skill is not listed in .claude/skills/README.md")


def lint_agent(
    report: Report, agent_md: Path, root: Path, skill_names: set[str]
) -> int:
    rel = agent_md.relative_to(root)
    text = agent_md.read_text(encoding="utf-8", errors="replace")
    fm, body, _ = split_frontmatter(text)
    if fm is None:
        report.error("E201", rel, "no YAML frontmatter (name + description required)")
        return 0
    name = fm.get("name")
    if not name:
        report.error("E201", rel, "name is missing")
    elif name != agent_md.stem:
        report.error(
            "E201", rel, f"name '{name}' does not match filename '{agent_md.stem}'"
        )
    desc = fm.get("description") or ""
    check_description(report, rel, desc, "2")
    if "\\n" in desc:
        report.warn(
            "W203",
            rel,
            "description contains a literal backslash-n (double-escaped newline)",
        )
    if len(desc) > AGENT_DESC_WARN_CHARS:
        report.warn(
            "W202",
            rel,
            f"description is {len(desc)} chars; it loads into every session, move detail into the body",
        )
    for key in fm:
        if key not in AGENT_FRONTMATTER_KEYS:
            report.warn("W204", rel, f"unknown frontmatter key '{key}'")
    if (
        "# Persistent Agent Memory" in body
        or "Your MEMORY.md is currently empty" in body
    ):
        report.warn(
            "W205",
            rel,
            "embeds the auto-injected Persistent Agent Memory boilerplate; delete it "
            "(Claude Code adds it when memory: is set)",
        )
    for skill in [s.strip() for s in (fm.get("skills") or "").split(",") if s.strip()]:
        if skill not in skill_names:
            report.error("E206", rel, f"preloads unknown skill '{skill}'")
    check_content(report, rel, text, "W207")
    return len(desc)


def lint_rules(
    report: Report, rules_dir: Path, root: Path, only: list[Path] | None
) -> None:
    for rule in sorted(rules_dir.rglob("*.md")):
        if only and not _selected(rule, only):
            continue
        rel = rule.relative_to(root)
        text = rule.read_text(encoding="utf-8", errors="replace")
        fm, body, _ = split_frontmatter(text)
        if fm is None or not fm.get("paths"):
            if len(body.splitlines()) > UNSCOPED_RULE_MAX_LINES:
                report.warn(
                    "W301",
                    rel,
                    f"unscoped rule over {UNSCOPED_RULE_MAX_LINES} lines loads into every session; "
                    "add a paths: scope or move it to a skill",
                )
        check_content(report, rel, text, "W304")


def lint_claude_md(report: Report, root: Path) -> None:
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return
    text = claude_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > CLAUDE_MD_MAX_LINES:
        report.warn(
            "W302",
            Path("CLAUDE.md"),
            f"{len(lines)} lines; target under {CLAUDE_MD_MAX_LINES} (move detail to skills or .claude/rules/)",
        )
    check_content(report, Path("CLAUDE.md"), text, "W303")


def lint_readme(report: Report, skill_names: set[str], readme_text: str) -> None:
    if not readme_text:
        return
    listed = set(re.findall(r"\(`([a-z0-9-]+)`\)", readme_text))
    for phantom in sorted(listed - skill_names):
        report.warn(
            "W110",
            Path(".claude/skills/README.md"),
            f"lists skill '{phantom}' which does not exist",
        )


def _hook_commands(node: object) -> list[str]:
    """Collect every hook `command` string from a settings.json structure."""
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "command" and isinstance(node.get("command"), str):
            found.append(node["command"])
        for value in node.values():
            found.extend(_hook_commands(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_hook_commands(value))
    return found


def lint_settings(report: Report, root: Path) -> None:
    """Hooks wired in .claude/settings.json must exist and be executable."""
    settings = root / ".claude" / "settings.json"
    if not settings.exists():
        return
    rel = settings.relative_to(root)
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.error("E401", rel, f"invalid JSON: {exc}")
        return
    for command in _hook_commands(data.get("hooks", {})):
        for script in HOOK_SCRIPT.findall(command):
            path = root / script
            if not path.exists():
                report.error("E402", rel, f"hook script does not exist: {script}")
            elif not os.access(path, os.X_OK):
                report.error(
                    "E403", rel, f"hook script is not executable: {script} (chmod +x)"
                )
    check_content(report, rel, settings.read_text(encoding="utf-8"), "W404")


def _selected(path: Path, only: list[Path]) -> bool:
    return any(path == o or o in path.parents or path in o.parents for o in only)


def run(root: Path, only: list[Path] | None) -> Report:
    report = Report()
    claude_dir = root / ".claude"
    skills_dir = claude_dir / "skills"
    agents_dir = claude_dir / "agents"
    rules_dir = claude_dir / "rules"
    hooks_dir = claude_dir / "hooks"
    settings = claude_dir / "settings.json"
    readme = skills_dir / "README.md"
    readme_text = (
        readme.read_text(encoding="utf-8", errors="replace") if readme.exists() else ""
    )
    skill_dirs = (
        sorted(p for p in skills_dir.iterdir() if p.is_dir())
        if skills_dir.exists()
        else []
    )
    skill_names = {p.name for p in skill_dirs}

    def selected(path: Path) -> bool:
        return not only or _selected(path, only)

    for sd in skill_dirs:
        if selected(sd):
            lint_skill(report, sd, root, readme_text)
    total_desc = 0
    if agents_dir.exists():
        for am in sorted(agents_dir.glob("*.md")):
            if selected(am):
                total_desc += lint_agent(report, am, root, skill_names)
    if not only and total_desc // CHARS_PER_TOKEN > AGENT_DESC_TOTAL_MAX_TOKENS:
        report.error(
            "E208",
            Path(".claude/agents"),
            f"combined agent descriptions ~{total_desc // CHARS_PER_TOKEN} tokens "
            f"(limit {AGENT_DESC_TOTAL_MAX_TOKENS})",
        )
    if rules_dir.exists() and selected(rules_dir):
        lint_rules(report, rules_dir, root, only)
    if selected(root / "CLAUDE.md"):
        lint_claude_md(report, root)
    if selected(readme):
        lint_readme(report, skill_names, readme_text)
    if selected(settings) or (only and selected(hooks_dir)):
        lint_settings(report, root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)"
    )
    parser.add_argument(
        "--paths", nargs="*", type=Path, help="limit to these files/dirs"
    )
    parser.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / ".claude").is_dir():
        print(
            f"harness-lint: no .claude/ directory under {root}; pass --root <repo root>",
            file=sys.stderr,
        )
        return 2
    only = (
        [(p if p.is_absolute() else root / p).resolve() for p in args.paths]
        if args.paths
        else None
    )
    report = run(root, only)
    if args.json:
        print(json.dumps([f.__dict__ for f in report.findings], indent=1))
    else:
        for f in sorted(
            report.findings, key=lambda x: (x.level != "error", x.file, x.code)
        ):
            print(f.render())
        print(
            f"\nharness-lint: {len(report.errors)} error(s), {len(report.warnings)} warning(s)"
        )
    failed = bool(report.errors) or (args.strict and bool(report.warnings))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
