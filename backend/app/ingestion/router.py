from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.app.ingestion.parser import parse_rfq_text
from backend.app.ingestion.document_reader import read_document
from backend.app.ingestion.source_mapper import map_source_references
from backend.app.retrieval.models import ParsedRFQ

router = APIRouter(prefix="/api", tags=["RFQ Ingestion"])

SUPPORTED_EXTENSIONS = {".txt", ".eml", ".pdf", ".xlsx", ".csv"}
MAX_FILE_BYTES = 10 * 1024 * 1024


class TextRFQRequest(BaseModel):
    text: str = Field(min_length=1)


@router.post("/parse", response_model=ParsedRFQ)
def parse_text(request: TextRFQRequest):
    """Parse an RFQ submitted as plain text."""

    try:
        return parse_rfq_text(request.text)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.post("/parse-file", response_model=ParsedRFQ)
def parse_file(file: UploadFile = File(...)):
    """Parse an uploaded RFQ document."""

    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type",
        )

    content = file.file.read(MAX_FILE_BYTES + 1)

    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 10 MB limit",
        )

    if not content:
        raise HTTPException(
            status_code=422,
            detail="Uploaded file is empty",
        )

    temporary_path = None

    try:
        with NamedTemporaryFile(
            mode="wb",
            suffix=extension,
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)

        document = read_document(temporary_path)

        # Restore the buyer's original filename.
        document.source_filename = filename

        result = parse_rfq_text(document.text)

        result.source_type = document.source_type
        result.source_filename = filename

        result = map_source_references(result, document)

        return result

    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        file.file.close()
