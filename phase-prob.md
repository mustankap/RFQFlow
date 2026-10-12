# AlloyQuote — Final AI Agent Architecture
### Track 2: RudCo | RFQ to Quote

For the hackathon submission, we want to demonstrate **an AI agent that receives a messy RFQ, understands the buyer's requirements, searches suppliers, evaluates pricing and compliance, and produces a quotation draft—or asks questions when information is missing.**

The key is that **the agent orchestrates the workflow**. Your three developers build the capabilities that the agent uses.

## 1. Complete end-to-end data flow

```text
                         BUYER
                           |
                           v
                 ┌───────────────────┐
                 │   CLI / WEB UI    │
                 │                   │
                 │ Text / PDF / XLSX │
                 │ Image / Email     │
                 └─────────┬─────────┘
                           |
                           v
        ┌───────────────────────────────────┐
        │         DEVELOPER 1               │
        │         RFQ INGESTION             │
        │                                   │
        │  1. Detect input type             │
        │  2. Extract document content      │
        │  3. LLM extracts specifications   │
        │  4. Normalize material details    │
        │  5. Validate structured output    │
        │  6. Identify missing information  │
        └─────────────────┬─────────────────┘
                          |
                          v
                   ParsedRFQ JSON
                          |
                          v
        ┌───────────────────────────────────┐
        │        AI AGENT ORCHESTRATOR      │
        │                                   │
        │  Understand current RFQ state     │
        │  Decide which tool to call next   │
        │  Evaluate tool results            │
        │  Decide when to stop              │
        └─────────────────┬─────────────────┘
                          |
               ┌──────────┴──────────┐
               |                     |
               v                     v
       MISSING INFORMATION     SUFFICIENT TO SEARCH
               |                     |
               v                     |
       ASK CLARIFICATION             |
               |                     |
               v                     |
        BUYER RESPONDS               |
               |                     |
               v                     |
        UPDATE ParsedRFQ             |
               |                     |
               └──────────┬──────────┘
                          |
                          v
        ┌───────────────────────────────────┐
        │         DEVELOPER 2               │
        │         HYBRID RETRIEVAL          │
        │                                   │
        │  1. Generate query embeddings     │
        │  2. Semantic vector search        │
        │  3. Structured SQL search         │
        │  4. Retrieve historical pricing   │
        │  5. Retrieve compliance evidence  │
        └─────────────────┬─────────────────┘
                          |
                          | Queries
                          v
        ┌───────────────────────────────────┐
        │         DEVELOPER 3               │
        │         DATA FOUNDATION           │
        │                                   │
        │  SQLite                           │
        │  - Supplier catalog               │
        │  - Supplier prices                │
        │  - Historical quotations          │
        │  - Market benchmarks              │
        │  - Compliance documents           │
        │                                   │
        │  ChromaDB index uses these records│
        └─────────────────┬─────────────────┘
                          |
                          v
                  RetrievalEvidence
                          |
                          v
        ┌───────────────────────────────────┐
        │        AI AGENT ORCHESTRATOR      │
        │                                   │
        │  Evaluate retrieved evidence      │
        │  Select next tools                │
        └─────────────────┬─────────────────┘
                          |
                ┌─────────┴─────────┐
                |                   |
                v                   v
       SPEC VALIDATION        PRICING TOOL
                |                   |
                v                   v
       COMPLIANCE CHECK      MARKET COMPARISON
                |                   |
                └─────────┬─────────┘
                          |
                          v
                 AGENT EVALUATES
                          |
             ┌────────────┼────────────┐
             |            |            |
             v            v            v
        NEEDS INFO     NO MATCH     READY FOR
             |            |         HUMAN REVIEW
             v            v            |
         ASK BUYER    REPORT ISSUE      v
                                  QUOTE GENERATOR
                                         |
                                         v
                                 QUOTATION DRAFT
                                         |
                                         v
                                   HUMAN APPROVAL
                                         |
                                         v
                                        BUYER
```

**This is the final architecture.**

The implementation can stay simple, but the demo should show the agent making at least one meaningful decision based on a tool result.

---

# 2. Walk through one realistic example

Imagine the buyer submits:

> Hi RudCo,
>
> Please provide pricing for:
>
> 1. 20 pcs 304 stainless steel sheet, 0.060 inches thick, 48 × 96 inches.
> 2. 10 aluminum plates, 1/4 inch thick, 24 × 48 inches.
>
> Mill Test Reports required.
>
> Please send your best price.

### Step 1 — Developer 1 extracts and structures the RFQ

Your parser calls Nicrron.

