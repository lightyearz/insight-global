---
name: agentic-ai-resources
description: "Theory primer and curated, link-checked reading list on AI agents: agent vs workflow, the agent loop, agentic design patterns (ReAct, reflection, tool use, planning, multi-agent), designing tools for agents, JSON-RPC 2.0, the Model Context Protocol (MCP) and its transports, agent harness protocols such as the open-source Codex app-server, stdio vs WebSocket vs SSE, human-in-the-loop control points (approval, interrupt, steer, observe), agent security, and running agent servers on Cloud Run. Use when explaining or designing an agent loop or agent server, answering what JSON-RPC 2.0, MCP or an app-server protocol is, choosing a transport, adding approval or interrupt points, reviewing agent security, or when someone wants a reading set or paper list on agentic AI."
---

# Agentic AI: Theory and Resources

**Domain:** how AI agents work: the loop, the design patterns, the wire protocols (JSON-RPC 2.0, MCP, harness protocols), the transports, the human-in-the-loop control points, and the security model.
**Audience:** anyone designing, building or reviewing an agent, an agent server, or a client for one.
**Links:** the curated library is in [reference/reading-list.md](reference/reading-list.md), with HTTP checks recorded there. Protocol specs here are date-versioned and change; check the current revision before relying on details.

## When to use

- "How does an agent loop work?" / "What is ReAct?" / "Agent or workflow?"
- "What is JSON-RPC 2.0?" / "What is MCP?" / "How does an agent app-server protocol work?"
- "WebSocket, SSE or stdio for an agent?"
- Adding approval, interrupt, steering or observer features
- Designing tools an agent will call, or reviewing an agent for prompt-injection risk
- Hosting an agent server on Cloud Run
- Someone wants a reading list, a NotebookLM source set, or the foundational papers

## How to use this skill

1. Answer from Part 1. It is self-contained theory.
2. Cite 3-6 links from `reference/reading-list.md` that match the question, not the whole list.
3. For a NotebookLM-style source set, hand over the comma-separated list at the top of the reading list.
4. For implementation in this stack, hand off to the skills in Part 2.

---

# PART 1 - THEORY PRIMER

## 1.1 Agent vs workflow

A **workflow** orchestrates LLMs and tools through predefined code paths. An **agent** is a system where the LLM directs its own process: it decides what to do next and which tools to call, and keeps going until it judges the task done. Anthropic's "Building Effective Agents" draws this line most clearly.

The minimal mental model: **an agent is an LLM running tools in a loop.** Planning, reflection, memory and multi-agent setups are elaborations of that loop.

Use an agent only when the task is open-ended and you cannot predict the number of steps. If you can hard-code the steps, a workflow is cheaper, faster and more reliable. Many failed "agents" are workflows that were over-engineered into agents.

## 1.2 The agent loop

```
                 +---------------------------------------------+
                 |                                             |
   user input -> CONTEXT  ->  MODEL  -> decides:               |
   (system        (history,    (LLM)    +- final answer -> emit, wait for next turn
    prompt,        tools,               +- call tool(args)     |
    tools,         memory)                     |               |
    history)                                   v               |
                                          EXECUTE TOOL         |
                                               |               |
                                          OBSERVATION ---------+
                                          (append result to context, loop)
```

One **turn** is one trip through "model decides, maybe acts, observes", repeated until the model emits a final answer or a stop condition fires. Stop conditions: a final message, an iteration or token cap, a budget or time limit, a guardrail block, or a human interrupt (1.8). Always set the caps. An uncapped loop is an unbounded bill.

**ReAct** (Reasoning + Acting, Yao et al. 2022) is the canonical shape of the loop: the model interleaves a *Thought*, an *Action* (tool call) and an *Observation* (tool result) until done. Most tool-calling agents today are ReAct loops, even when the reasoning is hidden inside the model's native function calling or thinking.

```
Thought:     I need the order status. I should call get_order.
Action:      get_order({"id": "A-1029"})
Observation: {"status": "shipped", "eta": "Tue"}
Thought:     I have what I need.
Answer:      Your order shipped and arrives Tuesday.
```

## 1.3 Design patterns

Andrew Ng's four agentic patterns, which describe what you add to the loop:

