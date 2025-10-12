from fastapi import APIRouter, Depends
from fastapi import status
import logging
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from . import utils


router = APIRouter(dependencies=[Depends(utils.auth_user)])
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class IndexerRequest(BaseModel):
    text: str


print(f"This is the payload to send to /index : {IndexerRequest(text='Hello').dict()}")


@router.post("/index", status_code=status.HTTP_200_OK)
def index(request: IndexerRequest) -> JSONResponse:
    logger.warning(f"Inside Indexer::{request}")
    try:
        print(f"Initiating indexing with data {request}")
        try:
            chunks = utils.get_chunks(request.text)
            for chunk in chunks:
                embedding = utils.get_embedding(chunk)
                utils.insert_db(chunk, embedding)
            return JSONResponse(content={"success": True})
        except Exception:
            logger.error("Indexing failed")
            return JSONResponse(content={"error": "Indexing failed"})
    except Exception as e:
        logger.error(str(e))
        return JSONResponse(content={"error": str(e)})
