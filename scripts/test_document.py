import sys

from backend.app.ingestion.document_reader import read_document
from backend.app.ingestion.parser import parse_rfq_text
from backend.app.ingestion.source_mapper import map_source_references


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.test_document <file>")
        return

    file_path = sys.argv[1]

    document = read_document(file_path)

    print("\n===== DOCUMENT EXTRACTED =====")
    print("Type:", document.source_type)
    print("Filename:", document.source_filename)
    print("Segments:", len(document.segments))

    print("\n===== EXTRACTED TEXT =====")
    print(document.text)

    print("\n===== NICRRON PARSING =====")

    result = parse_rfq_text(document.text)
    result = map_source_references(result, document)

    # Record the actual uploaded source type.
    result.source_type = document.source_type
    result.source_filename = document.source_filename

    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
