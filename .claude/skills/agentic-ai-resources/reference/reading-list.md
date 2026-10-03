# Agentic AI Reading List

## Contents
- How this list was checked
- NotebookLM-ready source list
- 1. Agent loops, patterns, tool design
- 2. JSON-RPC 2.0 and transports
- 3. Model Context Protocol (MCP)
- 4. Agent harness protocols (Codex app-server)
- 5. Frameworks and human-in-the-loop
- 6. Agent security
- 7. Foundational papers

## How this list was checked

Each URL was fetched on 2026-10-03 and returned HTTP 200 with a substantive body, except where a row says otherwise. GitHub links could not be fetched from the checking environment and are marked "not re-checked". Specs (MCP in particular) are date-versioned: when a link names a revision, check whether a newer one exists.

## NotebookLM-ready source list

Paste as one comma-separated block. Every entry here returned HTTP 200 in the check above.

```
https://www.anthropic.com/engineering/building-effective-agents, https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents, https://www.anthropic.com/engineering/writing-tools-for-agents, https://www.anthropic.com/engineering/multi-agent-research-system, https://lilianweng.github.io/posts/2023-06-23-agent/, https://huyenchip.com/2025/01/07/agents.html, https://www.deeplearning.ai/the-batch/how-agents-can-improve-llm-performance, https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-2-reflection, https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use, https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-4-planning, https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-5-multi-agent-collaboration, https://www.promptingguide.ai/research/llm-agents, https://www.promptingguide.ai/techniques/react, https://react-lm.github.io/, https://simonwillison.net/2025/Sep/18/agents/, https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/, https://www.jsonrpc.org/specification, https://en.wikipedia.org/wiki/JSON-RPC, https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API, https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events, https://datatracker.ietf.org/doc/html/rfc6455, https://cloud.google.com/run/docs/triggering/websockets, https://modelcontextprotocol.io/docs/getting-started/intro, https://modelcontextprotocol.io/specification, https://modelcontextprotocol.io/docs/learn/architecture, https://modelcontextprotocol.io/specification/2026-07-28/changelog, https://modelcontextprotocol.io/specification/2025-11-25/basic/transports, https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/, https://www.anthropic.com/news/model-context-protocol, https://developers.openai.com/codex/app-server, https://openai.github.io/openai-agents-python/, https://openai.github.io/openai-agents-python/running_agents/, https://developers.openai.com/api/docs/guides/agents, https://docs.langchain.com/oss/python/langgraph/interrupts, https://www.langchain.com/blog/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt, https://huggingface.co/docs/smolagents/index, https://huggingface.co/docs/smolagents/conceptual_guides/react, https://huggingface.co/learn/agents-course/unit0/introduction, https://google.github.io/adk-docs/, https://a2a-protocol.org/latest/, https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
```

For the papers in section 7, upload the PDFs from arXiv directly (`https://arxiv.org/pdf/<id>`); PDFs ingest more reliably than abstract pages.

## 1. Agent loops, patterns, tool design

