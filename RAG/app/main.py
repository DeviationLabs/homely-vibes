from fastapi import FastAPI, Request, Depends, HTTPException
from . import indexer
from . import queries
import logging

app = FastAPI(docs_url=None, redoc_url=None)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def auth_user(request: Request):
    auth_key = request.headers.get("Authorization")
    logger.info(f"Inside Auth::{auth_key}")
    if auth_key == "validated_user":
        return True
    else:
        raise HTTPException(401, {"message": "unauthorised"})


app.include_router(indexer.router, prefix="/api/v1",
                   dependencies=[Depends(auth_user)])
app.include_router(queries.router, prefix="/api/v1",
                   dependencies=[Depends(auth_user)])