It produces structured information:

```json
{
  "rfq_id": "RFQ-001",
  "items": [
    {
      "line_id": "LINE-001",
      "material": "stainless steel",
      "grade": "304",
      "form": "sheet",
      "thickness_in": 0.060,
      "width_in": 48,
      "length_in": 96,
      "quantity": 20,
      "requires_mtr": true,
      "missing_fields": []
    },
    {
      "line_id": "LINE-002",
      "material": "aluminum",
      "grade": null,
      "form": "plate",
      "thickness_in": 0.25,
      "width_in": 24,
      "length_in": 48,
      "quantity": 10,
      "requires_mtr": true,
      "missing_fields": ["grade"]
    }
  ]
}
```

This is a simplified representation of your actual `ParsedRFQ` contract.

Notice that the second product has no material grade.

**Your parser reports the missing grade; it doesn't choose one.**

Developer 1's work is complete once this structured information and its source references are available.

---

# 3. Step 2 — The agent receives ParsedRFQ

Now the actual agent starts making decisions.

Input:

```python
agent.run(parsed_rfq)
```

The agent sees two items.

**LINE-001**

```text
Material: Stainless steel
Grade: 304
Thickness: 0.060 inches
Dimensions: 48x96 inches
Quantity: 20
```

It has sufficient information for a targeted product search.

**LINE-002**

```text
Material: Aluminum
Grade: Unknown
Thickness: 0.25 inches
Dimensions: 24x48 inches
Quantity: 10
```

The grade is missing.

The agent could search for preliminary candidates, but cannot establish the required grade compatibility.

### Agent action

It invokes two tools:

```python
search_supplier_catalog(line_001)
```

And:

```python
generate_clarification(
    line_id="LINE-002",
    missing_fields=["grade"]
)
```

This is our first autonomous decision.

The agent isn't blindly processing all products in the same way.

It chooses different actions based on the extracted requirements.

---

# 4. Step 3 — Developer 2 performs retrieval

For LINE-001, the agent calls:

```python
search_supplier_catalog(line_001)
```

Developer 2 handles this.

The retrieval process involves two searches:

**Semantic retrieval**

```text
304 stainless steel sheet
0.060 inch
48x96 inch
```

The description gets converted into an embedding.

ChromaDB finds semantically similar catalog records.

**Structured retrieval**

SQLite searches for exact material properties:

```sql
SELECT *
FROM supplier_products
WHERE material_family = 'stainless steel'
AND material_grade = '304'
AND product_form = 'sheet';
```

Developer 2 combines these results.

Suppose it finds the following fictional records:

| SKU | Material | Grade | Thickness | Dimensions | Supplier cost |
|---|---|---|---|---|---|
| SS001 | Stainless steel | 304 | 0.060 in | 48×96 in | $100 |
| SS002 | Stainless steel | 316 | 0.060 in | 48×96 in | $110 |
| SS003 | Stainless steel | 304 | 0.125 in | 48×96 in | $130 |

The prices are illustrative synthetic data.

Retrieval returns these as candidates, with conflicts identified.

Developer 2 does not independently choose the final supplier or selling price.

---

# 5. Step 4 — Agent verifies supplier compatibility

The agent receives the candidates.

It sees that SS001 looks promising.

But instead of deciding based on embedding similarity, it invokes:

```python
validate_specifications(
    requested_spec=line_001,
    supplier_sku="SS001"
)
```

A deterministic validation tool checks the specifications.

Result:

```json
{
  "sku": "SS001",
  "grade_match": true,
  "form_match": true,
  "thickness_match": true,
  "dimensions_match": true,
  "status": "specifications_match"
}
```

These results assume the database values and buyer requirements have compatible, verified units and specifications.

Now the agent knows that SS001 matches the checked technical specifications.

It still needs to check compliance and commercial information.

**This separation is important: retrieval discovers candidates; validation establishes which requirements have actually been satisfied.**

---

# 6. Step 5 — Agent retrieves prices

The agent invokes:

```python
retrieve_historical_quotes("SS001")
```

Result:

```json
{
  "sku": "SS001",
  "historical_quotes": [
    {
      "price": 125,
      "currency": "USD",
      "price_unit": "per_sheet",
      "date": "2026-09-15",
      "source": "HIST-001",
      "is_synthetic": true
    }
  ]
}
```

It also invokes:

```python
retrieve_supplier_prices("SS001")
```

Result:

```json
{
  "sku": "SS001",
  "supplier_cost": 100,
  "currency": "USD",
  "price_unit": "per_sheet",
  "effective_date": "2026-10-01",
  "is_synthetic": true
}
```