| Resource | URL | What it teaches |
|---|---|---|
| Anthropic, Building Effective Agents | https://www.anthropic.com/engineering/building-effective-agents | The reference. Agent vs workflow, the five workflow patterns, when not to use an agent. Start here. |
| Anthropic, Effective Context Engineering | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | Managing the context window that feeds the loop: the practical bottleneck. |
| Anthropic, Writing Effective Tools for Agents | https://www.anthropic.com/engineering/writing-tools-for-agents | Tool design: consolidation, naming, compact responses, actionable errors, evaluating tools with agents. |
| Anthropic, How We Built Our Multi-Agent Research System | https://www.anthropic.com/engineering/multi-agent-research-system | Orchestrator and parallel sub-agents in production: when multi-agent pays off and what it costs in tokens. |
| Lilian Weng, LLM Powered Autonomous Agents | https://lilianweng.github.io/posts/2023-06-23-agent/ | The canonical survey: planning, memory, tool use, with the foundational citations. |
| Chip Huyen, Agents | https://huyenchip.com/2025/01/07/agents.html | A long, rigorous engineer's walk through tools, planning and failure modes. |
| DeepLearning.AI, Agentic Design Patterns part 1 (overview) | https://www.deeplearning.ai/the-batch/how-agents-can-improve-llm-performance | Andrew Ng's four-pattern framing. |
| ...part 2, Reflection | https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-2-reflection | Self-critique and revision. |
| ...part 3, Tool Use | https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-3-tool-use | Function calling as a pattern. |
| ...part 4, Planning | https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-4-planning | Decompose and execute. |
| ...part 5, Multi-agent | https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-5-multi-agent-collaboration | Orchestrator and specialised workers. |
| Prompting Guide, LLM Agents | https://www.promptingguide.ai/research/llm-agents | Compact, well-cited overview of agent components. |
| Prompting Guide, ReAct | https://www.promptingguide.ai/techniques/react | The ReAct pattern with prompt examples. |
| ReAct project page | https://react-lm.github.io/ | The original paper's demo page. |
| Simon Willison, "Agents" | https://simonwillison.net/2025/Sep/18/agents/ | The plain-English "LLM running tools in a loop" definition, with history. |
| 12-Factor Agents (HumanLayer) | https://github.com/humanlayer/12-factor-agents | Production engineering principles for reliable agents. Not re-checked. |
| OpenAI, A Practical Guide to Building Agents (PDF) | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | First-party guide: when to build an agent, orchestration, guardrails. |

## 2. JSON-RPC 2.0 and transports

| Resource | URL | What it teaches |
|---|---|---|
| JSON-RPC 2.0 Specification | https://www.jsonrpc.org/specification | The whole protocol on one page: request, notification, response, error codes, batch. |
| Wikipedia, JSON-RPC | https://en.wikipedia.org/wiki/JSON-RPC | History and version comparison; gentler than the spec. |
| MDN, WebSocket API | https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API | The browser full-duplex transport. |
| MDN, Server-Sent Events | https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events | One-way server push; how LLM token streams arrive. |
| RFC 6455 (WebSocket) | https://datatracker.ietf.org/doc/html/rfc6455 | The authoritative WebSocket spec: handshake, framing, the Origin header. |
| Cloud Run, Using WebSockets | https://cloud.google.com/run/docs/triggering/websockets | Request timeouts, reconnects, session affinity, billing and concurrency for WebSocket services on Cloud Run. |

## 3. Model Context Protocol (MCP)

| Resource | URL | What it teaches |
|---|---|---|
| MCP, Introduction | https://modelcontextprotocol.io/docs/getting-started/intro | What MCP is; the host, client and server model. |
| MCP, Specification (latest) | https://modelcontextprotocol.io/specification | Redirects to the current revision. JSON-RPC 2.0 underneath. |
| MCP, Architecture | https://modelcontextprotocol.io/docs/learn/architecture | The layered architecture: data layer and transport layer. |
| MCP, 2026-07-28 changelog | https://modelcontextprotocol.io/specification/2026-07-28/changelog | The move to a stateless protocol: no initialize handshake or sessions, `server/discover`, multi-round-trip requests instead of server-initiated requests. |
| MCP, Transports (2025-11-25 revision) | https://modelcontextprotocol.io/specification/2025-11-25/basic/transports | The stateful-era transport spec: stdio and Streamable HTTP with session IDs and resumability. Useful for interoperating with older servers. |
| Why MCP dropped SSE for Streamable HTTP | https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/ | The clearest explainer of the 2025-03-26 transport change and why not WebSocket. |
| Anthropic, Introducing MCP | https://www.anthropic.com/news/model-context-protocol | The motivation and the open-standard framing. |

## 4. Agent harness protocols (Codex app-server)

