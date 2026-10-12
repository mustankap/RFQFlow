# PRISM integration and sponsor verification

Choose **Custom orchestration** during onboarding. This application uses plain
Python/FastAPI, direct HTTP calls to Nicrron, and manual PRISM instrumentation.
There is no LangChain, LangGraph, OpenAI SDK, or autonomous agent loop in D2.

Official reference: https://blockconvey.com/docs

## Configure and verify real tracing

Place these in the gitignored `.env`:

```dotenv
PRISMTRACE_HOST=https://prism.blockconvey.com
PRISMTRACE_API_KEY=your-project-key
PRISMTRACE_PROJECT_ID=your-project-uuid
```

Run `python -m backend.app.retrieval query --as-of 2026-10-10`. Each actual Nicrron
embedding exchange is submitted to the documented `POST /api/traces` endpoint
with `X-PRISMtrace-Key` authentication. Run trajectories use the installed SDK's
`PRISMtrace.submit_trajectory`. Both share one session ID and
`agent_name=agent_id= rudco-rfq-phase1`.

Inspect `.local/traces/<session-id>.json` for `prism_status` and returned trace IDs.
Delivery failure is surfaced as a warning and never changes retrieval evidence.
No credentials or raw embedding vectors are written. Input descriptions and
retrieved evidence ARE included in local/remote traces; use authorized data.
HTTP delivery is synchronous and bounded by timeouts for this demo. A production
server should dispatch telemetry off the request path.

Missing credentials mean `not_configured`, not successful integration. A unit test
using mocked transport only proves the request contract, not live delivery.

## Knowledge Base reference export

```bash
python -m backend.app.retrieval export-grounding
```

This writes `.local/prism/catalog-grounding.txt`, containing canonical source IDs,
row references, material/grade/form, and synthetic labels. Add that file to the
project's PRISM Knowledge Base using the documented dashboard workflow. Ground a
supported statement such as “DEMO-SS304-060 has grade 304” against the synthetic
catalog. Also evaluate the unsupported statement “DEMO-SS304-060 has a verified
MTR.” Retain the observed result/trace/document IDs for the event demonstration.
Exporting a document does not prove that PRISM uploaded, retrieved or grounded it.

## Evaluator and Guardrail handoff

Use the actual query outputs in `.local/traces/` and the labeled cases in
`backend/data/fixtures/retrieval/evaluation_cases.json` to configure a PRISM
Evaluator for evidence provenance and candidate labeling. Evaluate an actual run,
including a wrong-grade candidate and missing MTR case. Keep the evaluator run ID
and observed outcome. Local Recall@k results do not substitute for this action.

Configure the shared project's prompt-injection Guardrail and coordinate with
Developer 1 to run a real adversarial RFQ through ingestion. D2 embeds normalized
structured requirements and never executes RFQ instructions. That isolation is
not a claim that PRISM blocked a request: HTTP/SDK trace processing is observational.
Only a documented inline enforcement path can claim prevention.

These dashboard actions require the project's account/access and are not silently
performed through guessed endpoints. The retrieval code does not report a
successful PRISM evaluator, Guardrail, or Knowledge Base result until one exists.

## Observed live verification — October 10, 2026

A real three-line RFQ retrieval run delivered three Nicrron embedding traces and
its retrieval trajectory. PRISM setup-doctor returned `overall: connected`,
`live_connected: true`, `app_trace_count: 3`, and `blocked_step: null`. All five
stages were complete, including trace normalization and analysis. The application
returned all three lines with status `ok` and no PRISM delivery warnings.

Sanitized receipt: [prism-verification.json](prism-verification.json). Credentials
and account credential metadata are excluded. This verifies ingestion and
automatic analysis; it does not claim completion of the separate Evaluators Hub,
Guardrail, or Knowledge Base demonstrations described above.
