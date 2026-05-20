import streamlit as st
from google.genai import types

from src.config import create_gemini_client, load_config
from src.inventory import compute_database_coverage, database_coverage_sentence, load_inventory
from src.local_api_client import (
    LocalSearchApiUnavailable,
    get_local_api_documents,
    get_local_api_stats,
    search_local_api,
)
from src.local_retrieval import (
    LocalRetrievalUnavailable,
    get_local_index_documents,
    get_local_index_stats,
    hits_to_context,
    hits_to_linked_documents,
    search_local,
)
from src.prompts import HECTOR_INSTRUCTIONS, build_prompt, build_prompt_with_local_context
from src.source_linking import build_linked_documents, extract_used_source_titles
from src.ui import (
    display_document_card,
    display_linked_documents,
    render_catalogue,
    render_coverage_box,
    render_instructions,
    render_sidebar,
)


DEFAULT_TEMPERATURE = 0.1
SUGGESTED_QUESTIONS = [
    "Quels documents récents parlent de mobilité durable ?",
    "Quels avis concernent la TVA ?",
    "Quels documents traitent du pouvoir d'achat depuis 2024 ?",
    "Résume les documents sur la rénovation énergétique.",
    "Quels rapports concernent le secteur de la construction ?",
    "Quels documents parlent du budget mobilité ?",
]


st.set_page_config(
    page_title="Hector - Assistant documentaire",
    page_icon="📚",
    layout="wide",
)


config = load_config()
client = create_gemini_client(config)

INVENTORY, INVENTORY_BY_PATH = load_inventory(
    json_file=config.inventory_json_file,
    csv_file=config.inventory_csv_file,
)
DATABASE_COVERAGE = compute_database_coverage(
    inventory=INVENTORY,
    inventory_by_path=INVENTORY_BY_PATH,
    selection_file=config.file_search_selection_file,
    data_dir=config.data_dir,
)


def distinct_values(rows: list[dict], key: str) -> list[str]:
    return sorted(
        {
            str(row.get(key, "")).strip()
            for row in rows
            if str(row.get(key, "")).strip()
        }
    )


def build_user_constraints() -> str:
    constraints = []

    document_type = st.session_state.get("rag_document_type", "Tous")
    year = st.session_state.get("rag_year", "Toutes")
    theme = st.session_state.get("rag_theme", "Tous")

    if document_type != "Tous":
        constraints.append(f"- Type de document à privilégier : {document_type}.")
    if year != "Toutes":
        constraints.append(f"- Année à privilégier : {year}.")
    if theme != "Tous":
        constraints.append(f"- Thème à privilégier : {theme}.")

    return "\n".join(constraints)


@st.cache_data(ttl=60, show_spinner=False)
def get_api_stats_cached() -> dict:
    return get_local_api_stats()


@st.cache_data(ttl=60, show_spinner=False)
def get_api_documents_cached() -> list[dict]:
    return get_local_api_documents()


@st.cache_data(ttl=60, show_spinner=False)
def get_local_stats_cached() -> dict:
    return get_local_index_stats()


@st.cache_data(ttl=60, show_spinner=False)
def get_local_documents_cached() -> list[dict]:
    return get_local_index_documents()


def get_active_engine_data(search_engine: str) -> tuple[dict | None, list[dict] | None, str | None]:
    if search_engine == "API locale":
        try:
            return get_api_stats_cached(), get_api_documents_cached(), None
        except LocalSearchApiUnavailable as e:
            return None, None, str(e)

    if search_engine == "Recherche locale directe":
        try:
            return get_local_stats_cached(), get_local_documents_cached(), None
        except LocalRetrievalUnavailable as e:
            return None, None, str(e)

    return None, DATABASE_COVERAGE.get("indexed_rows", []), None


