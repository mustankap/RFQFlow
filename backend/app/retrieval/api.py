"""Standalone D2 API; does not take ownership of Developer 1's app/main.py."""
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..api.retrieval_routes import router

app = FastAPI(title='RFQFlow Retrieval', version='0.2.0')
app.include_router(router)


@app.exception_handler(ValidationError)
async def validation_error(request: Request, exc: ValidationError):
    return JSONResponse(status_code=422, content={'detail': 'Invalid parsed RFQ or canonical evidence data',
        'fields': [list(e['loc']) for e in exc.errors()]})


@app.exception_handler(ValueError)
async def value_error(request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={'detail': str(exc)})


@app.exception_handler(FileNotFoundError)
@app.exception_handler(sqlite3.Error)
async def storage_error(request: Request, exc: Exception):
    return JSONResponse(status_code=503, content={'detail': 'Canonical SQLite data unavailable; check server configuration'})
