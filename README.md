# RFQFlow / AlloyQuote

Phase 1 turns RFQs into structured requirements and traceable retrieval evidence.
The master specification is [phase1.md](phase1.md).

This starter lets Developer 2 work independently: a synthetic parsed RFQ stands in
for Developer 1, and a synthetic catalog stands in for Developer 3. Embeddings
use **Nicrron**, and Chroma persists the vectors locally. No local embedding model
or fake embeddings are used by the application.

## Run the retrieval starter

Python 3.11+ is required. Run these commands from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp -n .env.example .env
```

Set `NICRRON_API_KEY` in `.env` locally. Do not commit it. The configured model is
`openai/text-embedding-3-small`, listed in the
[Nicrron embedding documentation](https://nicrron.ai/docs/embeddings).
Account access and credits are still required. Calls use
`https://api.nicrron.ai/v1/embeddings` with a fixed model for both indexing and queries.

```bash
python -m backend.app.retrieval seed
python -m backend.app.retrieval query
python -m pytest backend/tests -q
```

`seed` embeds six fictional catalog products into `.local/chroma`.
`query` reads three fully specified synthetic RFQ lines and searches the existing
index; it does not rebuild it. First seed, then query. Missing keys and failed API
calls stop with a nonzero exit code; they do not activate a fallback provider.
Seeding again synchronizes this demo collection, including removing products no
longer in the supplied catalog. Use a separate `--db` path for other datasets.

```bash
python -m backend.app.retrieval seed --db .local/another-demo --catalog path/to/catalog.json
python -m backend.app.retrieval query --db .local/another-demo --rfq path/to/parsed_rfq.json
```

Results retain line IDs, synthetic flags, source IDs, model identity, and dimension
conflicts. Material, grade, and form use exact metadata filters when supplied.
Distances measure cosine distance (lower is closer), not compatibility confidence.
All results are candidates only. Historical prices and compliance evidence are
empty and explicitly reported as unavailable.

## Replace the temporary inputs

| Temporary component | Replacement |
| --- | --- |
| `backend/data/fixtures/retrieval/parsed_rfq_ideal.json` | Developer 1's `ParsedRFQ`; call `retrieve_for_rfq()` directly |
| `backend/data/fixtures/retrieval/supplier_catalog.json` | Developer 3's SQLite records mapped to `Product` and passed to `build_index()` |
| `backend/app/retrieval/models.py` | Team-approved shared Pydantic contracts |

The fixture loader is the only JSON-catalog adapter. Retrieval accepts records,
not a hardcoded catalog. Chroma is a rebuildable index, not the canonical database.
Changing embedding models requires a fresh `--db` directory and reindexing every
product with that model. Never mix query and catalog embedding models.
The client checks the model identity returned by Nicrron. Index loading verifies
the actual cosine metric, and stored vector dimensions are checked before querying.
Dimension comparisons allow only numerical roundoff (1e-9 inches), not a material
manufacturing tolerance or an approval of compatibility.

Draft models and output fields are local to Developer 2; they are not a declaration
that all three developers have approved the shared contracts. Exact filters assume
upstream normalized vocabulary. This starter is semantic search with metadata
filters, not the full SQLite/semantic hybrid retrieval described in `phase1.md`.

## Ownership

| Owner | Component |
| --- | --- |
| Developer 1 | RFQ ingestion, parsing, ingestion API, application entry point |
| Developer 2 (this starter) | Embeddings, Chroma indexing, retrieval, retrieval API |
| Developer 3 | SQLite, canonical catalog, historical data, data quality |
| Named owner to agree as a team | Shared contracts and sponsor integration |

Continue D2 development on `feature/rag-retrieval`. Agree on contracts before
integrating the three components. No parser, D3 database implementation, agent
loop, pricing decisions, or user interface is included here.

## Ninoo development workflow