| Pattern | What it adds | Example |
|---|---|---|
| **Reflection** | The agent critiques and revises its own output, often in a separate critic pass | A code agent reviews its diff before returning it |
| **Tool use** | The model calls external functions (search, code execution, databases, APIs) | The loop in 1.2; the engine of almost every agent |
| **Planning** | Decompose a goal into steps, execute, adapt | Plan-and-Solve, Tree of Thoughts |
| **Multi-agent** | Specialised agents collaborate (orchestrator and workers, debate, roles) | A researcher, a writer and a critic |

Anthropic's companion taxonomy of **workflow** shapes: prompt chaining, routing, parallelisation, orchestrator-workers, and evaluator-optimizer. Pick the simplest shape that solves the task, and move to an autonomous agent only when it cannot.

Multi-agent systems trade tokens for breadth. Parallel sub-agents with isolated contexts can explore more, but they multiply cost and make failures harder to trace. They suit wide, parallelisable research better than tightly coupled tasks such as editing one codebase.

## 1.4 Tool use and tool design

A tool is a typed function the model is told about: a name, a description and a JSON-schema for its parameters. The model emits a structured call, your runtime executes it, and the result goes back into the context as an observation. Foundational papers: MRKL (2022, modular reasoning with routed tools) and Toolformer (2023, a model that learns when to call APIs).

Tools are a user interface for a model. Design them the way you would design an API for a new colleague who reads only the docstring:

- **Fewer, higher-level tools beat thin wrappers over every endpoint.** `schedule_meeting` beats `list_users` + `list_events` + `create_event` when the agent always needs all three.
- **Names and descriptions carry the behaviour.** Say when to use the tool, when not to, and what the parameters mean. Namespace related tools (`orders_get`, `orders_cancel`).
- **Return meaningful, compact results.** Prefer human-readable identifiers to opaque UUIDs, paginate or truncate large results, and say how to get more.
- **Errors should be actionable.** "No order A-1029; IDs look like A-0000. Try orders_search" lets the model recover; a stack trace does not.
- **Validate arguments in the runtime,** never only in the description. The model will eventually send something malformed.
- **Evaluate tools with the agent.** Run realistic tasks, read the transcripts, and fix the tools the agent misuses.

## 1.5 Context and memory

The context window is the agent's working memory and its main bottleneck: every tool result, file and turn competes for it, and quality degrades as it fills. Core techniques are compaction (summarise and restart), structured note-taking outside the context, just-in-time retrieval instead of preloading, and sub-agents whose large intermediate work never enters the orchestrating agent's context. The `harness-engineering` skill covers these levers in depth, including how Claude Code implements them.

## 1.6 JSON-RPC 2.0

**JSON-RPC 2.0 is a lightweight, stateless remote-procedure-call protocol that encodes messages as JSON.** The spec (https://www.jsonrpc.org/specification) fits on one page. It answers one question: how do two programs call each other's functions over a byte stream? LSP, MCP and the Codex app-server all use it, for three reasons.

**a) It is transport-agnostic.** The spec defines message shapes, not how bytes move. The same messages run over stdio pipes, a WebSocket, an HTTP body or a TCP socket.

**b) There are exactly three message types:**

```jsonc
// 1. REQUEST: has an "id", expects exactly one response
{ "jsonrpc": "2.0", "id": 1, "method": "turn/start", "params": { "threadId": "t1", "input": [] } }

// 2. NOTIFICATION: no "id"; fire-and-forget, the receiver must not reply
{ "jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": { "text": "Hel" } }

// 3a. RESPONSE (success): echoes the request "id"
{ "jsonrpc": "2.0", "id": 1, "result": { "turnId": "turn_7", "status": "inProgress" } }

// 3b. RESPONSE (error): "error" instead of "result"
{ "jsonrpc": "2.0", "id": 1, "error": { "code": -32601, "message": "Method not found" } }
```

- `method` is the function name. The `/` in `turn/start` is a naming convention, not syntax.
- `params` is an object (by name) or an array (by position), or omitted.
- The `id` correlates a response with its request. **A notification is a request without an id**, and the receiver must not reply. Streaming agent events (token deltas, status, fan-out to watchers) are notifications; commands that need an answer are requests.

**c) It is bidirectional and symmetric.** Either side may send requests and notifications. This is what makes protocol-level human-in-the-loop possible: the server can send a request to the client ("approve this command?") mid-task and wait for the response.

