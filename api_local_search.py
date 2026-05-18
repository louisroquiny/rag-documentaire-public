import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.local_retrieval import LocalRetrievalUnavailable, search_local


API_TOKEN = os.getenv("LOCAL_SEARCH_API_TOKEN", "")

app = FastAPI(title="Hector Local Search API")


class SearchRequest(BaseModel):
    question: str = Field(..., min_length=1)
    document_type: str = "Tous"
    year: str = "Toutes"
    theme: str = "Tous"
    top_k: int = Field(default=8, ge=1, le=30)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def search(request: SearchRequest, x_api_token: str | None = Header(default=None)):
    if API_TOKEN and x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")

    try:
        hits = search_local(
            question=request.question,
            document_type=request.document_type,
            year=request.year,
            theme=request.theme,
            top_k=request.top_k,
        )
    except LocalRetrievalUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {"hits": hits}
