from fastapi import APIRouter, Depends
from fastapi import status
import logging
from typing import Optional
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from . import utils


router = APIRouter(dependencies=[Depends(utils.auth_user)])
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class MatchRequest(BaseModel):
    match_on: str


class SummarizeRequest(BaseModel):
    summary_question: Optional[str]


print(f"This is an example payload to send to /priors : {MatchRequest(match_on='').dict()}")
print(
    f"This is an example payload to send to /summarize : {SummarizeRequest(summary_question='What is the meaning of life?').dict()}"
)
print(
    """Eg: curl --header "auth:validated_user" -X POST http://localhost:8080/api/v1/summarize -d '{"summary_question":"blank"}' -H 'Content-Type: application/json'"""
)
print("Also see swagger docs at http://localhost:8080/docs")


@router.post("/priors", status_code=status.HTTP_200_OK)
def fetch_matches(request: MatchRequest) -> JSONResponse:
    return JSONResponse(content={"success": True, "message": ["All matched data"]})


@router.post("/summarize", status_code=status.HTTP_200_OK)
def summarize(request: SummarizeRequest) -> JSONResponse:
    docs = utils.get_similar_texts(request.summary_question)
    answer = utils.get_llm_response(docs)

    return JSONResponse(content={"success": True, "message": answer})


def dud() -> None: ...
