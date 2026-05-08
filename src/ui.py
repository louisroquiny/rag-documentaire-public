import streamlit as st

from src.catalogue import distinct_values, filter_catalogue_rows, inventory_rows


FILE_SEARCH_MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
]

CATALOGUE_FILTER_KEYS = [
    "catalogue_category",
    "catalogue_theme",
    "catalogue_section",
    "catalogue_year",
    "catalogue_query",
]


def display_document_card(doc: dict, show_summary: bool = True) -> None:
    """Affiche une fiche document enrichie."""
    title = doc.get("title") or doc.get("path") or "Document"
    post_url = doc.get("post_url")
    file_url = doc.get("file_url")
    theme_url = doc.get("theme_url")
    source_list_url = doc.get("source_list_url")

    path = doc.get("path")
    category = doc.get("category")
    document_type = doc.get("document_type")
    section = doc.get("section")
    theme = doc.get("theme")
    date = doc.get("date")
    year = doc.get("year")
    summary = doc.get("summary")
    language = doc.get("language")

    st.markdown(f"**{title}**")

    details = []

    if document_type:
        details.append(f"Type : {document_type}")
    if category and category != document_type:
        details.append(f"Catégorie : {category}")
    if section:
        details.append(f"Section : {section}")
    if theme:
        details.append(f"Thème : {theme}")
    if date:
        details.append(f"Date : {date}")
    elif year:
        details.append(f"Année : {year}")
    if language:
        details.append(f"Langue : {language}")
    if path:
        details.append(f"Fichier : `{path}`")

    if details:
        st.caption(" · ".join(details))

    if show_summary and summary:
        st.write(summary)

    links = []
    if post_url:
        links.append(f"[Voir l'article]({post_url})")
    if file_url:
        links.append(f"[Télécharger le PDF]({file_url})")
    if theme_url:
        links.append(f"[Voir le thème]({theme_url})")
    if source_list_url:
        links.append(f"[Page de liste]({source_list_url})")

    if links:
        st.markdown(" · ".join(links))


def display_linked_documents(linked_documents: list[dict]) -> None:
    """Affiche une version compacte des documents cités sous la réponse."""
    if not linked_documents:
        st.caption("Aucun lien documentaire associé n'a été trouvé.")
        return

    unique_docs = []
    seen = set()

    for doc in linked_documents:
        key = doc.get("file_url") or doc.get("post_url") or doc.get("path") or doc.get("title")

        if not key or key in seen:
            continue

        seen.add(key)
        unique_docs.append(doc)

    if not unique_docs:
        st.caption("Aucun lien documentaire associé n'a été trouvé.")
        return

    with st.expander(f"Documents cités ({len(unique_docs)})", expanded=False):
        for doc in unique_docs:
            title = doc.get("title") or doc.get("filename") or doc.get("path") or "Document"
            document_type = doc.get("document_type") or doc.get("category")
            year = doc.get("year")
            date = doc.get("date") or doc.get("date_iso")
            post_url = doc.get("post_url")
            file_url = doc.get("file_url")

            meta = " · ".join(str(x) for x in [document_type, date or year] if x)
            links = []

            if post_url:
                links.append(f"[article]({post_url})")
            if file_url:
                links.append(f"[PDF]({file_url})")

            suffix = " · ".join(links)
            line = f"- **{title}**"

            if meta:
                line += f" — {meta}"
            if suffix:
                line += f" · {suffix}"

            st.markdown(line)


def _filter_for_options(
    rows: list[dict],
    category: str,
    theme: str,
    section: str,
    year: str,
    exclude: str,
) -> list[dict]:
    """Filtre les lignes pour calculer les options disponibles d'un champ."""
    filtered = rows

    if exclude != "category" and category != "Toutes":
        filtered = [row for row in filtered if str(row.get("category", "")).strip() == category]
    if exclude != "theme" and theme != "Tous":
        filtered = [row for row in filtered if str(row.get("theme", "")).strip() == theme]
    if exclude != "section" and section != "Toutes":
        filtered = [row for row in filtered if str(row.get("section", "")).strip() == section]
    if exclude != "year" and year != "Toutes":
        filtered = [row for row in filtered if str(row.get("year", "")).strip() == year]

    return filtered


def _selectbox_with_valid_default(label: str, options: list[str], key: str, default: str) -> str:
    current = st.session_state.get(key, default)
    if current not in options:
        current = default
        st.session_state[key] = default

    return st.selectbox(label, options, index=options.index(current), key=key)


def _reset_catalogue_filters() -> None:
    defaults = {
        "catalogue_category": "Toutes",
        "catalogue_theme": "Tous",
        "catalogue_section": "Toutes",
        "catalogue_year": "Toutes",
        "catalogue_query": "",
    }
    for key, value in defaults.items():
        st.session_state[key] = value