Next:

```python
retrieve_market_benchmarks("SS001")
```

Suppose no verified comparable market benchmark exists.

The tool returns:

```json
{
  "benchmarks": [],
  "status": "no_verified_benchmark"
}
```

The agent now has useful historical and cost information, but cannot honestly claim that a proposed selling price is currently competitive against the market.

---

# 7. Step 6 — The agent checks compliance

The buyer requested Mill Test Reports.

The agent invokes:

```python
check_compliance(
    sku="SS001",
    requirements=["MTR"]
)
```

Suppose the result is:

```json
{
  "sku": "SS001",
  "required_documents": ["MTR"],
  "verified_mtr_available": false,
  "status": "requires_documentation"
}
```

Now something important happens.

The technical specifications match, but the required documentation is unavailable.

**The agent should not declare the product ready for quotation approval.**

Instead, it can mark the line as requiring supplier documentation.

This is another meaningful agent decision.

---

# 8. Step 7 — Agent determines what happens next

Our agent has two product lines.

Let's summarize the results.

| Check | LINE-001 | LINE-002 |
|---|---|---|
| RFQ parsed | Yes | Yes |
| Material grade known | Yes | No |
| Supplier candidate found | Yes | Not yet confirmed |
| Technical match | Yes | Unresolved |
| Supplier cost available | Yes | Not checked |
| Market benchmark available | No | Not checked |
| MTR verified | No | Not checked |
| Ready for quotation approval | No | No |

The agent needs to decide what to do.

For LINE-001, it can prepare a provisional quote line with a documented supplier price basis, while flagging the missing benchmark and MTR.

For LINE-002, it should request the missing aluminum grade.

The overall RFQ should be marked as requiring clarification or review rather than ready to send.

---

# 9. Step 8 — The agent asks the buyer

The agent invokes:

```python
generate_clarification(
    line_id="LINE-002",
    missing_fields=["material_grade"]
)
```

The system displays:

> **AlloyQuote**
>
> I found a potential supplier product for the stainless steel sheet.
>
> Before completing your quotation, I need to clarify one item:
>
> **Item 2:** Which aluminum grade do you require?
>
> For example, 6061 or 5052?
>
> The stainless steel item also requires MTR verification.

The buyer responds:

> 6061.

The system updates LINE-002:

```json
{
  "line_id": "LINE-002",
  "material": "aluminum",
  "grade": "6061",
  "form": "plate",
  "thickness_in": 0.25,
  "width_in": 24,
  "length_in": 48,
  "quantity": 10,
  "requires_mtr": true
}
```

The agent resumes its workflow for LINE-002.

It searches the supplier catalog, validates specifications, retrieves pricing, and checks compliance.

**It doesn't need to restart the entire RFQ workflow.**

That makes it a stateful agent.

---

# 10. Step 9 — Generate the quotation

Assume the supplier and compliance checks eventually succeed, and the company has approved the appropriate pricing rules.

The agent invokes:

```python
calculate_quote_price()
```

This tool should use deterministic business logic—not ask an LLM to invent a price.

For example, using entirely synthetic demo records:

| Material | Quantity | Supplier cost | Proposed selling price |
|---|---:|---:|---:|
| Stainless 304 sheet | 20 | $100 | $125 |
| Aluminum 6061 plate | 10 | $75 | $95 |

The proposed selling prices above are illustrative, assuming a configured pricing policy. They are not verified market prices.

The pricing engine calculates:

```text
LINE-001
20 × $125 = $2,500

LINE-002
10 × $95 = $950

Subtotal = $3,450
```

The agent can then invoke:

```python
generate_quote()
```

The resulting draft might look like:

### AlloyQuote — Quotation Draft

**RFQ:** RFQ-001\
**Customer:** Demo Manufacturing Co.

| Item | Description | Qty | Unit Price | Total |
|---|---|---:|---:|---:|
| 1 | Stainless steel 304 sheet, 0.060", 48×96" | 20 | $125 | $2,500 |
| 2 | Aluminum 6061 plate, 0.25", 24×48" | 10 | $95 | $950 |
| | **Subtotal** | | | **$3,450** |

**Status: Draft — Subject to evidence verification and human approval.**

Pricing is illustrative synthetic data. Current market competitiveness must be supported by comparable benchmark evidence before making that claim. Required MTRs must be verified before the quote is represented as compliant.

After the reviewer approves the quote and supporting evidence, it can become ready to send.

---

# 11. Where exactly is the AI agent?

