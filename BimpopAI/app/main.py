from fastapi import FastAPI
from . import indexer
from . import queries
import logging

app = FastAPI()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

app.include_router(indexer.router, prefix="/api/v1")
app.include_router(queries.router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
