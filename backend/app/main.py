from fastapi import FastAPI

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
