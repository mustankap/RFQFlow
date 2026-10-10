from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.deployment import public_limits

from backend.app.ingestion.router import router as ingestion_router

app = FastAPI(
    title="RFQFlow API",
    description="Industrial RFQ extraction and normalization",
    version="0.1.0",
)

app.include_router(ingestion_router)


@app.get("/health")
def health():
    return {"status": "ok"}

from backend.app.workflow.router import router as quote_router
app.include_router(quote_router)

app.middleware("http")(public_limits)
app.add_middleware(CORSMiddleware,
    allow_origins=["https://mustankap.github.io", "http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)