**Reserved error codes:** `-32700` parse error, `-32600` invalid request, `-32601` method not found, `-32602` invalid params, `-32603` internal error. `-32000` to `-32099` are reserved for implementation-defined server errors. For example, the Codex app-server returns `-32001` "Server overloaded; retry later" when its request queue is full, and clients retry with jittered exponential backoff.

**Batching:** a client may send an array of requests; the server replies with an array of responses.

**A minimal client** (TypeScript, browser WebSocket): pending requests keyed by `id`, notifications dispatched as events, and server-to-client requests answered.

```ts
type Id = number | string;
type RpcError = { code: number; message: string; data?: unknown };
type Message =
  | { jsonrpc: "2.0"; id: Id; method: string; params?: unknown }   // request
  | { jsonrpc: "2.0"; method: string; params?: unknown }           // notification
  | { jsonrpc: "2.0"; id: Id; result: unknown }                    // success response
  | { jsonrpc: "2.0"; id: Id | null; error: RpcError };            // error response

export class JsonRpcClient {
  private nextId = 1;
  private readonly pending = new Map<Id, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();

  constructor(
    private readonly ws: WebSocket,
    private readonly onNotification: (method: string, params: unknown) => void,
    private readonly onServerRequest: (method: string, params: unknown) => Promise<unknown>,
  ) {
    // Production code validates the parsed message (for example with zod) before dispatching.
    ws.addEventListener("message", (event) => void this.dispatch(JSON.parse(String(event.data)) as Message));
  }

  request(method: string, params?: unknown, timeoutMs = 30_000): Promise<unknown> {
    const id = this.nextId++;
    const response = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value); },
        reject: (error) => { clearTimeout(timer); reject(error); },
      });
    });
    this.send({ jsonrpc: "2.0", id, method, params });
    return response;
  }

  notify(method: string, params?: unknown): void {
    this.send({ jsonrpc: "2.0", method, params });
  }

  private async dispatch(message: Message): Promise<void> {
    if ("method" in message) {
      if (!("id" in message)) {
        this.onNotification(message.method, message.params); // never reply to a notification
        return;
      }
      try { // server-to-client request, for example an approval prompt
        const result = await this.onServerRequest(message.method, message.params);
        this.send({ jsonrpc: "2.0", id: message.id, result });
      } catch (error) {
        this.send({ jsonrpc: "2.0", id: message.id, error: { code: -32603, message: String(error) } });
      }
      return;
    }
    if (message.id === null) return; // error about a message the server could not parse; log it
    const waiter = this.pending.get(message.id);
    if (!waiter) return;
    this.pending.delete(message.id);
    if ("error" in message) waiter.reject(new Error(`${message.error.code}: ${message.error.message}`));
    else waiter.resolve(message.result);
  }

  private send(message: Message): void {
    this.ws.send(JSON.stringify(message));
  }
}
```

Also reject every pending request when the socket closes, and reconnect with backoff (1.11).

## 1.7 Transports: stdio, WebSocket, SSE

| Transport | Shape | Direction | Used for |
|---|---|---|---|
| **stdio** (JSONL) | One JSON message per line over stdin and stdout | Bidirectional | A host process spawning the agent or tool server: CLIs, local MCP servers, the Codex app-server default. No network, nothing to authenticate. |
| **WebSocket** (RFC 6455) | One JSON message per text frame, full duplex over one long-lived connection | Bidirectional | Browsers and remote clients that send commands and receive a live event stream on the same connection |
| **SSE** (Server-Sent Events) | `text/event-stream` over plain HTTP | Server to client only | Streaming model tokens; MCP's Streamable HTTP responses. Simpler than WebSocket and proxy-friendly, but client-to-server messages need separate HTTP requests. |

Two streams are easy to confuse: **model provider to your server** is almost always SSE (providers stream tokens that way), while **your server to the browser** can be SSE (simple chat) or WebSocket (when the client must also send mid-turn commands such as steer or interrupt). An agent server often consumes SSE upstream and re-emits WebSocket notifications downstream.

