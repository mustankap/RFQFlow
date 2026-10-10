import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .embeddings import NicrronEmbeddings
from .repository import SQLiteRepository
from .service import RetrievalService
from .vector_search import RetrievalIndex

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / 'backend/data/fixtures/retrieval'


def create_service(db=None, chroma=None, as_of=None, trace=True):
    load_dotenv(ROOT / '.env')
    db = db or Path(os.getenv('RFQ_SQLITE_PATH', str(ROOT / '.local/demo.sqlite')))
    chroma = chroma or Path(os.getenv('RFQ_CHROMA_PATH', str(ROOT / '.local/chroma-hybrid')))
    day = as_of or os.getenv('RFQ_AS_OF_DATE')
    return RetrievalService(SQLiteRepository(db), RetrievalIndex(chroma, NicrronEmbeddings()),
        as_of=date.fromisoformat(day) if isinstance(day, str) else day,
        trace_dir=ROOT / '.local/traces' if trace else None)