def build_active_coverage(search_engine: str, stats: dict | None) -> dict | None:
    if search_engine == "API locale" and stats:
        return {
            "engine": "api",
            "label": f"API locale Chroma / {stats.get('collection', 'chroma')}",
            "indexed_documents": stats.get("indexed_documents", 0),
            "total_documents": stats.get("indexed_documents", 0),
            "chunk_count": stats.get("chunk_count", 0),
        }

    if search_engine == "Recherche locale directe" and stats:
        return {
            "engine": "local",
            "label": f"Chroma local / {stats.get('collection', 'chroma')}",
            "indexed_documents": stats.get("indexed_documents", 0),
            "total_documents": stats.get("indexed_documents", 0),
            "chunk_count": stats.get("chunk_count", 0),
        }

    return {
        "engine": "file_search",
        "label": config.file_search_store,
    }


def get_active_coverage_message(search_engine: str, stats: dict | None, error: str | None = None) -> str:
    if search_engine == "API locale":
        if error:
            return f"API locale configurée, mais statistiques Chroma indisponibles : {error}"
        if stats:
            indexed = stats.get("indexed_documents", 0)
            chunks = stats.get("chunk_count", 0)
            collection = stats.get("collection", "chroma")
            oldest = stats.get("oldest_document") or "date inconnue"
            return (
                f"Base Chroma utilisée via API locale : {indexed} document(s) indexé(s), "
                f"{chunks} extrait(s) vectorisé(s), collection `{collection}`. "
                f"Les documents consultables remontent jusqu'au {oldest}."
            )

    if search_engine == "Recherche locale directe":
        if error:
            return f"Recherche locale directe sélectionnée, mais statistiques Chroma indisponibles : {error}"
        if stats:
            indexed = stats.get("indexed_documents", 0)
            chunks = stats.get("chunk_count", 0)
            collection = stats.get("collection", "chroma")
            oldest = stats.get("oldest_document") or "date inconnue"
            return (
                f"Base Chroma locale : {indexed} document(s) indexé(s), "
                f"{chunks} extrait(s) vectorisé(s), collection `{collection}`. "
                f"Les documents consultables remontent jusqu'au {oldest}."
            )

    return database_coverage_sentence(DATABASE_COVERAGE)


def generate_with_gemini_file_search(question: str, model: str) -> tuple[str, list[dict], list[str]]:
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(question, constraints=build_user_constraints()),
        config=types.GenerateContentConfig(
            temperature=DEFAULT_TEMPERATURE,
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[config.file_search_store]
                    )
                )
            ],
        ),
    )

    answer = response.text or "Aucune réponse générée."
    linked_documents = build_linked_documents(
        response,
        answer_text=answer,
        inventory=INVENTORY,
        inventory_by_path=INVENTORY_BY_PATH,
    )
    source_titles = extract_used_source_titles(response)
    return answer, linked_documents, source_titles


def generate_from_hits(question: str, model: str, hits: list[dict]) -> tuple[str, list[dict], list[str]]:
    context = hits_to_context(hits)
    linked_documents = hits_to_linked_documents(hits)
    response = client.models.generate_content(
        model=model,
        contents=build_prompt_with_local_context(
            question=question,
            context=context,
            constraints=build_user_constraints(),
        ),
        config=types.GenerateContentConfig(temperature=DEFAULT_TEMPERATURE),
    )
    answer = response.text or "Aucune réponse générée."
    source_titles = [doc.get("title") or doc.get("path") for doc in linked_documents if doc.get("title") or doc.get("path")]
    return answer, linked_documents, source_titles


def generate_with_local_retrieval(question: str, model: str) -> tuple[str, list[dict], list[str]]:
    hits = search_local(
        question=question,
        document_type=st.session_state.get("rag_document_type", "Tous"),
        year=st.session_state.get("rag_year", "Toutes"),
        theme=st.session_state.get("rag_theme", "Tous"),
        top_k=8,
    )
    return generate_from_hits(question, model, hits)


def generate_with_local_api(question: str, model: str) -> tuple[str, list[dict], list[str]]:
    hits = search_local_api(
        question=question,
        document_type=st.session_state.get("rag_document_type", "Tous"),
        year=st.session_state.get("rag_year", "Toutes"),
        theme=st.session_state.get("rag_theme", "Tous"),
        top_k=8,
    )
    return generate_from_hits(question, model, hits)


