import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.local_retrieval import (
    LocalRetrievalUnavailable,
    get_local_index_documents,
    get_local_index_stats,
    search_local,
)


API_TOKEN = os.getenv("LOCAL_SEARCH_API_TOKEN", "")

app = FastAPI(title="Hector Local Search API")


class SearchRequest(BaseModel):
    question: str = Field(..., min_length=1)
    document_type: str = "Tous"
    year: str = "Toutes"
    theme: str = "Tous"
    top_k: int = Field(default=8, ge=1, le=30)


def check_token(x_api_token: str | None) -> None:
    if API_TOKEN and x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats(x_api_token: str | None = Header(default=None)):
    check_token(x_api_token)
    try:
        return get_local_index_stats()
    except LocalRetrievalUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/documents")
def documents(x_api_token: str | None = Header(default=None)):
    check_token(x_api_token)
    try:
        return {"documents": get_local_index_documents()}
    except LocalRetrievalUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/search")
def search(request: SearchRequest, x_api_token: str | None = Header(default=None)):
    check_token(x_api_token)

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
