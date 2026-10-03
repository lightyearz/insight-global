---
name: llm-models-expert
description: "Compares LLM providers and model tiers (Gemini on Vertex AI, Claude, OpenAI GPT, open-weight models on hosted or self-managed inference) on capability, context window, latency, data handling and price; estimates token cost; and designs model routing, cascades, fallbacks and model migrations. Use when choosing or switching a model, estimating or reducing LLM spend, deciding between a cheap and a strong model, checking free-tier, quota or deprecation constraints, or answering which model a feature should use. Never quotes a price or model ID from memory: it re-verifies against the provider's own models and pricing pages first."
---

# LLM Models Expert

How to pick a model, predict what it will cost, and route between models without locking the codebase to one provider. The stack default is Gemini on Vertex AI called through Application Default Credentials (ADC); everything here also applies to other providers.

This skill deliberately contains structure, not a price list. Model names, IDs, prices, context windows, free-tier limits and quotas change every few weeks. **Model IDs in this skill are illustrative: verify current IDs before use.**

## Reference files

Load only what the task needs:

- [reference/model-landscape.md](reference/model-landscape.md) - providers and model families, how to reach each from this stack, where to verify models, prices and deprecations, ID formats per platform, free tiers and their data terms, hosted and self-hosted open-weight options, the capability checklist for comparing candidates.
- [reference/cost-estimation.md](reference/cost-estimation.md) - the cost formula, what counts as input and output, multi-turn growth, a worked example, a Python estimator, measuring real usage from response metadata, billing export and alerts.
- [reference/routing-and-fallback.md](reference/routing-and-fallback.md) - static routing, cascades, availability fallback, what never to fall back on, a Python sketch on the provider-neutral interface, and the model-migration checklist.

## Ground rules

1. **Verify before you write.** Before putting a model ID into config or quoting a price, open the provider's models and pricing pages (listed in `reference/model-landscape.md`) and record the date you checked in the PR or decision record.
2. **Pin stable versions in production.** Preview and experimental models can change behaviour or disappear at short notice. Auto-updating aliases (for example `*-latest`) are for prototypes only.
3. **Stay inside the platform boundary when you can.** Gemini on Vertex AI uses ADC and IAM, with no API key. Several partner and open-weight models (for example Claude, Llama, Mistral) are also offered through Vertex AI Model Garden, which keeps the same IAM, billing, region controls and data terms. Going direct to another provider adds an API key in Secret Manager, a new data-processing agreement and a new egress path. That cost is real but sometimes worth it.
4. **Free tiers are for prototypes with synthetic data.** Some free or unpaid tiers let the provider use prompts and responses to improve its products, and allow human review of them. The Gemini Developer API's unpaid quota is one example. Never send real user data through one, and check the current terms before relying on any free tier.
5. **Decide with an eval, not a leaderboard.** Public rankings are a shortlist. Choose with your own task set (`llm-evaluation`).
6. **Log what was used.** Every call logs model ID, prompt version, input, output, cached and thinking tokens, latency and finish reason, so cost and quality can be traced to a model.
7. **Model choice is configuration.** Model IDs live in `pydantic-settings` or a versioned config file, never as string literals in business code (`ai-ml-engineering`).

## Selection procedure

1. **Is an LLM the right tool?** Rules, regex, a lookup, a small classifier or embedding similarity are cheaper, faster and more predictable for many tasks (`ai-ml-engineering`).
2. **Apply hard constraints first** (pass/fail, not weighted):
   - data handling: retention, training use, region or residency, contractual terms
   - availability in your region and platform; quota you can actually get
   - modalities (text, image, audio, video, PDF)
   - context window and maximum output tokens
   - structured output (JSON schema), function calling, streaming
   - latency: time to first token and p95 total latency for the user-facing path
3. **Build a small eval set** of 50-200 realistic cases with expected outputs or grading rubrics. Run two or three candidates that span tiers (small, mid, frontier).
4. **Choose the cheapest model that clears the quality bar**, then estimate cost at expected and peak volume using p95 token counts, not averages (`reference/cost-estimation.md`).
5. **Configure it:** model ID in settings, timeouts, retry policy, fallback route, output-token cap, thinking budget.
6. **Record the decision:** candidates, eval scores, cost estimate, date checked and the trigger for re-evaluation.
7. **Re-evaluate** when a deprecation notice arrives, a new generation ships, or cost or quality drifts. Keep the eval runnable in CI so this is cheap.

## Model tiers (provider-neutral)

