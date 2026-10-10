# Developer 2 integration contract

Authority: `phase-prob.md` (final architecture). `phase1.md` supplies detailed
retrieval/provenance requirements where consistent with the final document.

## Inputs from Developer 1

`adapt_rfq()` accepts the nested input illustrated in `phase1.md`, or an RFQ with
flat `items` as shown in `phase-prob.md`. It also accepts one flat D3-style line.
Prefer an RFQ envelope with stable `rfq_id`, `line_id` and source references.
Missing IDs are generated only for a standalone simplified fixture adapter;
production callers should pass stable IDs to preserve continuity across turns.

```json
{
  "rfq_id": "RFQ-001",
  "customer_id": "CUST-A",
  "items": [{
    "line_id": "LINE-001",
    "raw_input": "20 pieces 304 SS sheet 0.060 x 48 x 96 in",
    "material": "SS",
    "grade": "304",
    "form": "sheet",
    "dimensions": "0.060 x 48 x 96 in",
    "quantity": 20,
    "quantity_unit": "pieces",
    "standard": null,
    "requires_mtr": true
  }]
}
```

The supplied `ParsedRFQLine` should allow missing grade/quantity and use
`standard: str | None = None`, not `"ASTM"`. The D2 adapter treats the generic ASTM
label as unresolved even when supplied by that older model. It does not infer
that 16 gauge has an exact decimal equivalent or that `4x8` is in feet.

Flat dimensions support an explicit **thickness × width × length followed by a
shared unit**, such as `1/4 x 48 x 96 in` or `6 x 1200 x 2400 mm`. Unsupported mixed
units and ambiguous strings remain unresolved. Flat numeric `thickness_in`,
`width_in`, `length_in` are accepted as explicitly normalized values. Nested fields
must have status `explicit`, `converted`, or `verified` to be used numerically;
other statuses preserve the raw input and leave equivalence unresolved.

## Read-only SQLite adapter

The adapter uses D3's identifiers and relationships directly:

| Table | Identity | Relationship |
| --- | --- | --- |
| `product_catalog` | `catalog_id` | Canonical product specification; Chroma document ID |
| `vendor_pricing` | `pricing_id` | Many offers per `catalog_id` |
| `historical_quotes` | `quote_id` | `matched_catalog_id` references product |
| `market_benchmarks` (optional) | `benchmark_id` | Material/grade/form scope |
| `compliance_documents` (optional) | `evidence_id` | `catalog_id` references product |
| `source_documents` (optional) | `source_id` | Referenced by evidence records |

Original three-table schemas work without migration. Missing evidence fields are
returned as null plus warnings; `sqlite:<filename>/<table>/<record-id>` is a row
locator, not a fabricated original source. An absent synthetic flag remains
unknown, never automatically real or synthetic. `compliance_flags` and
`compliance_verified` are not treated as certification proof.

Recommended additive columns consumed when present:

- Product: `thickness_in`, `width_in`, `length_in`, `description`, `source_id`,
  `source_date`, `is_synthetic`.
- Vendor price: `currency`, `effective_date`, `expiration_date`, `source_id`,
  `source_date`, `is_synthetic`. Existing `unit_of_measure` is preserved.
- Historical quote: `customer_id`, `quantity`, `currency`, `price_unit`, `source_id`,
  `source_date`, `is_synthetic`. Existing `quote_date` is preserved.
- Source: `source_name`, `source_location`, `effective_date`, `is_synthetic`.

Optional benchmark fields: `benchmark_id`, `material`, `grade`, `form`, `price`,
`currency`, `price_unit`, `benchmark_date`, `size_basis`, `region`, `benchmark_type`,
`source_id`, `source_date`, `is_synthetic`.

Optional compliance fields: `evidence_id`, `catalog_id`, `document_type`,
`document_reference`, `standard`, `country_of_origin`, `lot_or_heat_id`,
`verification_status`, `source_id`, `source_date`, `is_synthetic`.

Use ISO dates (`YYYY-MM-DD`) and decimal strings for new prices. The synthetic D2
schema in `demo.py` shows a working example. It is a separate fixture, not a mandate
to replace D3's database. Retrieval never enables a second canonical product set.

## Output to the agent

`RetrievalEvidence` contains RFQ/run identifiers, embedding model, catalog version
and one `LineEvidence` per input line. A line includes:

- `supplier_candidates`: candidates with no known specification conflicts.
- `conflicting_candidates`: nearby or structured candidates with explicit conflicts.
- `supplier_prices`, `historical_quotes`, `market_benchmarks`, `compliance_evidence`.
- `query_text`, `status`, and warnings, including semantic degradation.

All candidates remain `candidate_only`. Each has `retrieval_methods`, RRF
`rank_score`, optional cosine `semantic_distance`, and unchecked requirements.
Neither rank score nor distance is compatibility confidence. SQL and vector
results are deduplicated by catalog ID, never by supplier name. Vendor offers are
retained individually by pricing ID.

Prices without bounded effective/expiration dates have unknown validity. Expired
and future records remain visible with warnings. Historical quotes older than
90 days are marked stale, using an explicit `--as-of` date or today's New York
date. This is a retrieval display policy, not a price-approval rule. Customer
history is scoped by exact customer ID if supplied. The adapter cannot authorize
a customer; the caller must supply authorized scope. Historical quote quantities
that differ from requested quantities are flagged.

Benchmarks are never declared commercially comparable automatically. A surcharge
is not a finished-product price. A retrieved MTR record is not proof of lot-level
compliance; synthetic document references are not real certificates.

## Integration order

1. D3 supplies its SQLite file and confirms field conventions/provenance.
2. Point `RFQ_SQLITE_PATH` at it and run `index` once.
3. D1 calls `service.retrieve_for_rfq(parsed_rfq)` or mounts the HTTP router.
4. The Phase 2 owner wraps the individual service functions as agent tools.
5. Rerun `index` after catalog changes; pricing updates are immediately visible.

Standalone API error handlers are in `backend/app/retrieval/api.py`; adopt them
when mounting the router in another application. Shared output models currently
live under D2 and can be moved to `app/contracts/` once the team settles ownership.
