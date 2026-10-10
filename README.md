# RFQFlow / AlloyQuote — Developer 2 retrieval

[phase-prob.md](phase-prob.md) is the final architecture. Developer 2 implements
retrieval capabilities for the agent: **SQLite structured search + Nicrron
embeddings + persistent Chroma semantic search**, returning typed, sourced evidence.
Developer 1 owns ingestion; Developer 3 owns canonical data. The Phase 2/shared
agent makes workflow decisions and calls separate validation/pricing tools.

## Run locally

Python 3.11+; commands run from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp -n .env.example .env
```

Set `NICRRON_API_KEY` in the gitignored `.env`. The runtime exclusively uses
Nicrron's documented `openai/text-embedding-3-small` at
`https://api.nicrron.ai/v1/embeddings`. No local or fake model fallback is enabled.

```bash
# Create a NEW synthetic SQLite database (refuses to overwrite existing files).
python -m backend.app.retrieval seed-demo
# Embed the SQLite catalog. Repeating unchanged indexing makes no model calls.
python -m backend.app.retrieval index
# Query the persisted index and current SQLite evidence.
python -m backend.app.retrieval query --as-of 2026-10-10
# Run the 12 labeled synthetic evaluation cases against real Nicrron embeddings.
python -m backend.app.retrieval evaluate --as-of 2026-10-10 --output .local/evaluation-results.json
# Unit/integration tests use test-only embeddings; no API keys are needed.
python -m pytest backend/tests -q
```

If `.local/demo.sqlite` already exists, skip `seed-demo`. To create another fixture
use `seed-demo --db .local/another-demo.sqlite`; pass that same `--db` to index/query.
`seed` is an alias for `index` for existing users; it now reads SQLite.

`--db` now means a **SQLite file**. `--chroma` means the vector directory.
Defaults are `.local/demo.sqlite` and `.local/chroma-hybrid`. The older starter
`.local/chroma` is left untouched and is no longer used.

## Connect Developer 3's database

```dotenv
RFQ_SQLITE_PATH=/absolute/path/to/developer3.sqlite
RFQ_CHROMA_PATH=/absolute/path/to/chroma-hybrid
```

Run `index` again. The adapter understands the exact table names and core columns
provided by Developer 3: `product_catalog`, `vendor_pricing`, `historical_quotes`.
It opens their file in SQLite **read-only** mode. Optional extended columns and
`source_documents`, `market_benchmarks`, `compliance_documents` enable richer
retrieval. Missing tables/metadata produce explicit warnings. No automatic D3
schema migration or synthetic data insertion occurs.

Each catalog product has a `catalog_id`; multiple vendor offers remain distinct
by `pricing_id`. Prices are serialized as decimal strings. Legacy `REAL` values
are converted with a precision warning; currencies and dates are never guessed.
See [D2 integration contract](docs/developer2-integration.md) for the field mapping.

## Retrieval behavior

1. Accept nested Phase 1 `ParsedRFQ` or simplified flat lines from the final doc/D3.
2. Normalize material vocabulary, preserve unresolved units and missing grades.
3. Build query text from the **current structured specification**, so clarification
   updates do not embed stale original text.
4. Search SQLite using parameterized material/grade/form predicates.
5. Search Chroma, limiting semantic results by material when known.
6. Combine SQL and semantic ranks with reciprocal rank fusion (`1 / (60 + rank)`),
   deduplicate by catalog ID, and return known conflicts separately.
7. Retrieve supplier prices, historical quotes, benchmarks and compliance records
   for primary candidates; preserve record identifiers, sources and dates.

Primary candidates have no **known** specification conflict. They are not approved
matches: missing dimensions, absent standards, certifications and origin requirements
remain visible under `unchecked_requirements`. Dimension comparisons allow numerical
roundoff only (1e-9 inches), not a manufacturing tolerance. Unknown products return
empty results, never invented IDs. Semantic failure returns SQL results with
`status: degraded`; it does not silently switch embedding providers.

