import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


def normalize_path(value: str | None) -> str:
    if not value:
        return ""
    value = str(value).replace("\\", "/").strip()
    if value.startswith("http://") or value.startswith("https://"):
        value = urlparse(value).path
    while value.startswith("./"):
        value = value[2:]
    for prefix in ["data/", "data_raw/"]:
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    return value.lower().strip("/")


def read_pdf_text(pdf_path: Path) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(pdf_path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        print(f"[PDF ERROR] {pdf_path}: {e}")
        return ""


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def make_chunk_id(path: str, index: int, text: str) -> str:
    raw = f"{path}:{index}:{text[:100]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_inventory(inventory_file: Path) -> dict:
    if not inventory_file.exists():
        raise FileNotFoundError(f"Inventory not found: {inventory_file}")
    return json.loads(inventory_file.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Archie local vector index.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--inventory", default="inventaire.json")
    parser.add_argument("--chroma-dir", default="chroma_db")
    parser.add_argument("--collection", default="archie_documents")
    parser.add_argument("--embedding-model", default="intfloat/multilingual-e5-base")
    parser.add_argument("--chunk-size", type=int, default=1800)
    parser.add_argument("--chunk-overlap", type=int, default=250)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    import chromadb
    from sentence_transformers import SentenceTransformer

    data_dir = Path(args.data_dir)
    inventory = load_inventory(Path(args.inventory))
    model = SentenceTransformer(args.embedding_model)
    client = chromadb.PersistentClient(path=str(Path(args.chroma_dir)))

    if args.reset:
        try:
            client.delete_collection(name=args.collection)
        except Exception:
            pass

    collection = client.get_or_create_collection(name=args.collection)

    ids = []
    docs = []
    metas = []

    for raw_path, row in inventory.items():
        if not isinstance(row, dict):
            continue
        row = dict(row)
        rel_path = normalize_path(row.get("path") or raw_path)
        pdf_path = data_dir / rel_path
        if not pdf_path.exists():
            print(f"[SKIP] missing PDF: {pdf_path}")
            continue
        print(f"[PDF] {pdf_path}")
        text = read_pdf_text(pdf_path)
        if not text.strip():
            print(f"[SKIP] empty text: {pdf_path}")
            continue
        for i, chunk in enumerate(chunk_text(text, args.chunk_size, args.chunk_overlap)):
            ids.append(make_chunk_id(rel_path, i, chunk))
            docs.append(chunk)
            metas.append({
                "path": rel_path,
                "chunk_index": i,
                "title": row.get("title", ""),
                "category": row.get("category", ""),
                "document_type": row.get("document_type", row.get("category", "")),
                "theme": row.get("theme", ""),
                "section": row.get("section", ""),
                "date": row.get("date", ""),
                "date_iso": row.get("date_iso", ""),
                "year": str(row.get("year", "") or ""),
                "post_url": row.get("post_url", ""),
                "file_url": row.get("file_url", ""),
                "summary": row.get("summary", ""),
                "filename": row.get("filename", ""),
                "language": row.get("language", ""),
                "source_list_url": row.get("source_list_url", ""),
            })

    print(f"Chunks to index: {len(docs)}")
    if not docs:
        return

    embeddings = model.encode(
        [f"passage: {doc}" for doc in docs],
        normalize_embeddings=True,
        show_progress_bar=True,
    ).tolist()

    batch_size = 500
    for start in range(0, len(docs), batch_size):
        end = start + batch_size
        collection.upsert(
            ids=ids[start:end],
            documents=docs[start:end],
            metadatas=metas[start:end],
            embeddings=embeddings[start:end],
        )
        print(f"Indexed: {min(end, len(docs))}/{len(docs)}")

    print("Local index ready.")


if __name__ == "__main__":
    main()
