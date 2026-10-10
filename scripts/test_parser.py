from backend.app.ingestion.parser import parse_rfq_text

SAMPLE_RFQS = [
    "20 pcs 304 SS sheet 16ga 4x8",
    "10 aluminum plates 1/4 x 2x4",
    """
Hello,

Please quote the following:

20 pcs 304 SS sheet 16ga 4x8
15 pcs A36 steel plate 1/4 x 48 x 96

Include MTRs for both materials.
""",
]


def main():
    print("\n========== RFQFlow Parser ==========\n")

    for i, rfq in enumerate(SAMPLE_RFQS, start=1):
        print(f"{i}. {rfq.strip()[:60]}")

    print("4. Enter custom RFQ text")

    choice = input("\nSelect option: ").strip()

    if choice == "4":
        print("\nEnter your RFQ text.")
        print("Type END on a new line when finished.\n")

        lines = []

        while True:
            line = input()

            if line.strip() == "END":
                break

            lines.append(line)

        rfq_text = "\n".join(lines)

    elif choice in ("1", "2", "3"):
        rfq_text = SAMPLE_RFQS[int(choice) - 1]

    else:
        print("Invalid option")
        return

    try:
        result = parse_rfq_text(rfq_text)

        print("\n========== PARSED RFQ ==========\n")
        print(result.model_dump_json(indent=2))

        print("\n========== VALIDATION SUMMARY ==========\n")

        for item in result.items:
            print(f"\n{item.line_id}")
            print(f"Original: {item.original_text}")
            print(f"Status: {item.extraction_status}")

            if item.missing_fields:
                print("Missing:", item.missing_fields)

            if item.ambiguities:
                print("Warnings:", item.ambiguities)

        print("\nParsedRFQ is ready for Developer 2 retrieval.")
        print("Any unresolved fields must remain visible.")

    except Exception as error:
        print(f"\nParsing failed: {error}")
        print("No verified ParsedRFQ was produced.")


if __name__ == "__main__":
    main()
