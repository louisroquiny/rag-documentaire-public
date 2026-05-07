import csv
from datetime import datetime
from pathlib import Path


FEEDBACK_FILE = Path("feedback_archie.csv")


def serialize_documents(documents: list[dict]) -> str:
    titles = []
    for doc in documents or []:
        title = doc.get("title") or doc.get("path") or doc.get("filename")
        if title:
            titles.append(str(title))
    return " | ".join(titles)


def append_feedback(
    question: str,
    answer: str,
    model: str,
    rating: str,
    documents: list[dict] | None = None,
) -> bool:
    """
    Enregistre un feedback simple dans un CSV local.
    Sur certains hébergements, l'écriture disque peut être éphémère ou indisponible.
    """
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "rating": rating,
        "model": model,
        "question": question,
        "answer": answer,
        "documents": serialize_documents(documents or []),
    }

    file_exists = FEEDBACK_FILE.exists()

    try:
        with FEEDBACK_FILE.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        return True
    except Exception:
        return False


def feedback_file_exists() -> bool:
    return FEEDBACK_FILE.exists()


def read_feedback_bytes() -> bytes:
    if not FEEDBACK_FILE.exists():
        return b""
    return FEEDBACK_FILE.read_bytes()