| Resource | URL | What it teaches |
|---|---|---|
| Codex App Server (OpenAI Developers) | https://developers.openai.com/codex/app-server | Protocol guide: initialize, threads, turns, item notifications, steer and interrupt, approvals, transports, backpressure. |
| app-server README (openai/codex) | https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md | Source-of-truth README with message shapes and error codes. Not re-checked. |
| DeepWiki, Codex architecture overview | https://deepwiki.com/openai/codex/1.3-architecture-overview | Generated architecture map of the Codex repository. Rate-limited automated checks (HTTP 429); opens in a browser. |
| OpenAI, Unlocking the Codex Harness | https://openai.com/index/unlocking-the-codex-harness/ | Why OpenAI built the app-server. Blocks scripted fetches; open in a browser. |

## 5. Frameworks and human-in-the-loop

| Resource | URL | What it teaches |
|---|---|---|
| OpenAI Agents SDK | https://openai.github.io/openai-agents-python/ | A small, readable agent framework; the loop in code. |
| ...Running agents | https://openai.github.io/openai-agents-python/running_agents/ | How the run loop, max turns and tool calls work. |
| OpenAI, Building agents (API guide) | https://developers.openai.com/api/docs/guides/agents | First-party guide to the agent loop on the OpenAI API. |
| Google Agent Development Kit (ADK) | https://google.github.io/adk-docs/ | Google's open-source agent framework, with Gemini and Google Cloud deployment paths. |
| Agent2Agent (A2A) protocol | https://a2a-protocol.org/latest/ | An open protocol for agents from different systems to talk to each other; complements MCP (agent to tool). |
| LangGraph, Interrupts | https://docs.langchain.com/oss/python/langgraph/interrupts | The `interrupt()` and `Command(resume=...)` primitive: persisted state, pause and resume. |
| LangChain, Human-in-the-loop with interrupt | https://www.langchain.com/blog/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt | The design rationale behind interrupt-based HITL. |
| smolagents (Hugging Face) | https://huggingface.co/docs/smolagents/index | A tiny code-agent framework: the loop with almost no abstraction. |
| smolagents, ReAct guide | https://huggingface.co/docs/smolagents/conceptual_guides/react | How smolagents implements the ReAct loop. |
| Hugging Face Agents Course | https://huggingface.co/learn/agents-course/unit0/introduction | A free, structured course from first principles. |

## 6. Agent security

| Resource | URL | What it teaches |
|---|---|---|
| Simon Willison, The Lethal Trifecta | https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ | Private data + untrusted content + external communication = exfiltration risk; remove one leg. |
| OpenAI, A Practical Guide to Building Agents (PDF) | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | The guardrails chapter: layered input and output checks, tool risk ratings, human escalation. |

## 7. Foundational papers

| Paper | arXiv | Why it matters |
|---|---|---|
| ReAct: Synergizing Reasoning and Acting (2022) | https://arxiv.org/abs/2210.03629 | Names the reason, act, observe loop. The most cited agent paper. |
| MRKL Systems (2022) | https://arxiv.org/abs/2205.00445 | Modular reasoning with routing to external tools and knowledge. |
| Toolformer (2023) | https://arxiv.org/abs/2302.04761 | A model that teaches itself when to call an API. |
| Reflexion (2023) | https://arxiv.org/abs/2303.11366 | Verbal self-reflection as a feedback loop: the reflection pattern. |
| Plan-and-Solve Prompting (2023) | https://arxiv.org/abs/2305.04091 | The planning pattern in prompt form. |
| Tree of Thoughts (2023) | https://arxiv.org/abs/2305.10601 | Deliberate search over reasoning steps. |
| Generative Agents (2023) | https://arxiv.org/abs/2304.03442 | Memory, reflection and planning in a simulated town. |
| Voyager (2023) | https://arxiv.org/abs/2305.16291 | A lifelong-learning agent with a growing skill library. |
| CoALA: Cognitive Architectures for Language Agents (2023) | https://arxiv.org/abs/2309.02427 | A framework for classifying any language agent by memory, action space and decision loop. |
| A Survey on LLM-based Autonomous Agents (2023) | https://arxiv.org/abs/2308.11432 | Construction, application and evaluation of LLM agents. |
| The Rise and Potential of LLM-Based Agents (2023) | https://arxiv.org/abs/2309.07864 | Survey using the brain, perception and action framing. |