def render_active_catalogue(search_engine: str, rows: list[dict] | None) -> None:
    if search_engine == "Gemini File Search":
        render_catalogue(DATABASE_COVERAGE)
        return

    st.markdown(f"### Catalogue — {search_engine}")

    if rows is None:
        st.warning("Catalogue Chroma indisponible : impossible de récupérer les documents indexés.")
        return

    if not rows:
        st.info("Aucun document trouvé dans le catalogue Chroma.")
        return

    st.caption(f"{len(rows)} document(s) disponible(s) dans le moteur sélectionné")

    for row in rows[:200]:
        display_document_card(row)
        st.markdown("---")

    if len(rows) > 200:
        st.info("Affichage limité aux 200 premiers résultats. Utilise les filtres de la question ou affine le catalogue dans une version ultérieure.")


def render_coverage_tab(database_coverage: dict, search_engine: str, stats: dict | None, error: str | None) -> None:
    st.markdown("### Couverture de la base")

    if search_engine in ["API locale", "Recherche locale directe"]:
        if error:
            st.warning(f"Statistiques Chroma indisponibles : {error}")
        elif stats:
            col1, col2, col3 = st.columns(3)
            col1.metric("Documents Chroma", stats.get("indexed_documents", 0))
            col2.metric("Extraits vectorisés", stats.get("chunk_count", 0))
            col3.metric("Moteur", search_engine)
            st.info(get_active_coverage_message(search_engine, stats, error))
            st.write(f"**Collection Chroma :** `{stats.get('collection', '')}`")
            st.write(f"**Document le plus ancien :** {stats.get('oldest_document') or 'date inconnue'}")
            st.write(f"**Document le plus récent :** {stats.get('newest_document') or 'date inconnue'}")
            return

    col1, col2, col3 = st.columns(3)
    col1.metric("Documents inventoriés", database_coverage.get("total_documents", 0))
    col2.metric("Documents indexés", database_coverage.get("indexed_documents", 0))
    col3.metric(
        "Documents non indexés",
        max(0, database_coverage.get("total_documents", 0) - database_coverage.get("indexed_documents", 0)),
    )

    st.info(database_coverage_sentence(database_coverage))
    selection_mode = database_coverage.get("selection_mode", "")
    selection_mode_label = "Sélection limitée" if selection_mode == "selection" else "Inventaire complet"
    selection_file_found = database_coverage.get("selection_file_found")

    st.write(f"**Mode de sélection :** {selection_mode_label}")
    st.write(f"**Fichier de sélection :** `{database_coverage.get('selection_file', '')}`")
    st.write(f"**Fichier de sélection trouvé :** {'oui' if selection_file_found else 'non'}")
    st.write(f"**Document le plus ancien :** {database_coverage.get('oldest_date_fr', 'date inconnue')}")
    st.write(f"**Document le plus récent :** {database_coverage.get('newest_date_fr', 'date inconnue')}")


def render_limits_tab() -> None:
    st.markdown("### Limites d'Hector")
    st.info(
        "Hector peut utiliser Gemini File Search, un index vectoriel local direct, ou une API locale. "
        "Dans tous les cas, il ne répond qu'à partir des documents disponibles pour le moteur choisi."
    )
    st.markdown(
        """
- En mode Gemini File Search, Hector dépend des quotas et des métadonnées retournées par Gemini.
- En mode Recherche locale directe, Hector dépend de l'index `chroma_db/` présent sur la même machine que Streamlit.
- En mode API locale, Hector interroge une API interne qui accède à `chroma_db/` côté serveur.
- Si l'index local n'existe pas ou si les dépendances locales ne sont pas installées, il faut utiliser Gemini File Search, construire l'index, ou configurer l'API locale.
- Les liens affichés viennent de l'inventaire local et des métadonnées disponibles.
- Une réponse d'Hector doit rester une aide documentaire : elle ne remplace pas une validation juridique, institutionnelle ou éditoriale.
"""
    )


st.title("📚 Hector")
st.caption(
    "Assistant IA du centre de documentation. Un peu speed, très serviable, "
    "et branché sur les documents publics indexés."
)

with st.sidebar:
    st.markdown("### Conversation")
    search_engine = st.selectbox(
        "Moteur documentaire",
        ["API locale", "Recherche locale directe", "Gemini File Search"],
        index=0,
        help="API locale interroge le serveur interne. Recherche locale directe lit chroma_db sur la même machine. Gemini File Search garde l'ancien comportement.",
    )