Browser WebSocket gotchas:
- **Browsers always send an `Origin` header on the WebSocket handshake.** Validate it against an explicit allowlist to block cross-site WebSocket hijacking. A policy that rejects every request carrying `Origin` is right for local-only servers and blocks every browser.
- **Browsers cannot set an `Authorization` header on the handshake.** Authenticate with a short-lived, single-use ticket obtained over an authenticated HTTP call (sent in the first message, or in a query parameter you never log), or with a secure same-site cookie.

## 1.8 Human-in-the-loop (HITL)

HITL means inserting a human decision at a control point in the loop. There are five generic points; every product uses some subset.

| Pattern | Where in the loop | Example implementation |
|---|---|---|
| **Approval (before acting)** | Before a tool or action executes | Codex asks the client to approve a shell command or file change, according to its approval policy |
| **Interrupt or cancel** | During an in-flight turn | `turn/interrupt` ends the turn with an "interrupted" status |
| **Steer or inject** | During an in-flight turn, without restarting it | `turn/steer` appends input to the running turn |
| **Observe (read-only)** | Watching the event stream | A supervisor dashboard subscribed to a run's notifications |
| **Review and edit state** | Pause, a human edits the proposed action or memory, resume | LangGraph `interrupt()` with `Command(resume=...)` |

The deepest version is LangGraph's `interrupt()`: the graph persists its full state, waits indefinitely for a human, and resumes exactly where it paused. Approval, editing and free-form input all use the same primitive.

Put checkpoints where a wrong action is costly or irreversible (running code, sending a message, spending money, deleting data, crossing a policy boundary), not on every step. Approval fatigue makes people click "yes" without reading.

Keep **control** (approve, interrupt, steer: the human changes what the agent does) separate from **visibility** (observe: the human only watches). Decide who may see which events independently of who may control the run. Observers often need a redacted view, and that filter belongs on the server, never in the client.

## 1.9 MCP (Model Context Protocol)

**MCP is an open standard for connecting agents to tools, data and prompts**, often described as "USB-C for AI tools". It was introduced by Anthropic in November 2024 and is built on JSON-RPC 2.0. A **host** (the agent application) runs **clients** that connect to **servers**; each server exposes tools, resources and prompts.

**The spec is date-versioned, and revisions change real behaviour.** Check the version your SDK and counterpart implement before relying on any detail below.