| Tier | Typical names | Good for | Trade-offs |
|------|---------------|----------|------------|
| Small / fast | "lite", "nano", "haiku-class", small open-weight (1-10B) | Classification, extraction, routing, guardrail checks, short rewrites, summarising history | Cheapest and fastest; weaker at multi-step reasoning and long instructions |
| Mid | "flash", "sonnet-class", "mini" | Default for chat, RAG answers, tool calling, most product features | Best price/quality balance for most work |
| Frontier | "pro", "opus-class", flagship | Hard reasoning, complex code, long-horizon agents, LLM-as-judge | Highest price and latency |
| Reasoning modes | Thinking budget or effort setting on many current models | Maths, planning, multi-step tool use | Thinking tokens are billed as output and add latency; use the lowest setting that passes the eval |
| Open-weight | Llama, Gemma, Mistral, Qwen, DeepSeek, gpt-oss and others | Data control, fine-tuning, predictable cost at steady high volume | You own serving, scaling, upgrades and safety filtering |
| Specialised | Embedding, reranker, speech, image models | Retrieval, search, voice, vision | Choose separately; embedding vectors from different models are not interchangeable |

## Starting points by use case

| Use case | Start with | Escalate when | Notes |
|----------|-----------|---------------|-------|
| Intent or topic classification, routing | Non-LLM classifier or small tier | Accuracy below target on the eval | Constrain output to an enum with structured output |
| Extraction to JSON | Small or mid with schema mode | Schema validation failures above threshold | Always validate with Pydantic |
| User-facing chat | Mid tier, streaming | Quality complaints on hard turns | Time to first token matters more than total latency |
| RAG answers with citations | Mid tier | Multi-document synthesis is weak | A long context window does not replace retrieval |
| Long-document summary | Mid tier with large context, or map-reduce with small tier | Quality loss on very long inputs | Watch long-context price thresholds |
| Code generation and review, multi-step agents | Frontier, or mid with thinking | - | Cap iterations and tokens per task (`agentic-ai-resources`) |
| LLM-as-judge | A stronger model, ideally from another family than the one judged | - | Calibrate the judge against human labels (`llm-evaluation`) |
| Input and output guardrail checks | Small, fast model or dedicated classifier | - | See `llm-guardrails` |
| Bulk offline work (backfills, labelling) | Batch API on the cheapest passing model | - | Batch or flex tiers are typically about half price; verify |
| Embeddings for search | Dedicated embedding model | Recall below target | Re-embed everything when you switch models |

## Cost levers (details in `reference/cost-estimation.md`)

- Output tokens usually cost several times more than input tokens. Cap `max_output_tokens` per use case and ask for concise formats.
- Thinking tokens bill as output. Set the thinking budget or level explicitly.
- Multi-turn chat sends the whole history again every turn, so input cost grows roughly with the square of conversation length. Window or summarise history.
- System prompts, tool declarations and retrieved context count as input on every call.
- Prompt caching: put stable content first. Cached input is billed at a fraction of the normal rate. Explicit caches also charge hourly storage.
- Batch and flex tiers are cheaper for non-interactive work. Priority tiers cost more.
- Some models charge a higher rate for all tokens in a request once the prompt passes a size threshold (for example 200K tokens).
- Global and regional endpoints can differ in price, quota and data-residency guarantees.
- Retries, fallbacks and cascades multiply calls. Count them in the estimate.

## Quotas and rate limits

- Gemini on Vertex AI serves many models from dynamic shared quota, so 429 responses can occur below any nominal limit. Retry with bounded, jittered exponential backoff. Buy provisioned throughput only when you need guaranteed capacity.
- Partner and open-weight models on Vertex AI have per-project, per-region, per-model quotas. Request increases well before a launch.
- Free tiers enforce low requests-per-minute and per-day caps and carry no SLA.
- Load-test against the real quota you have, not the documented maximum.

## Related skills

| Need | Skill |
|------|-------|
| Calling the model: client setup, retries, streaming, structured output, prompts | `ai-ml-engineering` |
| Building and running eval sets, comparing models, LLM-as-judge | `llm-evaluation` |
| Input and output filtering, prompt injection | `llm-guardrails` |
| Agent loops, tool use, MCP | `agentic-ai-resources` |
| Cloud budgets, billing export, Cloud Run sizing | `cloud-costs-optimization` |
| Storing a third-party API key in Secret Manager, service-to-service auth | `backend-architect`, `devops-infrastructure` |
