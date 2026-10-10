import re

from backend.app.retrieval.models import ParsedRFQ


def normalize_text(text):
    """Normalize whitespace for source matching."""
    text = " ".join(str(text).split())
    text = re.sub(r"\s*([:|])\s*", r"\1", text)
    return text.casefold()


def map_source_references(rfq, document):
    """
    Match parsed RFQ lines to PDF pages or spreadsheet rows.

    A reference is assigned only when there is exactly
    one matching source segment.
    """

    data = rfq.model_dump()
    source_type = document.source_type

    matched_rows = set()

    for item in data["items"]:
        original = normalize_text(item["original_text"])
        matches = []

        for segment in document.segments:

            if source_type == "pdf":
                source_text = normalize_text(segment["text"])

                if original in source_text:
                    matches.append(segment)

            elif source_type in ("xlsx", "csv"):

                if source_type == "xlsx":
                    prefix = f"[Sheet {segment['sheet']}, " f"Row {segment['row']}] "
                else:
                    prefix = f"[Row {segment['row']}] "

                expected = normalize_text(prefix + segment["text"])

                # Require the entire row to match.
                if original == expected:
                    matches.append(segment)

        reference = item["source_reference"]
        reference["source_filename"] = document.source_filename

        if len(matches) == 1:
            match = matches[0]

            if source_type == "pdf":
                reference["page"] = match["page"]

            elif source_type in ("xlsx", "csv"):
                reference["row"] = match["row"]
                reference["sheet"] = match.get("sheet")

                matched_rows.add(
                    (
                        match.get("sheet"),
                        match["row"],
                    )
                )

        elif source_type in ("pdf", "xlsx", "csv"):
            warning = "Could not uniquely verify source location"

            item["ambiguities"].append(warning)
            item["ambiguities"] = list(dict.fromkeys(item["ambiguities"]))
            item["extraction_status"] = "needs_review"

    # For our row-based spreadsheet fixtures, each
    # nonempty data row should produce one RFQ item.
    if source_type in ("xlsx", "csv"):
        for segment in document.segments:

            key = (
                segment.get("sheet"),
                segment["row"],
            )

            if key not in matched_rows:
                data.setdefault("unparsed_segments", []).append(segment)

                data.setdefault("errors", []).append(f"Unmapped spreadsheet row: {key}")

    return ParsedRFQ.model_validate(data)
