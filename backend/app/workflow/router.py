from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from .service import QuoteWorkflow

router = APIRouter(prefix='/api/quote', tags=['Quote workflow'])
workflow = QuoteWorkflow()

class RunRequest(BaseModel):
    text: str = Field(min_length=1)

class Answer(BaseModel):
    line_id: str
    field: Literal['material_family','material_grade','product_form','quantity','quantity_unit','thickness','width','length']
    value: str = Field(min_length=1)

class ClarifyRequest(BaseModel):
    rfq_id: str
    answers: list[Answer] = Field(min_length=1)

@router.post('/run')
def run(request: RunRequest):
    try:
        return workflow.run(request.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Parsing or retrieval unavailable; verify provider and seeded index') from exc

@router.post('/clarify')
def clarify(request: ClarifyRequest):
    try:
        return workflow.clarify(request.rfq_id,request.answers)
    except KeyError as exc:
        raise HTTPException(404,'RFQ session not found (sessions reset on restart)') from exc
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503,'Retrieval unavailable') from exc