Ninoo Code is the sponsor's development assistant; Nicrron is the runtime model
gateway. Follow the [official install guide](https://ninoo.ai/download/), then:

```bash
ninoo login
ninoo -m nicrron/coding "Review backend/app/retrieval and backend/tests against phase1.md Developer 2 responsibilities. Report issues without editing files. Do not read .env or other credentials."
```

Use Ninoo for an actual development/review task and retain its observed result for
the event demonstration. Installing it alone does not demonstrate sponsor use.
The CLI can also authenticate with `NINOO_API_KEY` as documented in
[Ninoo configuration](https://ninoo.ai/docs/).

## Verification and remaining Phase 1 work

Tests use clearly labeled test embeddings and mocked HTTP responses to verify
contracts, Nicrron request handling, persistent Chroma storage, filtering, and
conflicts without spending API credits. They do **not** establish live Nicrron
availability or semantic retrieval accuracy. Run `seed` and `query` with a real key
to verify those separately.

### Observed live verification — October 10, 2026

- Nicrron returned `openai/text-embedding-3-small` vectors with 1,536 dimensions.
- All six synthetic catalog records were persisted in local Chroma.
- A separate query process returned the expected SKU first on all three ideal
  synthetic RFQ lines, with source IDs and candidate-only labels preserved.
- Ninoo Code completed a read-only code review through `nicrron/coding`. Its
  actionable metric, model-consistency, and floating-point findings prompted
  additional validation and regression tests.

These are observations on the bundled fixtures, not a general accuracy claim.
Local query output and the Ninoo review are saved under gitignored `.local/`.

Still required: canonical SQLite integration, full shared evidence models, hybrid
ranking, historical/pricing/compliance retrieval, retrieval evaluation, API routes,
and real PRISM tracing/guardrail/evaluator/Knowledge Base integration.

## RFQ-to-Quote prototype

Local integration adds `POST /api/quote/run` (`{"text":"..."}`) and
`POST /api/quote/clarify` (`rfq_id`, `answers`: line_id/field/value records).
Existing parsing endpoints remain available. Workflow sessions are in memory and
reset on server restart; use one server worker. Clarifications preserve original
text and line IDs. Questions currently use deterministic templates.

All six catalog products have **DEMO DATA** USD per-piece costs in
`backend/data/fixtures/retrieval/demo_prices.json`. Selling price uses a **20%
markup on cost**, rounded to cents using Decimal ROUND_HALF_UP. Totals use rounded
selling prices; additional charges are zero. Freight/tax, availability and delivery
are excluded and not established. This is a synthetic demonstration quotation.
No live benchmarks are loaded: **Market competitiveness not established.**
Requested ASTM/MTR/origin requirements with no supporting records stay UNVERIFIED
and block quote readiness. No certification documents are fabricated.

Using the existing environment and configured Nicrron credentials:

```bash
python -m backend.app.retrieval seed
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
python -m scripts.demo_quote
python -m pytest backend/tests -q
```

The demo submits two explicitly dimensioned catalog products, then submits
`20 pcs 304 SS sheet 16ga 4x8` and answers thickness/width/length with verified
explicit decimal-inch measurements. The answer supplies thickness; the workflow
never derives decimal thickness from gauge. Provider access and a seeded index
are required for the live demo. Automated workflow tests mock extraction and use
clearly labeled test vectors, exercising real Chroma and API orchestration.

Observed integration verification (October 10, 2026): real Nicrron parsing and
embeddings plus Chroma produced two complete lines and a $1,980.00 synthetic quote.
The ambiguous gauge/4x8 request returned three questions and no quote; explicit
buyer thickness/width/length answers resumed to a $2,400.00 synthetic quote.
These are fixture-specific demo observations, not market or extraction-accuracy claims.

## Streamlit demo interface

Install declared dependencies once in the activated environment:

```bash
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

Terminal 1, from the repository root (Nicrron credentials configured server-side):

```bash
source .venv/bin/activate
python -m backend.app.retrieval seed
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2, from the same repository root:

```bash
source .venv/bin/activate
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Open http://127.0.0.1:8501. Load Complete RFQ or Load Ambiguous RFQ, then click
Process RFQ. For the ambiguous sample, answer thickness `0.060 in`, width `48 in`,
and length `96 in`, then Submit Clarifications. Answers remain in the same RFQ
session. Leave answers blank to keep those fields unresolved.

For another backend, set `RFQFLOW_API_URL` in the Streamlit terminal. No model
credentials are needed by Streamlit. Uploads support PDF/XLSX/CSV/EML/TXT: the UI
calls `/api/parse-file`, then passes its complete `ParsedRFQ` to `/api/quote/run`
using `parsed_rfq`. This preserves IDs and source locations without a second model
extraction. `/api/quote/run` accepts exactly one of `text` or `parsed_rfq`.

All prices remain synthetic demo data; missing compliance evidence prevents an
approved quote. Keep one FastAPI worker, because sessions are in memory. Scanned
PDFs, OCR and email attachments remain unsupported.
