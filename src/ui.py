import streamlit as st

from src.catalogue import distinct_values, filter_catalogue_rows, inventory_rows


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


def render_catalogue(database_coverage: dict) -> None:
    rows = inventory_rows(database_coverage)

    if not rows:
        st.info("Catalogue indisponible : inventaire non chargé.")
        return

    categories = ["Toutes"] + distinct_values(rows, "category")
    themes = ["Tous"] + distinct_values(rows, "theme")
    sections = ["Toutes"] + distinct_values(rows, "section")
    years = ["Toutes"] + sorted(distinct_values(rows, "year"), reverse=True)

    selected_category = st.selectbox("Catégorie", categories, key="catalogue_category")
    selected_theme = st.selectbox("Thème", themes, key="catalogue_theme")
    selected_section = st.selectbox("Section", sections, key="catalogue_section")
    selected_year = st.selectbox("Année", years, key="catalogue_year")

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

    filtered = sorted(filtered, key=lambda row: row.get("date_iso") or row.get("date") or "", reverse=True)

    st.caption(f"{len(filtered)} document(s) trouvé(s) dans les documents indexés")

    with st.expander("Afficher le catalogue des documents indexés", expanded=False):
        for row in filtered[:200]:
            display_document_card(row)
            st.markdown("---")

        if len(filtered) > 200:
            st.info("Affichage limité aux 200 premiers résultats. Affine les filtres pour voir moins de documents.")


def render_sidebar(config, inventory: dict, database_coverage: dict) -> tuple[str, float]:
    with st.sidebar:
        st.header("Paramètres")

        file_search_models = [
            "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-3.1-pro-preview",
        ]

        model = st.selectbox(
            "Modèle",
            file_search_models,
            index=0,
            help="Seuls les modèles compatibles avec Gemini File Search sont listés ici.",
        )

        temperature = st.slider(
            "Température",
            min_value=0.0,
            max_value=1.0,
            value=0.1,
            step=0.1,
            help="Plus la valeur est basse, plus les réponses sont stables et factuelles.",
        )

        st.markdown("### Base documentaire")
        st.code(config.file_search_store)

        st.markdown("### Inventaire")
        if inventory:
            st.success(f"{len(inventory)} document(s) chargés depuis l'inventaire")
        else:
            st.warning("Inventaire non trouvé ou vide")

        indexed = database_coverage.get("indexed_documents", 0)
        total = database_coverage.get("total_documents", 0)
        if total:
            st.info(f"{indexed} document(s) indexé(s) sur {total} dans l'inventaire")

        st.markdown("### Conseils")
        st.write("Pose une question précise : thème, période, type de document, recommandation, position ou comparaison.")

    return model, temperature
