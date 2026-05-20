from functools import lru_cache
from pathlib import Path


CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "archie_documents"
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
STATS_BATCH_SIZE = 500

_model = None
_collection = None


class LocalRetrievalUnavailable(RuntimeError):
    pass


def get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise LocalRetrievalUnavailable(
                "Le moteur local nécessite sentence-transformers. Installe requirements-local.txt."
            ) from e
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def get_collection():
    global _collection
    if _collection is None:
        try:
            import chromadb
        except Exception as e:
            raise LocalRetrievalUnavailable(
                "Le moteur local nécessite chromadb. Installe requirements-local.txt."
            ) from e
        if not CHROMA_DIR.exists():
            raise LocalRetrievalUnavailable(
                "Index local introuvable. Lance scripts/build_local_index.py pour créer chroma_db/."
            )
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = client.get_or_create_collection(name=COLLECTION_NAME)
    return _collection


def build_where_filter(document_type: str = "Tous", year: str = "Toutes", theme: str = "Tous") -> dict | None:
    conditions = []
    if document_type and document_type != "Tous":
        conditions.append({"document_type": document_type})
    if year and year != "Toutes":
        conditions.append({"year": year})
    if theme and theme != "Tous":
        conditions.append({"theme": theme})
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def search_local(
    question: str,
    document_type: str = "Tous",
    year: str = "Toutes",
    theme: str = "Tous",
    top_k: int = 8,
) -> list[dict]:
    model = get_model()
    collection = get_collection()
    query_embedding = model.encode([f"query: {question}"], normalize_embeddings=True)[0].tolist()
    where_filter = build_where_filter(document_type=document_type, year=year, theme=theme)
    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where_filter:
        query_kwargs["where"] = where_filter
    results = collection.query(**query_kwargs)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    hits = []
    for doc, meta, distance in zip(documents, metadatas, distances):
        meta = meta or {}
        hits.append({
            "text": doc,
            "metadata": meta,
            "distance": distance,
            "title": meta.get("title", ""),
            "post_url": meta.get("post_url", ""),
            "file_url": meta.get("file_url", ""),
            "path": meta.get("path", ""),
            "document_type": meta.get("document_type", ""),
            "theme": meta.get("theme", ""),
            "date": meta.get("date", ""),
            "year": meta.get("year", ""),
        })
    return hits


def _doc_key(meta: dict) -> str:
    return (
        meta.get("file_url")
        or meta.get("post_url")
        or meta.get("path")
        or meta.get("title")
        or ""
    )


def _iter_collection_metadatas(collection, total_count: int):
    for offset in range(0, total_count, STATS_BATCH_SIZE):
        result = collection.get(
            include=["metadatas"],
            limit=STATS_BATCH_SIZE,
            offset=offset,
        )
        for meta in result.get("metadatas", []) or []:
            yield meta or {}


def _metadata_to_document_row(meta: dict) -> dict:
    return {
        "title": meta.get("title", "") or meta.get("path", "") or "Document",
        "post_url": meta.get("post_url", ""),
        "file_url": meta.get("file_url", ""),
        "path": meta.get("path", ""),
        "category": meta.get("category", ""),
        "document_type": meta.get("document_type", ""),
        "theme": meta.get("theme", ""),
        "section": meta.get("section", ""),
        "date": meta.get("date", ""),
        "date_iso": meta.get("date_iso", ""),
        "year": meta.get("year", ""),
        "summary": meta.get("summary", ""),
        "filename": meta.get("filename", ""),
        "language": meta.get("language", ""),
        "source_list_url": meta.get("source_list_url", ""),
    }


@lru_cache(maxsize=1)
def get_local_index_documents() -> list[dict]:
    collection = get_collection()
    chunk_count = collection.count()
    documents = {}

    for meta in _iter_collection_metadatas(collection, chunk_count):
        key = _doc_key(meta)
        if not key or key in documents:
            continue
        documents[key] = _metadata_to_document_row(meta)

    return sorted(
        documents.values(),
        key=lambda row: row.get("date_iso") or row.get("date") or row.get("year") or "",
        reverse=True,
    )


@lru_cache(maxsize=1)
def get_local_index_stats() -> dict:
    collection = get_collection()
    chunk_count = collection.count()
    documents = get_local_index_documents()
    years = []
    dates = []

    for meta in documents:
        year = str(meta.get("year", "") or "").strip()
        date_iso = str(meta.get("date_iso", "") or "").strip()
        date = str(meta.get("date", "") or "").strip()
        if year.isdigit():
            years.append(year)
        if date_iso:
            dates.append(date_iso)
        elif date:
            dates.append(date)

    oldest = min(dates) if dates else (min(years) if years else "")
    newest = max(dates) if dates else (max(years) if years else "")

    return {
        "engine": "chroma",
        "collection": COLLECTION_NAME,
        "chunk_count": chunk_count,
        "indexed_documents": len(documents),
        "oldest_document": oldest,
        "newest_document": newest,
    }


def clear_local_index_cache() -> None:
    get_local_index_documents.cache_clear()
    get_local_index_stats.cache_clear()


def hits_to_context(hits: list[dict]) -> str:
    if not hits:
        return "Aucun extrait documentaire trouvé."
    blocks = []
    for i, hit in enumerate(hits, start=1):
        meta = hit.get("metadata", {}) or {}
        title = meta.get("title") or meta.get("path") or f"Document {i}"
        blocks.append(f"""
[Document {i}]
Titre : {title}
Type : {meta.get('document_type', '')}
Thème : {meta.get('theme', '')}
Date : {meta.get('date', '') or meta.get('year', '')}
Lien article : {meta.get('post_url', '')}
Lien PDF : {meta.get('file_url', '')}
Extrait :
{hit.get('text', '')}
""".strip())
    return "\n\n---\n\n".join(blocks)


def hits_to_linked_documents(hits: list[dict]) -> list[dict]:
    docs = []
    seen = set()
    for hit in hits:
        meta = hit.get("metadata", {}) or {}
        key = meta.get("file_url") or meta.get("post_url") or meta.get("path") or meta.get("title")
        if not key or key in seen:
            continue
        seen.add(key)
        docs.append(_metadata_to_document_row(meta))
    return docs
