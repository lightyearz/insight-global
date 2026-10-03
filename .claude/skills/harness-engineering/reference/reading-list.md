# Harness engineering and context engineering: reading list

All URLs fetched and content-checked on 2026-09-25 unless marked. Entries marked (PDF) are arXiv papers; the PDF is at `https://arxiv.org/pdf/<id>` for NotebookLM or offline reading. Titles marked "title from listing" were taken from the arXiv listing rather than the full text.

## Contents
- First-party guides (Anthropic, OpenAI, Manus)
- The harness-engineering canon (2026)
- Context engineering research
- Agent skills research
- Claude Code documentation (the exact surface)
- Token-cost tooling and benchmarks
- Curated lists
- NotebookLM list

## First-party guides (Anthropic, OpenAI, Manus)

| Source | Why it matters |
|---|---|
| [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Anthropic, 2025) | The attention budget, altitude, just-in-time retrieval, compaction, structured notes, subagent distillation. The spine of Part 2. |
| [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) (Anthropic, 2025) | Initializer + coding agent, feature list JSON, progress file, git as memory, one feature per session, end-to-end self-verification. |
| [Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) (Anthropic, 2025) | Tool design: self-contained, unambiguous, token-efficient; evaluate tools with agents. |
| [Building effective agents](https://www.anthropic.com/research/building-effective-agents) (Anthropic, 2024) | Workflows vs agents; the composable patterns. |
| [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) (Anthropic, 2025) | Why skills exist and how progressive disclosure keeps them cheap. |
| [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) (Anthropic docs) | The rules this repo's lint enforces: 1,024-char descriptions, 500-line bodies, one-level references, TOCs, evaluation-first authoring. |
| [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/) (Lopopolo, OpenAI, Feb 2026; bot-walled for fetch tools, summary: [emilsit.net](https://www.emilsit.net/t/2026/02/openai-harness-engineering/)) | A million lines with zero hand-written code. AGENTS.md as a map not a manual, docs/ as system of record, custom linters with remediation text, garbage collection of slop. |
| [Context engineering for AI agents: lessons from building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) (Manus, 2025) | KV-cache hit rate as the metric (10x price gap), mask don't remove tools, file system as context, recitation, keep failures in context. |

## The harness-engineering canon (2026)

| Source | Why it matters |
|---|---|
| [Harness engineering for coding agent users](https://martinfowler.com/articles/harness-engineering.html) (Bockeler on martinfowler.com, Apr 2026) | The mental model: guides (feedforward) and sensors (feedback), computational vs inferential, maintainability / architecture / behaviour harnesses, keep quality left, harness coherence. |
| [Harness Engineering: Anatomy, Architecture, and Evolution of Coding Agents: A Source-Code Study of Eleven Systems](https://arxiv.org/abs/2609.00006) (Barbaste et al., 2026) (PDF) | Seven canonical subsystems, 29 patterns, 18 recommendations, 90-line minimum viable harness. No frameworks, no vector retrieval, skills beat MCP in adoption. |
| [Harness Engineering for Agentic AI Coding Tools: An Exploratory Study](https://arxiv.org/abs/2602.14690) (Galster et al., 2026) (PDF) | 2,853 repositories: context files dominate, AGENTS.md is the interoperable standard, skills are mostly static text, few use subagents. |
| [An Empirical Study of Harness Design for Coding Agents](https://arxiv.org/abs/2609.20804) (Fan et al., Sep 2026) (PDF) | 176 configurations, four models: rule-based elision before LLM summarisation wins; planning helps weak models, saves cost for strong ones; bash-only beats bespoke tools for strong models. |
| [From Question Answering to Task Completion: A Survey on Agent System and Harness Design](https://arxiv.org/abs/2606.20683) (Guo et al., 2026) (PDF) | Six runtime responsibilities (observation, context, control, action, state, verification) and four paradigms ending in harness engineering. |
| [Building Effective AI Coding Agents for the Terminal: Scaffolding, Harness, Context Engineering, and Lessons Learned](https://arxiv.org/abs/2603.05344) (Bui, 2026) (PDF) | OPENDEV: model routing, planner/executor split, lazy tool discovery, adaptive compaction, event-driven reminders against instruction fade. |
| [MemoHarness: Agent Harnesses That Learn from Experience](https://arxiv.org/abs/2607.14159) (Huang et al., 2026) (PDF) | Dual-layer experience bank (per-case diagnoses + global patterns) editing six harness dimensions; transfers across suites. |
| Agentic Harness Engineering: Observability-Driven Automatic Evolution of Coding-Agent Harnesses ([arXiv 2604.25850](https://arxiv.org/abs/2604.25850)) (PDF, title from listing) | Closing the loop: traces drive harness edits automatically. |
| Loop Engineering: Building Blocks, Adoption, and Impact ([arXiv 2608.21884](https://arxiv.org/abs/2608.21884)) (PDF, title from listing) | What developers actually put in agent loops and what it changes. |
| Natural-Language Agent Harnesses ([arXiv 2603.25723](https://arxiv.org/abs/2603.25723)) (PDF, title from listing) | Harnesses specified in prose rather than code. |

## Context engineering research

| Source | Why it matters |
|---|---|
| [Context Rot: how increasing input tokens impacts LLM performance](https://www.trychroma.com/research/context-rot) (Chroma, 2025) | 18 models; non-uniform degradation with length; distractors and low needle-question similarity make it worse; shuffled haystacks beat structured ones. |
| [A Survey of Context Engineering for Large Language Models](https://arxiv.org/abs/2507.13334) (Mei et al., 2025) (PDF) | 1,400+ papers organised into retrieval/generation, processing, management, and the system implementations (RAG, memory, tool reasoning, multi-agent). |
| [Lost in the Middle](https://arxiv.org/abs/2307.03172) (Liu et al., 2023) (PDF) | The positional effect that recitation and summaries exist to fight. |
| [LLMs Get Lost in Multi-Turn Conversation](https://arxiv.org/abs/2505.06120) (Laban et al., 2025) (PDF) | About 39 percent drop from single-turn to multi-turn; why a fresh session with a better prompt beats repeated corrections. |
| LOCA-bench: Benchmarking Language Agents Under Controllable and Extreme Context Growth ([arXiv 2602.07962](https://arxiv.org/abs/2602.07962)) (PDF, title from listing) | Measures agents as context grows past useful limits. |
| Context Engineering: A Practitioner Methodology for Structured Human-AI Collaboration ([arXiv 2604.04258](https://arxiv.org/abs/2604.04258)) (PDF, title from listing) | A methodology framing for teams. |
| Meta context engineering via agentic skill evolution ([arXiv 2601.21557](https://arxiv.org/abs/2601.21557)) (PDF, title from listing) | Skills as the unit that evolves context. |
| [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793) (Yang et al., 2024) (PDF) | The original argument that the interface (harness) matters as much as the model. |
| [Agent Workflow Memory](https://arxiv.org/abs/2409.07429) (Wang et al., 2024) (PDF) | Inducing reusable workflows from experience; the ancestor of learned skills. |

## Agent skills research

| Source | Why it matters |
|---|---|
| [SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks](https://arxiv.org/abs/2602.12670) (Li et al., 2026) (PDF) | 86 tasks, 7,308 trajectories: curated skills +16.2 points on average, +4.5 in software engineering, 16 of 84 tasks negative; self-generated skills no benefit; two to three focused modules beat comprehensive docs. |
| [Agent Skills for Large Language Models: Architecture, Acquisition, Security, and the Path Forward](https://arxiv.org/abs/2602.12430) (Xu and Yan, 2026) (PDF) | Formalises progressive disclosure; 26.1 percent of community skills contain vulnerabilities; a four-tier trust and lifecycle framework. |
| Dynamic Agent Skills: A Lifecycle Survey and Taxonomy of Evolving Skill Libraries ([arXiv 2607.10113](https://arxiv.org/abs/2607.10113)) (PDF, title from listing) | Skill libraries that grow and prune. |
| Towards a Systems Foundation for Agentic Skills: Architecture, Lifecycle, and Security ([arXiv 2608.29596](https://arxiv.org/abs/2608.29596)) (PDF, title from listing) | Systems view of skill loading, isolation, and trust. |
| SkillsVote: Lifecycle Governance of Agent Skills from Collection, Recommendation to Evolution ([arXiv 2605.18401](https://arxiv.org/abs/2605.18401)) (PDF, title from listing) | Governance of a shared skill pool. |
| [Agent Skills open standard](https://agentskills.io) | The portable SKILL.md format Claude Code and others read. |

## Claude Code documentation (the exact surface)

| Page | Use it for |
|---|---|
| [Skills](https://code.claude.com/docs/en/skills) | Frontmatter fields (`when_to_use`, `paths`, `context: fork`, `allowed-tools`, `hooks`), lazy loading, the 1,536-char listing cap, post-compaction retention. |
| [Subagents](https://code.claude.com/docs/en/sub-agents) | `skills:` preload, `maxTurns`, `memory`, `omitClaudeMd`, `disallowedTools`, the 15,000-token description warning, what a subagent does and does not receive. |
| [Hooks reference](https://code.claude.com/docs/en/hooks) | Every event, matcher semantics, exit code 2, JSON `permissionDecision` / `additionalContext` / `updatedInput`, the `if` field, command / http / mcp_tool / prompt / agent hook types. |
| [How Claude remembers your project](https://code.claude.com/docs/en/memory) | CLAUDE.md hierarchy, `@imports`, `.claude/rules/` with `paths:`, the 200-line target, MEMORY.md limits, HTML comments stripped from context. |
| [Best practices](https://code.claude.com/docs/en/best-practices) | Verification first, explore-plan-code, CLAUDE.md include/exclude table, subagents for investigation, adversarial review, the common failure patterns. |

## Token-cost tooling and benchmarks

| Source | Why it matters |
|---|---|
| [rtk-ai/rtk](https://github.com/rtk-ai/rtk) | What RTK is and how the PreToolUse rewrite works; its own docs admit Read/Grep/Glob bypass it and that token counts are bytes/4 estimates. |
| [rtk Claude Code token savings: a skill trial benchmark](https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/) (JetBrains, Jul 2026) | The paired A/B test: +7.6 percent cost at low effort, flat at high effort, ceiling about 3 percent of input tokens. Why this harness does not adopt output-compression proxies. |

## Curated lists

| Source | Why it matters |
|---|---|
| [ai-boost/awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) | Tools, patterns, evals, memory, MCP, permissions, observability. |
| [RUCAIBox/awesome-agent-harness](https://github.com/RUCAIBox/awesome-agent-harness) | Paper list behind "Agent Systems with Harness Engineering". |
| [Faros: Harness engineering guide](https://www.faros.ai/blog/harness-engineering) | Vendor overview; the five-layer framing (tools, verification, context and memory, guardrails, observability). |

## NotebookLM list

Paste as web sources, then add the arXiv PDFs above (`https://arxiv.org/pdf/<id>`) as uploads:

https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents, https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents, https://www.anthropic.com/engineering/writing-tools-for-agents, https://www.anthropic.com/research/building-effective-agents, https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills, https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices, https://www.emilsit.net/t/2026/02/openai-harness-engineering/, https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus, https://martinfowler.com/articles/harness-engineering.html, https://www.trychroma.com/research/context-rot, https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/, https://code.claude.com/docs/en/skills, https://code.claude.com/docs/en/sub-agents, https://code.claude.com/docs/en/hooks, https://code.claude.com/docs/en/memory, https://code.claude.com/docs/en/best-practices
