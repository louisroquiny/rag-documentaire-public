import csv
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def normalize_filename(value: str | None) -> str:
    """
    Normalise un nom, chemin ou URL pour faciliter les correspondances.
    """
    if not value:
        return ""

    value = str(value).replace("\\", "/").strip()

    if value.startswith("http://") or value.startswith("https://"):
        value = urlparse(value).path

    return Path(value).name.lower().strip()


def normalize_path(value: str | None) -> str:
    """
    Normalise un chemin pour matcher la colonne path de l'inventaire.
    """
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


def normalize_inventory_row(row: dict, path: str = "") -> dict:
    """
    Harmonise les anciennes et nouvelles structures d'inventaire.
    """
    row = dict(row)
    row["path"] = row.get("path") or path
    row["filename"] = row.get("filename") or normalize_filename(row.get("path")) or normalize_filename(row.get("file_url"))
    row["document_type"] = row.get("document_type") or row.get("category", "")
    row["date_iso"] = row.get("date_iso", "")
    row["year"] = str(row.get("year", "") or "")
    row["summary"] = row.get("summary", "")
    row["section"] = row.get("section", "")
    row["theme_url"] = row.get("theme_url", "")
    row["language"] = row.get("language", "")
    row["source_list_url"] = row.get("source_list_url", "")
    row["id"] = row.get("id", "")
    return row


def load_inventory(
    json_file: Path = Path("inventaire.json"),
    csv_file: Path = Path("inventaire.csv"),
) -> tuple[dict, dict]:
    """
    Charge inventaire.json si disponible, sinon inventaire.csv.
    Retourne deux index : rows_by_filename, rows_by_path.
    """
    if json_file.exists() and json_file.stat().st_size > 0:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        rows_by_filename: dict[str, dict] = {}
        rows_by_path: dict[str, dict] = {}

        if isinstance(data, dict):
            for path, row in data.items():
                if not isinstance(row, dict):
                    continue

                row = normalize_inventory_row(row, path)
                path_key = normalize_path(row["path"])
                filename = normalize_filename(row["path"]) or normalize_filename(row.get("file_url"))

                if filename:
                    rows_by_filename[filename] = row

                if path_key:
                    rows_by_path[path_key] = row

        return rows_by_filename, rows_by_path

    if not csv_file.exists():
        return {}, {}

    rows_by_filename: dict[str, dict] = {}
    rows_by_path: dict[str, dict] = {}

    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            row = normalize_inventory_row(row, row.get("path", ""))
            local_path = row.get("path", "")
            file_url = row.get("file_url", "")

            path_key = normalize_path(local_path)
            filename = normalize_filename(local_path) or normalize_filename(file_url)

            if filename:
                rows_by_filename[filename] = row

            if path_key:
                rows_by_path[path_key] = row

    return rows_by_filename, rows_by_path


def load_selection_paths(selection_file: str | None) -> tuple[set[str], bool]:
    """
    Lit l'inventaire de selection genere par analyse_quota_gemini.py.
    """
    if not selection_file:
        return set(), False

    selection_path = Path(str(selection_file))

    if not selection_path.exists():
        return set(), False

    try:
        data = json.loads(selection_path.read_text(encoding="utf-8"))
    except Exception:
        return set(), False

    selected_paths: set[str] = set()

    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = [("", row) for row in data if isinstance(row, dict)]
    else:
        return set(), False

    for key, row in items:
        if not isinstance(row, dict):
            continue

        path = row.get("path") or key
        path_key = normalize_path(path)

        if path_key:
            selected_paths.add(path_key)

    return selected_paths, True


def unique_inventory_rows(inventory: dict, inventory_by_path: dict) -> list[dict]:
    """
    Retourne les lignes uniques de l'inventaire complet.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    source_rows = inventory_by_path.values() if inventory_by_path else inventory.values()

    for row in source_rows:
        key = row.get("file_url") or row.get("post_url") or row.get("path") or row.get("title")

        if not key or key in seen:
            continue

        seen.add(key)
        rows.append(row)

    return rows


def parse_inventory_date(row: dict):
    date_iso = str(row.get("date_iso", "") or "").strip()

    if not date_iso:
        return None

    try:
        return datetime.strptime(date_iso, "%Y-%m-%d").date()
    except Exception:
        return None


def format_date_fr_from_iso(date_iso: str | None) -> str:
    if not date_iso:
        return "date inconnue"

    try:
        return datetime.strptime(str(date_iso), "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return str(date_iso)


def local_pdf_exists_for_row(row: dict, data_dir: Path = Path("data")) -> bool:
    """
    Verifie si le PDF selectionne existe localement dans data/.
    """
    path = normalize_path(row.get("path"))

    if not path:
        return False

    if not data_dir.exists():
        return True

    return (data_dir / path).exists()


def compute_database_coverage(
    inventory: dict,
    inventory_by_path: dict,
    selection_file: str | None,
    data_dir: Path = Path("data"),
) -> dict:
    """
    Calcule ce que la base Gemini est censee contenir par rapport a l'inventaire complet local.
    """
    all_rows = unique_inventory_rows(inventory, inventory_by_path)
    total_documents = len(all_rows)
    selected_paths, selection_file_found = load_selection_paths(selection_file)

    if selection_file_found and selected_paths:
        indexed_rows = [
            row for row in all_rows
            if normalize_path(row.get("path")) in selected_paths
            and local_pdf_exists_for_row(row, data_dir)
        ]
        selection_mode = "selection"
    else:
        indexed_rows = all_rows
        selection_mode = "full_inventory"

    dated_rows = [row for row in indexed_rows if parse_inventory_date(row)]
    oldest_row = min(dated_rows, key=parse_inventory_date) if dated_rows else None
    newest_row = max(dated_rows, key=parse_inventory_date) if dated_rows else None

    oldest_date_iso = oldest_row.get("date_iso") if oldest_row else ""
    newest_date_iso = newest_row.get("date_iso") if newest_row else ""

    return {
        "selection_file": str(selection_file or ""),
        "selection_file_found": selection_file_found,
        "selection_mode": selection_mode,
        "total_documents": total_documents,
        "indexed_documents": len(indexed_rows),
        "selected_paths_count": len(selected_paths),
        "selection_missing_local_count": max(0, len(selected_paths) - len(indexed_rows)) if selection_file_found and selected_paths else 0,
        "indexed_paths": selected_paths,
        "indexed_rows": indexed_rows,
        "oldest_date_iso": oldest_date_iso,
        "oldest_date_fr": format_date_fr_from_iso(oldest_date_iso),
        "newest_date_iso": newest_date_iso,
        "newest_date_fr": format_date_fr_from_iso(newest_date_iso),
    }


def database_coverage_sentence(database_coverage: dict) -> str:
    total = database_coverage["total_documents"]
    indexed = database_coverage["indexed_documents"]
    oldest = database_coverage["oldest_date_fr"]

    if total and indexed:
        return (
            "En raison de l'espace mémoire limité, "
            f"la base documentaire indexée contient {indexed} document(s) sur {total} "
            f"dans l'inventaire complet. Les documents consultables remontent jusqu'au {oldest}."
        )

    if total:
        return (
            "En raison de l'espace mémoire limité, "
            f"l'inventaire contient {total} document(s), mais la couverture indexée n'a pas pu être déterminée."
        )

    return "La couverture de la base documentaire n'a pas pu être déterminée."