active_stats, active_rows, active_error = get_active_engine_data(search_engine)
active_coverage = build_active_coverage(search_engine, active_stats)

model = render_sidebar(
    config=config,
    inventory=INVENTORY,
    database_coverage=DATABASE_COVERAGE,
    active_coverage=active_coverage,
)

filter_rows = active_rows or []
document_types = ["Tous"] + distinct_values(filter_rows, "document_type")
years = ["Toutes"] + sorted(distinct_values(filter_rows, "year"), reverse=True)
themes = ["Tous"] + distinct_values(filter_rows, "theme")

with st.sidebar:
    if st.button("Nouvelle conversation"):
        for key in ["messages", "last_question", "last_answer", "last_documents", "last_model", "pending_question"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.markdown("#### Cadrer la prochaine question")
    st.selectbox("Type", document_types, key="rag_document_type")
    st.selectbox("Année", years, key="rag_year")
    st.selectbox("Thème", themes, key="rag_theme")

    st.markdown("### Questions suggérées")
    for index, suggested_question in enumerate(SUGGESTED_QUESTIONS):
        if st.button(suggested_question, key=f"sidebar_suggested_question_{index}"):
            st.session_state.pending_question = suggested_question
            st.rerun()

render_coverage_box(get_active_coverage_message(search_engine, active_stats, active_error))

if "messages" not in st.session_state:
    st.session_state.messages = []

pending_question = st.session_state.pop("pending_question", None)
chat_question = st.chat_input("Ex. Quels documents parlent de mobilité durable ?")
question = pending_question or chat_question

chat_tab, catalogue_tab, coverage_tab, limits_tab, instructions_tab = st.tabs(
    [
        "Questionner Hector",
        "Catalogue",
        "Couverture",
        "Limites",
        "Instructions d'Hector",
    ]
)

with chat_tab:
    st.markdown("### Conversation")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if "documents" in message:
                    display_linked_documents(message.get("documents", []))
                if message.get("source_titles"):
                    with st.expander("Sources techniques détectées"):
                        for title in message.get("source_titles", []):
                            st.write("-", title)

    if question:
        st.session_state.messages.append({"role": "user", "content": question})

        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Hector fouille les documents..."):
                try:
                    if search_engine == "API locale":
                        answer, linked_documents, source_titles = generate_with_local_api(question, model)
                    elif search_engine == "Recherche locale directe":
                        answer, linked_documents, source_titles = generate_with_local_retrieval(question, model)
                    else:
                        answer, linked_documents, source_titles = generate_with_gemini_file_search(question, model)

                    st.caption(f"Moteur utilisé : {search_engine}")
                    st.markdown(answer)
                    display_linked_documents(linked_documents)

                    with st.expander("Sources techniques détectées"):
                        if source_titles:
                            for title in source_titles:
                                st.write("-", title)
                        else:
                            st.write("Aucune source technique détectée dans la réponse.")

                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": answer,
                            "documents": linked_documents,
                            "source_titles": source_titles,
                        }
                    )

                except LocalSearchApiUnavailable as e:
                    error_message = f"API locale indisponible : {e}"
                    st.warning(error_message)
                    st.info("Vérifie LOCAL_SEARCH_API_URL / LOCAL_SEARCH_API_TOKEN, ou passe temporairement sur Recherche locale directe ou Gemini File Search.")
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                except LocalRetrievalUnavailable as e:
                    error_message = f"Recherche locale directe indisponible : {e}"
                    st.warning(error_message)
                    st.info("Passe temporairement le moteur documentaire sur API locale ou Gemini File Search, ou construis l'index local.")
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                except Exception as e:
                    error_message = f"Erreur pendant la génération : {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})

with catalogue_tab:
    render_active_catalogue(search_engine, active_rows)

with coverage_tab:
    render_coverage_tab(DATABASE_COVERAGE, search_engine, active_stats, active_error)

with limits_tab:
    render_limits_tab()

with instructions_tab:
    render_instructions(HECTOR_INSTRUCTIONS, assistant_name="Hector")
