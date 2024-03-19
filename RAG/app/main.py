from fastapi import FastAPI, Request, Depends, HTTPException
from . import indexer
from . import queries
from . import utils
import logging

app = FastAPI()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app.include_router(indexer.router, prefix="/api/v1")
app.include_router(queries.router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
