from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from .service import QuoteWorkflow
from backend.app.retrieval.models import ParsedRFQ

router = APIRouter(prefix='/api/quote', tags=['Quote workflow'])
workflow = QuoteWorkflow()

class RunRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    parsed_rfq: ParsedRFQ | None = None

    @model_validator(mode='after')
    def one_input(self):
        if (self.text is None) == (self.parsed_rfq is None):
            raise ValueError('Supply exactly one of text or parsed_rfq')
        return self

class Answer(BaseModel):
    line_id: str
    field: Literal['material_family','material_grade','product_form','quantity','quantity_unit','thickness','width','length']
    value: str = Field(min_length=1, max_length=200)

class ClarifyRequest(BaseModel):
    rfq_id: str
    answers: list[Answer] = Field(min_length=1, max_length=100)

@router.post('/run')
def run(request: RunRequest):
    try:
        return workflow.run_parsed(request.parsed_rfq) if request.parsed_rfq is not None else workflow.run(request.text)
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