This is the part I want you to understand clearly.

You have two different kinds of components.

## A. Tools — Built by the developers

| Tool | Owner | Purpose |
|---|---|---|
| `parse_rfq()` | Developer 1 | Extract structured requirements |
| `search_supplier_catalog()` | Developer 2 | Retrieve supplier candidates |
| `retrieve_historical_quotes()` | Developer 2 | Retrieve historical pricing evidence |
| `retrieve_market_benchmarks()` | Developer 2 | Retrieve benchmark evidence |
| Database repositories | Developer 3 | Supply canonical source records |
| `validate_specifications()` | Phase 2 / shared | Check technical compatibility |
| `calculate_quote_price()` | Phase 2 / shared | Apply pricing rules |
| `check_compliance()` | Phase 2 / shared | Verify documented requirements |
| `generate_clarification()` | Phase 2 / shared | Formulate questions |
| `generate_quote()` | Phase 2 / shared | Assemble quotation draft |

These tools perform specific operations.

They don't have to be autonomous.

## B. The agent — The orchestrator

The agent uses these tools.

It can decide:

**Decision 1:** Do I understand the RFQ?

If not, call the parser or request clarification.

**Decision 2:** Can I search for suppliers?

If yes, call the catalog retrieval tool.

**Decision 3:** Are the retrieved products technically compatible?

If uncertain, invoke specification validation.

**Decision 4:** Do I have sufficient pricing evidence?

If not, retrieve additional price records or flag that information as unavailable.

**Decision 5:** Are the compliance requirements satisfied?

If not, request supporting documentation or flag the issue.

**Decision 6:** Can I produce a valid quotation draft?

If yes, generate the draft using approved calculations.

If not, ask for clarification or report the blocker.

That's the agent's autonomy.

It decides **what to do next based on the current state and tool results**.

However, the application must enforce rules such as never inventing prices, never approving unverifiable compliance, and never sending a quote without the required human approval.

---

# 12. Final architecture for the hackathon demo

I would keep the demo centered on one visible agent workflow:

```text
                 RFQ SUBMITTED
                       |
                       v
               RFQ INTAKE TOOL
                       |
                       v
                  ParsedRFQ
                       |
                       v
                 ┌───────────┐
                 │  AI AGENT │<──────────┐
                 └─────┬─────┘           |
                       |                 |
                       v                 |
              SELECT NEXT ACTION         |
                       |                 |
        ┌──────────────┼──────────────┐  |
        |              |              |  |
        v              v              v  |
   SEARCH CATALOG   ASK BUYER    CHECK PRICING
        |              |              |
        v              v              v
    TOOL RESULT    USER ANSWER    TOOL RESULT
        |              |              |
        └──────────────┼──────────────┘
                       |
                       └─────────────────┘

                  AGENT EVALUATES
                       |
             ┌─────────┴─────────┐
             |                   |
        MORE WORK             ALL REQUIRED
         NEEDED             CHECKS SATISFIED
             |                   |
             v                   v
        CALL TOOLS          GENERATE DRAFT
             |                   |
             v                   v
        AGENT LOOP          HUMAN APPROVAL
                                 |
                                 v
                            FINAL QUOTE
```

### What makes this impressive to judges?

It's not simply uploading a PDF and asking GPT to write a quotation.

The system can demonstrate that:

- **Developer 1:** The AI understands messy industrial descriptions and preserves ambiguity.
- **Developer 2:** Supplier recommendations come from actual retrieval results, not LLM guesses.
- **Developer 3:** Prices, specifications, and compliance claims have identifiable data sources.
- **AI agent:** The system autonomously chooses which tools to invoke and when to ask for clarification.
- **PRISM:** Guardrails, evaluations, traces, and Knowledge Base grounding provide evidence that the system is behaving reliably.
- **Final output:** A human-reviewable quotation draft backed by supplier records and explicit pricing logic.

The most compelling live demonstration would show the agent encountering missing information, asking one targeted question, receiving the answer, resuming the workflow, and creating a quote draft without starting over.

### Your team's central architecture

**Developer 1 builds understanding. Developer 2 builds retrieval. Developer 3 builds the data foundation. The agent connects their work and makes controlled decisions.**

One important timing distinction: your master specification calls the extraction-and-retrieval foundation **Phase 1**, and the tool-calling quotation agent **Phase 2**. The architecture above represents the combined final submission, not just Phase 1.

For the hackathon, the essential goal is a working demonstration of that complete loop—even with a small, clearly labeled synthetic supplier catalog—rather than a large system with unverified capabilities.