# Model Landscape: Providers, Access Paths, Where to Verify

## Contents
- How to use this file
- Providers and families
- Where to verify (models, pricing, lifecycle)
- Model ID formats differ by platform
- Model lifecycle
- Free tiers and credits
- Hosted open-weight inference
- Self-hosting
- Comparison sources
- Capability checklist for a candidate model

## How to use this file

This file names the model families and where their current facts live. It holds no prices and no current model list on purpose. Open the linked pages, copy the exact ID and price into your decision record with the date checked, and treat anything written here as a pointer, not a fact. **Verify current IDs before use.**

## Providers and families

| Provider | Families and tiers | Access from this stack | Notes |
|----------|-------------------|------------------------|-------|
| Google Gemini | Pro (frontier), Flash (mid), Flash-Lite (small), plus Live, TTS, image and embedding variants | **Vertex AI via ADC** (default); Gemini Developer API with an API key for quick prototypes | Vertex AI keeps traffic under IAM, Cloud billing and Google Cloud data terms |
| Anthropic Claude | Opus (frontier), Sonnet (mid), Haiku (small) | Vertex AI Model Garden via ADC (enable the model first and check region availability), or the Anthropic API with a key in Secret Manager | IDs differ between the two paths (see below) |
| OpenAI GPT | Flagship, "mini" and "nano"-style tiers, plus reasoning variants | OpenAI API with a key in Secret Manager, or a cloud-hosted equivalent | Only a separate integration from this stack; budget for a second SDK and terms review |
| Open-weight | Llama, Gemma, Mistral, Qwen, DeepSeek, gpt-oss and others | Vertex AI Model Garden (managed API or a deployed endpoint), hosted inference providers, or self-hosted | Licences differ per model; read them before commercial use |
| Embedding models | Gemini and Vertex AI text embeddings, open-weight sentence-transformers, other providers' embedding APIs | Vertex AI via ADC, or in-process | Dimension and normalisation affect pgvector index design (`ai-ml-engineering`) |

## Where to verify (models, pricing, lifecycle)

| What | Page |
|------|------|
| Gemini on Vertex AI: model list | https://cloud.google.com/vertex-ai/generative-ai/docs/models |
| Gemini on Vertex AI: versions and retirement dates | https://cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions |
| Generative AI on Vertex AI: pricing (Gemini, partner and open models) | https://cloud.google.com/vertex-ai/generative-ai/pricing |
| Vertex AI quotas and dynamic shared quota | https://cloud.google.com/vertex-ai/generative-ai/docs/quotas, https://cloud.google.com/vertex-ai/generative-ai/docs/dynamic-shared-quota |
| Vertex AI context caching | https://cloud.google.com/vertex-ai/generative-ai/docs/context-cache/context-cache-overview |
| Vertex AI batch inference for Gemini | https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-gemini |
| Vertex AI token counting | https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/get-token-count |
| Claude on Vertex AI | https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude |
| Gemini Developer API: models, pricing, terms | https://ai.google.dev/gemini-api/docs/models, https://ai.google.dev/gemini-api/docs/pricing, https://ai.google.dev/gemini-api/terms |
| Anthropic: models, pricing, deprecations | https://docs.anthropic.com/en/docs/about-claude/models/overview, https://docs.claude.com/en/docs/about-claude/pricing, https://docs.claude.com/en/docs/about-claude/model-deprecations |
| OpenAI: models, pricing, deprecations | https://platform.openai.com/docs/models, https://openai.com/api/pricing/ (may block scripted fetches; open in a browser), https://platform.openai.com/docs/deprecations |

## Model ID formats differ by platform

The same model can have a different ID on each platform. Copy the ID from the platform you will call, never from another.

| Platform | Typical shape (illustrative) |
|----------|------------------------------|
| Gemini on Vertex AI or the Gemini API | `gemini-<version>-<tier>` for stable models, a `-preview` or dated suffix for previews, `gemini-<tier>-latest` style aliases that move |
| Claude on the Anthropic API | `claude-<tier>-<version>` alias or `claude-<tier>-<version>-<YYYYMMDD>` snapshot |
| Claude on Vertex AI | `claude-<tier>-<version>@<YYYYMMDD>` (an `@` before the snapshot date) |
| Open models on Vertex AI | a publisher-qualified name from the Model Garden card |

Some models are only served from the `global` location on Vertex AI, others only from specific regions. The location is part of the configuration, next to the ID.

