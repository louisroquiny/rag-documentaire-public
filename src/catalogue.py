def inventory_rows(database_coverage: dict) -> list[dict]:
    """
    Retourne les lignes du catalogue affichable.
    Par defaut, il s'agit des documents selectionnes/indexes dans Gemini.
    """
    return list(database_coverage.get("indexed_rows") or [])


def distinct_values(rows: list[dict], key: str) -> list[str]:
    return sorted(
        {
            str(row.get(key, "")).strip()
            for row in rows
            if str(row.get(key, "")).strip()
        }
    )


def filter_catalogue_rows(
    rows: list[dict],
    category: str,
    theme: str,
    section: str,
    year: str,
    query: str,
) -> list[dict]:
    filtered = rows

    if category != "Toutes":
        filtered = [row for row in filtered if str(row.get("category", "")).strip() == category]

    if theme != "Tous":
        filtered = [row for row in filtered if str(row.get("theme", "")).strip() == theme]

    if section != "Toutes":
        filtered = [row for row in filtered if str(row.get("section", "")).strip() == section]

    if year != "Toutes":
        filtered = [row for row in filtered if str(row.get("year", "")).strip() == year]

    query = (query or "").lower().strip()

    if query:
        filtered = [
            row for row in filtered
            if query in str(row.get("title", "")).lower()
            or query in str(row.get("summary", "")).lower()
            or query in str(row.get("theme", "")).lower()
            or query in str(row.get("section", "")).lower()
            or query in str(row.get("category", "")).lower()
            or query in str(row.get("document_type", "")).lower()
            or query in str(row.get("date", "")).lower()
            or query in str(row.get("year", "")).lower()
            or query in str(row.get("path", "")).lower()
        ]

    return filtered