- **Standard transports:** stdio (the client launches the server as a subprocess and exchanges newline-delimited JSON-RPC) and **Streamable HTTP** (one HTTP endpoint; each client message is a POST; the server replies with a JSON object or an SSE stream).
- **Transport history:** the original HTTP+SSE transport (2024-11-05) was replaced by Streamable HTTP in 2025-03-26. Any guide describing a separate "MCP SSE transport" is out of date.
- **MCP does not define a WebSocket transport.** It was proposed and not adopted: browsers cannot set auth headers on a WebSocket handshake, and SSE over ordinary HTTP works with existing proxies and tooling. Custom transports are allowed, so a WebSocket binding is buildable but non-standard.
- **Origin validation is mandatory** for Streamable HTTP servers (403 on an invalid `Origin`) to prevent DNS-rebinding attacks. Local servers should bind to 127.0.0.1 only.
- **Revisions up to 2025-11-25** used a stateful model: an `initialize` handshake per connection, an `Mcp-Session-Id` header, a GET endpoint for server-initiated messages, SSE resumability via `Last-Event-ID`, and server-to-client requests such as sampling (the server asks the host's LLM to generate) and elicitation (the server asks the user for input).
- **The 2026-07-28 revision made MCP stateless:** no `initialize` handshake (each request carries its protocol version and capabilities in `_meta`, and servers implement `server/discover`), no protocol-level sessions, no GET stream, and no resumability. Server-initiated requests were replaced by a multi-round-trip pattern: the server returns an `input_required` result listing what it needs, and the client retries the original request with the answers. Roots, Sampling and Logging are deprecated.

The design lesson from that change applies beyond MCP: **server-initiated requests are hard to scale over stateless HTTP.** "Return what you need, let the client retry with it" works through load balancers and serverless platforms without sticky sessions.

## 1.10 Agent harness protocols (the Codex app-server as an example)

MCP exposes tools to an agent. A **harness protocol** drives a whole agent: threads, turns, streaming output, approvals. OpenAI's open-source Codex app-server is a well-documented public example and a good template for your own agent server.

It is both a protocol and a long-lived process hosting agent threads. Internally: a transport reader, a message processor that translates client requests into core operations and core events into a small set of stable, UI-ready notifications, a thread manager, and the core agent loop.

```
initialize (once per connection) -> thread/start (or resume, fork) -> turn/start
                                                                        | server streams notifications:
                                                                        +-> turn/started
                                                                        +-> item/started
                                                                        +-> item/agentMessage/delta  (token chunks)
                                                                        +-> item/completed
                                                                        +-> turn/completed (status, token usage)
   mid-turn control:  turn/steer (append input)   turn/interrupt (cancel)
   server -> client:  approval requests before risky commands or file changes
```

Notes from the upstream docs worth knowing:
- The wire format is JSON-RPC 2.0 style with the `"jsonrpc":"2.0"` field omitted, so a strict JSON-RPC library may reject its messages.
- stdio (JSONL) is the default transport. WebSocket is marked experimental and unsupported upstream; a production browser-facing deployment needs its own authentication, Origin allowlist and backpressure handling.
- Under load it rejects requests with `-32001` rather than queueing without bound.

Compared with MCP: the same JSON-RPC base and request/notification model, but a different job (driving an agent rather than exposing tools) and a different remote transport. An agent server can speak both: a harness protocol to its UI and MCP to its tools. Keep the two protocol surfaces separate in code and in documentation.

## 1.11 Running an agent server on this stack

- **Cloud Run supports WebSockets** as long-running HTTP requests. The request timeout applies (default 5 minutes, up to 60), so clients must reconnect. Session affinity is best effort, so a reconnect can land on another instance. Do not enable end-to-end HTTP/2 for WebSocket services. An instance with any open WebSocket counts as active and is billed. Raise per-instance concurrency for connection-heavy services.
- **Keep run state outside the instance** (Cloud SQL or another shared store) so a reconnecting client can resume a thread from any instance. Give events monotonic sequence numbers so clients can ask for "everything after N".
- **IAM-protected services cannot be called directly from a browser.** Either proxy through a server-side route that attaches an ID token (SSE works well through a Next.js route handler), or expose the agent service with application-level authentication (1.7).
- **Bound everything:** iterations per turn, tokens per turn, wall-clock time per turn, concurrent turns per user, and queue depth per instance.
- Deployment flags, probes and IAM: `cloud-run-deploy` and `devops-infrastructure`. Service boundaries and service-to-service auth: `backend-architect`.

## 1.12 Agent security

- **Every tool result is untrusted input.** Web pages, emails, documents and API responses can carry instructions (indirect prompt injection). The model cannot reliably tell data from instructions.
- **The lethal trifecta** (Simon Willison): an agent that has access to private data, is exposed to untrusted content, and can communicate externally can be tricked into exfiltrating that data. Remove at least one of the three for any agent that handles sensitive data.
- **Least privilege:** give each agent only the tools and scopes its task needs. Prefer read-only tools; put irreversible actions behind approval (1.8).
- **Sandbox code execution** with no ambient credentials, and allowlist network egress.
- **Audit:** log every tool call with its arguments, result size, caller and approval decision.
- Input and output filtering, injection detection and PII handling: `llm-guardrails`.

## 1.13 Evaluating agents

Evaluate both the **outcome** (was the final state correct?) and the **trajectory** (were the tool calls sensible, safe and efficient?). Track cost and step counts per task alongside success rate; an agent that succeeds in forty steps when five would do is a regression. Building eval sets and LLM judges: `llm-evaluation`.

---

# PART 2 - RELATED SKILLS

| For... | Skill |
|---|---|
| Calling Gemini on Vertex AI, structured output, streaming, prompts | `ai-ml-engineering` |
| Which model to run the agent on, and what it will cost | `llm-models-expert` |
| Prompt injection, input and output filtering | `llm-guardrails` |
| Agent and tool evaluation, LLM-as-judge | `llm-evaluation` |
| Context engineering, Claude Code skills, subagents and hooks | `harness-engineering` |
| Chat and agent-activity UI, SSE and WebSocket clients in Next.js | `frontend-developer` |
| Service boundaries, service-to-service auth, data ownership | `backend-architect` |
| Deploying WebSocket or SSE services on Cloud Run | `cloud-run-deploy`, `devops-infrastructure` |