## Model lifecycle

- Stages: experimental or preview, then generally available (GA), then deprecated, then retired (calls fail).
- Production uses GA, pinned versions. Previews are for evaluation and can change without notice.
- Track the deprecation pages above. When a model in your config is announced for retirement, open a migration task immediately with the retirement date (`reference/routing-and-fallback.md`, migration checklist).
- An alias that auto-updates silently changes behaviour under you. Pin, and upgrade deliberately behind an eval.

## Free tiers and credits

| Kind | Typical shape | Caveats |
|------|---------------|---------|
| Unpaid quota on a developer API (for example the Gemini Developer API) | Free requests up to low per-minute and per-day caps on some models | Read the terms: unpaid use may let the provider use prompts and responses to improve its products, with human review. Not acceptable for real user data. The Gemini API terms also restrict serving end users in some regions (for example the EEA, Switzerland and the UK) to paid services. |
| New-account credits | A one-off credit on signup | Expires; not a production plan |
| Cloud free-trial credits | Credit usable across a cloud provider's services | Expires; quotas start low |
| Hosted open-weight free tiers | Rate-limited access to popular open models | Limits and model lists change frequently; no SLA |

Use free tiers for spikes, demos with synthetic data, and comparing models. Plan production on paid tiers from the start so data terms, quotas and SLAs are known.

## Hosted open-weight inference

Serverless APIs that run open-weight models, usually priced per token and often OpenAI-API-compatible:

| Service | What it is good for |
|---------|--------------------|
| Vertex AI Model Garden | Open models under the same IAM, billing and region controls as Gemini |
| Groq (https://console.groq.com/docs/models) | Very low-latency inference on custom hardware |
| Together AI (https://docs.together.ai/docs/serverless-models) | Broad open-model catalogue, fine-tuning |
| Hugging Face Inference Providers (https://huggingface.co/docs/inference-providers/index) | One API over many providers and Hub models |
| OpenRouter (https://openrouter.ai/models) | One API and key over many providers; handy for side-by-side price and model comparison |
| Fireworks AI, Replicate | Open-model serving, fine-tuning, multimodal models |

Each external provider is a new data processor: check retention and training-use terms, region, and whether a zero-data-retention option exists before sending user data.

## Self-hosting

- **When it pays:** steady, high, predictable volume; strict data control; a fine-tuned model; or a small model that fits cheaply on CPU or a single GPU.
- **When it does not:** spiky or low volume. An idle GPU costs money every hour, and per-token APIs scale to zero for free.
- **Options:** vLLM (high-throughput serving with continuous batching) on GKE or on Cloud Run with GPUs (https://cloud.google.com/run/docs/configuring/services/gpu); Ollama or llama.cpp for local development and small CPU deployments; ONNX Runtime for small encoder models (`ai-ml-engineering`).
- **Break-even:** monthly GPU cost (instances x hours x hourly rate) divided by tokens you can serve per month at realistic utilisation, compared with the per-token API price. Include engineering time for upgrades, autoscaling, monitoring and safety filtering.

## Comparison sources

Use these to build a shortlist, then decide with your own eval:

- LMArena leaderboard (https://lmarena.ai/leaderboard): crowd-sourced pairwise preference rankings.
- Artificial Analysis (https://artificialanalysis.ai/): independent quality, speed and price comparisons across providers.
- OpenRouter model list (https://openrouter.ai/models): side-by-side per-token prices and context lengths.
- Provider model cards and system cards: stated context window, output limits, training cutoff, safety evaluations.

Leaderboards measure general preference, not your task. A model that ranks lower can win on your eval at a fraction of the price.

## Capability checklist for a candidate model

- [ ] Available on the platform and in the region or location you will use
- [ ] Data terms acceptable (retention, training use, residency, zero-data-retention option)
- [ ] Context window and maximum output tokens sufficient at p95
- [ ] Modalities needed (images, audio, PDF, video)
- [ ] Structured output with JSON schema, function calling, parallel tool calls
- [ ] Streaming supported on the path you use
- [ ] Thinking controls (budget or level) and how thinking tokens are billed
- [ ] Prompt caching supported (implicit or explicit) and minimum cacheable prefix size
- [ ] Batch or flex mode available for offline work
- [ ] Safety filter behaviour and configurability
- [ ] Quota you can obtain, and SLA
- [ ] Lifecycle stage (GA or preview) and published retirement date
- [ ] Price checked on the provider page, with the date recorded
