from src.inventory import normalize_path


def get_attr_or_key(obj, name: str, default=None):
    """Compatible avec les objets SDK Gemini et les dicts."""
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    try:
        return getattr(obj, name)
    except Exception:
        return default


def metadata_item_to_pair(item) -> tuple[str | None, str | None]:
    """
    Lit une entrée custom_metadata Gemini :
    {"key": "...", "string_value": "..."}
    ou l'équivalent objet SDK.
    """
    key = get_attr_or_key(item, "key")

    if not key:
        return None, None

    for value_key in [
        "string_value",
        "numeric_value",
        "bool_value",
        "stringValue",
        "numericValue",
        "boolValue",
        "value",
    ]:
        value = get_attr_or_key(item, value_key)

        if value not in (None, ""):
            return str(key), str(value)

    return str(key), ""


def custom_metadata_to_dict(custom_metadata) -> dict:
    """Transforme retrieved_context.custom_metadata en dict Python simple."""
    result: dict[str, str] = {}

    if not custom_metadata:
        return result

    if isinstance(custom_metadata, dict):
        custom_metadata = (
            custom_metadata.get("custom_metadata")
            or custom_metadata.get("customMetadata")
            or custom_metadata.get("metadata")
            or [custom_metadata]
        )

    try:
        items = list(custom_metadata)
    except Exception:
        return result

    for item in items:
        key, value = metadata_item_to_pair(item)

        if key:
            result[key] = value or ""

    return result


def extract_custom_metadata_from_context(retrieved_context) -> dict:
    """Essaie de récupérer les métadonnées attachées au document File Search."""
    if not retrieved_context:
        return {}

    for attr in ["custom_metadata", "customMetadata", "metadata"]:
        value = get_attr_or_key(retrieved_context, attr)
        parsed = custom_metadata_to_dict(value)

        if parsed:
            return parsed

    return {}


def find_inventory_row_from_metadata(meta: dict | None, inventory_by_path: dict) -> dict | None:
    """
    Retrouve une ligne d'inventaire via le path des custom_metadata Gemini.
    """
    if not meta:
        return None

    for key in [normalize_path(meta.get("path")), normalize_path(meta.get("relative_path"))]:
        if key and key in inventory_by_path:
            return inventory_by_path[key]

    if any(meta.get(k) for k in ["title", "post_url", "file_url", "path", "relative_path"]):
        return {
            "id": meta.get("id", ""),
            "category": meta.get("category", ""),
            "document_type": meta.get("document_type", meta.get("category", "")),
            "section": meta.get("section", ""),
            "title": meta.get("title", "") or meta.get("path", "") or "Document",
            "theme": meta.get("theme", ""),
            "theme_url": meta.get("theme_url", ""),
            "summary": meta.get("summary", ""),
            "date": meta.get("date", ""),
            "date_iso": meta.get("date_iso", ""),
            "year": meta.get("year", ""),
            "post_url": meta.get("post_url", ""),
            "file_url": meta.get("file_url", ""),
            "path": meta.get("path", "") or meta.get("relative_path", ""),
            "filename": meta.get("filename", ""),
            "language": meta.get("language", ""),
            "source_list_url": meta.get("source_list_url", ""),
        }

    return None


def find_inventory_row_from_title(source_title: str | None, inventory_by_path: dict) -> dict | None:
    """
    Essaie de retrouver une ligne d'inventaire à partir d'une source Gemini,
    uniquement par path normalisé.
    """
    if not source_title:
        return None

    source_path = normalize_path(source_title)

    if source_path in inventory_by_path:
        return inventory_by_path[source_path]

    for path_key, row in inventory_by_path.items():
        if path_key and path_key in source_path:
            return row

    for path_key, row in inventory_by_path.items():
        if source_path and source_path in path_key:
            return row

    return None