def _sort_catalogue_rows(rows: list[dict], sort_mode: str) -> list[dict]:
    if sort_mode == "Date ancienne":
        return sorted(rows, key=lambda row: row.get("date_iso") or row.get("date") or "")
    if sort_mode == "Type":
        return sorted(rows, key=lambda row: (row.get("document_type") or row.get("category") or "", row.get("title") or ""))
    if sort_mode == "Thème":
        return sorted(rows, key=lambda row: (row.get("theme") or "", row.get("title") or ""))
    return sorted(rows, key=lambda row: row.get("date_iso") or row.get("date") or "", reverse=True)


def render_catalogue(database_coverage: dict) -> None:
    rows = inventory_rows(database_coverage)

    if not rows:
        st.info("Catalogue indisponible : inventaire non chargé.")
        return

    col_reset, col_sort = st.columns([1, 2])
    with col_reset:
        st.button("Réinitialiser les filtres", on_click=_reset_catalogue_filters)
    with col_sort:
        sort_mode = st.selectbox(
            "Trier par",
            ["Date récente", "Date ancienne", "Type", "Thème"],
            key="catalogue_sort_mode",
        )

    current_category = st.session_state.get("catalogue_category", "Toutes")
    current_theme = st.session_state.get("catalogue_theme", "Tous")
    current_section = st.session_state.get("catalogue_section", "Toutes")
    current_year = st.session_state.get("catalogue_year", "Toutes")

    category_options = ["Toutes"] + distinct_values(
        _filter_for_options(rows, current_category, current_theme, current_section, current_year, exclude="category"),
        "category",
    )
    theme_options = ["Tous"] + distinct_values(
        _filter_for_options(rows, current_category, current_theme, current_section, current_year, exclude="theme"),
        "theme",
    )
    section_options = ["Toutes"] + distinct_values(
        _filter_for_options(rows, current_category, current_theme, current_section, current_year, exclude="section"),
        "section",
    )
    year_options = ["Toutes"] + sorted(
        distinct_values(
            _filter_for_options(rows, current_category, current_theme, current_section, current_year, exclude="year"),
            "year",
        ),
        reverse=True,
    )

    selected_category = _selectbox_with_valid_default("Catégorie", category_options, "catalogue_category", "Toutes")
    selected_theme = _selectbox_with_valid_default("Thème", theme_options, "catalogue_theme", "Tous")
    selected_section = _selectbox_with_valid_default("Section", section_options, "catalogue_section", "Toutes")
    selected_year = _selectbox_with_valid_default("Année", year_options, "catalogue_year", "Toutes")

    catalogue_query = st.text_input(
        "Recherche dans le catalogue",
        "",
        key="catalogue_query",
        placeholder="Ex. mobilité, carbone, salaires...",
    )

    filtered = filter_catalogue_rows(
        rows=rows,
        category=selected_category,
        theme=selected_theme,
        section=selected_section,
        year=selected_year,
        query=catalogue_query,
    )

    filtered = _sort_catalogue_rows(filtered, sort_mode)

    st.caption(f"{len(filtered)} document(s) trouvé(s) dans les documents indexés")

    with st.expander("Afficher le catalogue des documents indexés", expanded=False):
        for row in filtered[:200]:
            display_document_card(row)
            st.markdown("---")

        if len(filtered) > 200:
            st.info("Affichage limité aux 200 premiers résultats. Affine les filtres pour voir moins de documents.")


def render_sidebar(config, inventory: dict, database_coverage: dict) -> str:
    with st.sidebar:
        st.header("Paramètres")

        model = st.selectbox(
            "Modèle",
            FILE_SEARCH_MODELS,
            index=0,
            help="Seuls les modèles compatibles avec Gemini File Search sont listés ici.",
        )

        st.markdown("### Base documentaire")
        st.code(config.file_search_store)

        st.markdown("### Inventaire")
        if not inventory:
            st.warning("Inventaire non trouvé ou vide")

        indexed = database_coverage.get("indexed_documents", 0)
        total = database_coverage.get("total_documents", 0)
        if total:
            st.success(f"{indexed} document(s) indexé(s) sur {total} dans l'inventaire")

        st.markdown("### Conseils")
        st.write("Pose une question précise : thème, période, type de document, recommandation, position ou comparaison.")

    return model


def render_coverage_box(message: str) -> None:
    st.info(message)


def render_instructions(instructions: str, assistant_name: str = "Archie") -> None:
    st.markdown(f"### Instructions de {assistant_name}")
    st.caption("Ces instructions sont celles envoyées au modèle avant chaque question.")
    st.code(instructions, language="markdown")
