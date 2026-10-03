# Google Cloud Model Armor (Managed Option)

## Contents

- [What it covers](#what-it-covers)
- [When to choose it](#when-to-choose-it)
- [Setup](#setup)
- [Creating a template](#creating-a-template)
- [Calling the sanitize API from a service](#calling-the-sanitize-api-from-a-service)
- [Interpreting results](#interpreting-results)
- [Vertex AI integration and floor settings](#vertex-ai-integration-and-floor-settings)
- [Enforcement modes and rollout](#enforcement-modes-and-rollout)
- [Limitations to design around](#limitations-to-design-around)
- [Testing](#testing)

Facts below come from the Model Armor documentation and the `google-cloud-modelarmor` Python client (`modelarmor_v1`). The service evolves quickly; re-check the docs for limits, regions and pricing before relying on them.

## What it covers

Model Armor screens prompts and responses against a **template** that configures:

| Filter | Result key | Notes |
|--------|------------|-------|
| Responsible AI: dangerous, harassment, hate speech, sexually explicit | `rai` | confidence threshold per category: `LOW_AND_ABOVE`, `MEDIUM_AND_ABOVE`, `HIGH` |
| Prompt injection and jailbreak | `pi_and_jailbreak` | one confidence threshold |
| Sensitive Data Protection | `sdp` | basic (a small fixed set of infoTypes) or advanced (your own SDP inspect and de-identify templates) |
| Malicious URIs | `malicious_uris` | scans a bounded number of URLs per payload |
| CSAM | `csam` | always on |

It also screens supported document types, within size limits, when called directly through the API.

## When to choose it

| Prefer Model Armor when | Prefer self-hosted detectors when |
|-------------------------|-----------------------------------|
| You do not want to operate or tune detector models | You need custom categories, thresholds or domain-specific recall |
| You want one policy enforced across many apps and projects (floor settings) | Per-request latency must stay in single-digit ms |
| Security teams want centralised logging and dashboards | Inputs are multi-turn or encoded in ways you must normalise first |
| Detecting documents and files is in scope | Cost per token at your volume is too high |

They combine well: cheap in-process checks (normalisation, Presidio, scope) first, Model Armor for the categories it covers, and your own policy decides the action.

## Setup

- Enable the Model Armor API in the project that owns the templates.
- Use the regional endpoint `modelarmor.<REGION>.rep.googleapis.com`; templates are regional, and the request must go to the region where the template exists.
- IAM: callers that sanitize need `roles/modelarmor.user` on the template project; viewing templates needs `roles/modelarmor.viewer`; managing templates is an admin role held by your infrastructure pipeline, not by runtime service accounts.
- Runtime authentication is ADC: the Cloud Run service's own service account, no keys.
- Manage templates as code (Terraform or a reviewed script) so a threshold change is a reviewed diff.

## Creating a template

```python
from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1 as ma


def default_template() -> ma.Template:
    medium = ma.DetectionConfidenceLevel.MEDIUM_AND_ABOVE
    return ma.Template(
        filter_config=ma.FilterConfig(
            rai_settings=ma.RaiFilterSettings(rai_filters=[
                ma.RaiFilterSettings.RaiFilter(filter_type=t, confidence_level=medium)
                for t in (
                    ma.RaiFilterType.DANGEROUS,
                    ma.RaiFilterType.HARASSMENT,
                    ma.RaiFilterType.HATE_SPEECH,
                    ma.RaiFilterType.SEXUALLY_EXPLICIT,
                )
            ]),
            pi_and_jailbreak_filter_settings=ma.PiAndJailbreakFilterSettings(
                filter_enforcement=ma.PiAndJailbreakFilterSettings.PiAndJailbreakFilterEnforcement.ENABLED,
                confidence_level=medium,
            ),
            malicious_uri_filter_settings=ma.MaliciousUriFilterSettings(
                filter_enforcement=ma.MaliciousUriFilterSettings.MaliciousUriFilterEnforcement.ENABLED,
            ),
            sdp_settings=ma.SdpFilterSettings(basic_config=ma.SdpBasicConfig(
                filter_enforcement=ma.SdpBasicConfig.SdpBasicConfigEnforcement.ENABLED,
            )),
        ),
        template_metadata=ma.Template.TemplateMetadata(
            enforcement_type=ma.Template.TemplateMetadata.EnforcementType.INSPECT_ONLY,
            multi_language_detection=ma.Template.TemplateMetadata.MultiLanguageDetection(
                enable_multi_language_detection=True,
            ),
        ),
    )


def create_template(project_id: str, location: str, template_id: str) -> ma.Template:
    client = ma.ModelArmorClient(
        transport="rest",
        client_options=ClientOptions(api_endpoint=f"modelarmor.{location}.rep.googleapis.com"),
    )
    return client.create_template(
        request=ma.CreateTemplateRequest(
            parent=f"projects/{project_id}/locations/{location}",
            template_id=template_id,
            template=default_template(),
        )
    )
```

- Use separate templates for prompts and responses when thresholds differ, and per product surface when policies differ.
- Use advanced SDP configuration (your own inspect and de-identify templates) when you need infoTypes beyond the basic set or non-US identifiers.
- Template metadata can also turn on logging of sanitize operations. Check what those log entries contain before enabling it on traffic with personal data, and set retention and access on the log bucket accordingly.

## Calling the sanitize API from a service

Calling the API yourself means your service, not the integration, decides what happens on an error. The check plugs into the pipeline from `pipeline.md`.

```python
import asyncio
import logging

from google.api_core.client_options import ClientOptions
from google.cloud import modelarmor_v1 as ma

logger = logging.getLogger(__name__)


def matched_filters(result: ma.SanitizationResult) -> list[str]:
    names: list[str] = []
    for name, filter_result in result.filter_results.items():
        which = type(filter_result).pb(filter_result).WhichOneof("filter_result")
        if which is None:
            continue
        inner = getattr(filter_result, which)
        if which == "sdp_filter_result":  # nested: inspect_result or deidentify_result
            sub = type(inner).pb(inner).WhichOneof("result")
            if sub is None:
                continue
            inner = getattr(inner, sub)
        if inner.match_state == ma.FilterMatchState.MATCH_FOUND:
            names.append(name)
    return names


class ModelArmorCheck:
    name = "model_armor"

    def __init__(self, project_id: str, location: str, template_id: str, *,
                 actions: dict[str, Action], failure_mode: FailureMode, timeout_s: float) -> None:
        self._client = ma.ModelArmorClient(
            transport="rest",
            client_options=ClientOptions(api_endpoint=f"modelarmor.{location}.rep.googleapis.com"),
        )
        self._template = f"projects/{project_id}/locations/{location}/templates/{template_id}"
        self._actions = actions  # result key -> Action, from the policy file
        self.failure_mode = failure_mode
        self.timeout_s = timeout_s

    def _sanitize(self, text: str, source: str) -> ma.SanitizationResult:
        item = ma.DataItem(text=text)
        if source == "model_output":
            response = self._client.sanitize_model_response(
                request=ma.SanitizeModelResponseRequest(name=self._template, model_response_data=item),
                timeout=self.timeout_s,
            )
        else:
            response = self._client.sanitize_user_prompt(
                request=ma.SanitizeUserPromptRequest(name=self._template, user_prompt_data=item),
                timeout=self.timeout_s,
            )
        return response.sanitization_result

    async def run(self, text: str, ctx: CheckContext) -> list[Finding]:
        result = await asyncio.to_thread(self._sanitize, text, ctx.source)
        findings = [
            Finding(self.name, f"model_armor.{key}", 1.0, self._actions.get(key, Action.BLOCK))
            for key in matched_filters(result)
        ]
        if result.invocation_result != ma.InvocationResult.SUCCESS:
            # PARTIAL or FAILURE: some filters did not run. Keep real matches, then apply the failure mode.
            logger.error("model armor incomplete", extra={"invocation_result": result.invocation_result.name,
                                                          "request_id": ctx.request_id})
            if self.failure_mode is FailureMode.CLOSED:
                findings.append(Finding(self.name, "check_unavailable", 1.0, Action.BLOCK))
        return findings
```

- Create the client once at startup and reuse it. `ModelArmorAsyncClient` (gRPC) is an alternative to the thread hop.
- Pass the HTTP timeout to the client call as well as the pipeline timeout, so the worker thread ends instead of lingering.
- Retries: a small number with backoff on transient errors (`429`, `503`) only, within the pipeline deadline; Google publishes a recommended retry strategy for Model Armor.
- Whether text sent to Model Armor counts as leaving your trust boundary is a data-governance decision. It runs in your project, but redact first if your policy requires it (the SDP filter needs raw text to detect anything).

## Interpreting results

- `sanitization_result.filter_match_state`: `MATCH_FOUND` if any filter matched.
- `sanitization_result.filter_results`: per-filter results keyed by `rai`, `pi_and_jailbreak`, `sdp`, `malicious_uris`, `csam`. Each has an `execution_state` (`EXECUTION_SUCCESS` or `EXECUTION_SKIPPED`) and a `match_state`; RAI results also carry per-category results.
- `sanitization_result.invocation_result`: `SUCCESS`, `PARTIAL` (some filters skipped or failed) or `FAILURE` (all skipped or failed). A clean `filter_match_state` with `PARTIAL` does **not** mean clean input.
- With advanced SDP and a de-identify template, the de-identified text is returned in the SDP result; use it only if the de-identification matches what your pipeline expects.
- The API returns findings; it does not block anything by itself. Your code decides the action.

## Vertex AI integration and floor settings

- A `generateContent` call can name templates directly: `model_armor_config` with `prompt_template_name` and `response_template_name` (in `google-genai`, `types.GenerateContentConfig(model_armor_config=types.ModelArmorConfig(...))`). A blocked prompt surfaces as `prompt_feedback.block_reason == MODEL_ARMOR` (see `output-validation.md`).
- Floor settings apply a minimum policy to every `generateContent` call in a project, even when the request omits `model_armor_config`; the Vertex AI service agent needs `roles/modelarmor.user`.
- **The integration fails open.** Per the documentation, Vertex AI skips sanitization and continues when Model Armor is unavailable in the region, temporarily unreachable, or errors, so unscreened prompts and responses can occasionally pass. Configuration errors (permissions, quota) are still reported in inspect-and-block mode.
- The integration does not pass SDP de-identified text back to the model; with inspect-and-block it blocks instead. It also does not screen documents or file uploads; call the API directly for those.
- A request routed to a region where the named template does not exist fails with "template not found".

Use the integration as a baseline that is cheap to turn on everywhere, and call the sanitize API from your service on paths that must fail closed.

## Enforcement modes and rollout

- **Inspect only:** findings are logged to Cloud Logging and nothing is blocked. Use it to measure match rates and false positives on real traffic before enforcing.
- **Inspect and block:** violating prompts and responses are stopped (applies to integrations; with the direct API your code enforces).
- Roll out per category: start in inspect-only, compare matches against a labelled sample, set confidence levels per category, then enforce. Keep the before/after numbers (`llm-evaluation`).
- Filter versions change over time; pin the filter version where the product allows it and re-evaluate when it changes.

## Limitations to design around

- Each request is screened on its own, as a single turn; there is no conversation history. Multi-turn attacks need your own conversation-level checks.
- Encoded content (Base64, hex, URL encoding, ciphertext) is not decoded. Normalise and decode suspicious encodings yourself, or treat them as a signal.
- The RAI and prompt-injection filters are tested on a list of major languages and may be weaker elsewhere; multi-language detection must be enabled per request or per template, and some regions have limited multi-language support.
- Token limits apply per filter and differ between buffered and real-time streaming modes (`StreamSanitizeUserPrompt` / `StreamSanitizeModelResponse`); payloads over the limit are partially screened. Check the current system limits.
- File screening has a size limit; larger files are skipped.
- The malicious-URI filter scans a bounded number of URLs per payload.
- Pricing is based on the tokens screened; estimate with `cloud-costs-optimization` and re-verify on the pricing page.

## Testing

- Unit tests use a fake `ModelArmorClient` (or fake `_sanitize`) returning constructed `SanitizationResult` objects: a match per filter, `PARTIAL` with and without matches, `FAILURE`, a timeout, and an exception.
- Assert that a `PARTIAL` result on a fail-closed check blocks, and that a real match is kept even when other filters were skipped.
- Keep one live contract test, marked and run on demand against a staging template, that sends a known injection string and a benign string and asserts the match states.
- Add the live path to the production canary set (`red-teaming.md`) so a broken template, missing IAM binding or regional outage is detected by an alert, not by a user.