def find_inventory_row_from_text(text: str | None, inventory: dict, inventory_by_path: dict) -> dict | None:
    """
    Fallback prudent : retrouve une ligne si le titre exact du document apparaît dans le texte.
    """
    if not text:
        return None

    text_lower = str(text).lower().strip()

    if not text_lower:
        return None

    rows = inventory_by_path.values() if inventory_by_path else inventory.values()

    for row in rows:
        title = str(row.get("title", "")).lower().strip()

        if title and title in text_lower:
            return row

    for row in rows:
        title = str(row.get("title", "")).lower().strip()

        if title and text_lower in title and len(text_lower) >= 20:
            return row

    return None


def extract_used_sources(response) -> list[dict]:
    """
    Extrait les sources utilisées par Gemini File Search.
    """
    sources: list[dict] = []

    try:
        grounding = response.candidates[0].grounding_metadata
    except Exception:
        return sources

    chunks = getattr(grounding, "grounding_chunks", None) or []

    for chunk in chunks:
        retrieved_context = getattr(chunk, "retrieved_context", None)

        if not retrieved_context:
            continue

        title = getattr(retrieved_context, "title", None)
        uri = getattr(retrieved_context, "uri", None)
        metadata = extract_custom_metadata_from_context(retrieved_context)

        sources.append(
            {
                "source_title": title or "",
                "source_uri": uri or "",
                "metadata": metadata,
            }
        )

    return sources


def extract_used_source_titles(response) -> list[str]:
    """Extrait les titres ou noms de documents utilisés par Gemini File Search."""
    titles: list[str] = []
    seen: set[str] = set()

    for source in extract_used_sources(response):
        for candidate in [source.get("source_title"), source.get("source_uri")]:
            if candidate and candidate not in seen:
                titles.append(candidate)
                seen.add(candidate)

    return titles


def build_linked_documents(
    response,
    answer_text: str = "",
    inventory: dict | None = None,
    inventory_by_path: dict | None = None,
) -> list[dict]:
    """
    Construit la liste des documents cités avec liens article/PDF.
    """
    inventory = inventory or {}
    inventory_by_path = inventory_by_path or {}
    linked_documents: list[dict] = []
    seen_keys: set[str] = set()

    def add_row(row: dict | None, source_title: str = ""):
        if not row:
            return

        key = row.get("file_url") or row.get("post_url") or row.get("path") or row.get("title") or source_title

        if not key or key in seen_keys:
            return

        seen_keys.add(key)
        linked_documents.append(
            {
                "id": row.get("id", ""),
                "title": row.get("title") or source_title or "Document",
                "post_url": row.get("post_url"),
                "file_url": row.get("file_url"),
                "path": row.get("path", ""),
                "category": row.get("category", ""),
                "document_type": row.get("document_type", row.get("category", "")),
                "section": row.get("section", ""),
                "theme": row.get("theme", ""),
                "theme_url": row.get("theme_url", ""),
                "summary": row.get("summary", ""),
                "date": row.get("date", ""),
                "date_iso": row.get("date_iso", ""),
                "year": row.get("year", ""),
                "filename": row.get("filename", ""),
                "language": row.get("language", ""),
                "source_list_url": row.get("source_list_url", ""),
                "source_title": source_title,
            }
        )

    for source in extract_used_sources(response):
        metadata = source.get("metadata") or {}
        source_title = source.get("source_title") or source.get("source_uri") or ""

        row = find_inventory_row_from_metadata(metadata, inventory_by_path)
        if not row:
            row = find_inventory_row_from_title(source_title, inventory_by_path)
        if not row and source.get("source_uri"):
            row = find_inventory_row_from_title(source.get("source_uri"), inventory_by_path)
        if not row:
            row = find_inventory_row_from_text(source_title, inventory, inventory_by_path)
        if not row and source.get("source_uri"):
            row = find_inventory_row_from_text(source.get("source_uri"), inventory, inventory_by_path)

        add_row(row, source_title)

    answer_lower = (answer_text or "").lower()

    if answer_lower:
        rows = inventory_by_path.values() if inventory_by_path else inventory.values()

        for row in rows:
            path = str(row.get("path", "")).strip()
            title = str(row.get("title", "")).strip()
            path_lower = normalize_path(path)
            title_lower = title.lower()

            if (path_lower and path_lower in answer_lower) or (title_lower and title_lower in answer_lower):
                add_row(row, title or path)

    return linked_documents