Chroma collections are identified by model and canonical catalog content hash.
Partial builds cannot be queried. Changed SQLite catalog contents cause explicit
SQL-only degradation until `index` is run again. Pricing changes are read directly
from SQLite and do not require catalog reindexing. Old vector snapshots remain on
disk; choose a new Chroma directory or remove obsolete local snapshots manually
when no longer needed. This demo loads the small catalog in memory per run; it is
not tuned for millions of products.

## Python functions and HTTP API

```python
from backend.app.retrieval.config import create_service

service = create_service()
evidence = service.retrieve_for_rfq(parsed_rfq)
line_result = service.retrieve_for_line(parsed_line)
candidates = service.search_supplier_catalog(parsed_line)
prices = service.retrieve_supplier_prices("DEMO-SS304-060")
history = service.retrieve_historical_quotes("DEMO-SS304-060", customer_id="CUST-A")
benchmarks = service.retrieve_market_benchmarks("DEMO-SS304-060")
documents = service.retrieve_compliance_evidence("DEMO-SS304-060")
```

Each returns a Pydantic model; call `.model_dump(mode="json")` for JSON-safe values.
Single-evidence methods return an `EvidenceSet` containing their named collection
and warnings. A supplied `customer_id` is an exact scope, never a fallback to other
customers. Without it, historical rows are labeled cross-customer reference only.
Customer identity/authorization must be supplied by the calling application.

```bash
python -m uvicorn backend.app.retrieval.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`. `POST /api/retrieval/rfq` accepts
`{"parsed_rfq": {...}, "top_k": 5}`. `POST /api/retrieval/catalog` accepts
`{"line": {...}, "top_k": 5}`. GET endpoints under
`/api/retrieval/products/{catalog_id}/` expose `prices`, `history`, `benchmarks`,
and `compliance`. Unknown IDs return empty evidence with a warning. Invalid inputs
return 422; unavailable SQLite returns 503. This is a local development API without
authentication; bind to localhost. Developer 1 can mount the exported router in
`backend/app/api/retrieval_routes.py` and adopt the standalone app's error handlers.

## Sponsors and evidence

- **Nicrron:** real runtime embeddings; model identity/dimensions checked; bounded
  retries and timeouts. [Official embedding API](https://nicrron.ai/docs/embeddings).
- **Ninoo Code:** used for actual read-only reviews of this implementation.
  [Official workflow](https://ninoo.ai/docs/). Review transcripts are in gitignored
  `.local/ninoo-review.txt` and `.local/ninoo-hybrid-review.txt` on this workstation.
- **PRISM:** actual embedding events can be sent to `/api/traces`; the installed
  `prismtrace-sdk==0.5.1` submits retrieval trajectories. Set `PRISMTRACE_API_KEY`
  and `PRISMTRACE_PROJECT_ID` to enable delivery. Runs have unique session IDs and
  agent name `rudco-rfq-phase1`. Local trace JSON records delivery status, latency,
  model, token usage and output; no credentials or vectors are logged.

Use **Custom orchestration** in PRISM onboarding. See
[PRISM handoff](docs/prism-handoff.md) for setup, grounding reference export and the
remaining dashboard actions. Local tests and exported references do not substitute
for a real PRISM evaluator run or Knowledge Base grounding result.

## Verified scope

Live Nicrron testing on October 10, 2026: six indexed products; **12/12 labeled
synthetic cases passed**, mean Recall@3 and Recall@5 of 1.0 over the ten cases with
known relevant products. The two no-match cases use empty-result checks and are
excluded from recall averages. These fixtures are deliberately small; this is not
a claim of general retrieval accuracy. [Observed results](docs/evaluation-results.json).

The implementation retrieves evidence and does not generate quotes, approve
compliance, calculate selling prices, or implement the Phase 2 agent loop.
