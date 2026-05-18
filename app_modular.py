import streamlit as st
from google.genai import types

from src.config import create_gemini_client, load_config
from src.inventory import compute_database_coverage, database_coverage_sentence, load_inventory
from src.local_retrieval import (
    LocalRetrievalUnavailable,
    hits_to_context,
    hits_to_linked_documents,
    search_local,
)
from src.prompts import ARCHIE_INSTRUCTIONS, build_prompt, build_prompt_with_local_context
from src.source_linking import build_linked_documents, extract_used_source_titles
from src.ui import (
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
    page_title="Archie - Assistant documentaire",
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


def generate_with_local_retrieval(question: str, model: str) -> tuple[str, list[dict], list[str]]:
    hits = search_local(
        question=question,
        document_type=st.session_state.get("rag_document_type", "Tous"),
        year=st.session_state.get("rag_year", "Toutes"),
        theme=st.session_state.get("rag_theme", "Tous"),
        top_k=8,
    )
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


def render_coverage_tab(database_coverage: dict) -> None:
    st.markdown("### Couverture de la base")
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
    st.markdown("### Limites d'Archie")
    st.info(
        "Archie peut utiliser soit Gemini File Search, soit un index vectoriel local. "
        "Dans les deux cas, il ne répond qu'à partir des documents disponibles pour le moteur choisi."
    )
    st.markdown(
        """
- En mode Gemini File Search, Archie dépend des quotas et des métadonnées retournées par Gemini.
- En mode Recherche locale, Archie dépend de l'index `chroma_db/` construit localement.
- Si l'index local n'existe pas ou si les dépendances locales ne sont pas installées, il faut utiliser Gemini File Search ou construire l'index.
- Les liens affichés viennent de l'inventaire local et des métadonnées disponibles.
- Une réponse d'Archie doit rester une aide documentaire : elle ne remplace pas une validation juridique, institutionnelle ou éditoriale.
"""
    )


st.title("📚 Archie")
st.caption(
    "Assistant IA du centre de documentation. Un peu speed, très serviable, "
    "et branché sur les documents publics indexés."
)
render_coverage_box(database_coverage_sentence(DATABASE_COVERAGE))

model = render_sidebar(
    config=config,
    inventory=INVENTORY,
    database_coverage=DATABASE_COVERAGE,
)

indexed_rows = DATABASE_COVERAGE.get("indexed_rows", [])
document_types = ["Tous"] + distinct_values(indexed_rows, "document_type")
years = ["Toutes"] + sorted(distinct_values(indexed_rows, "year"), reverse=True)
themes = ["Tous"] + distinct_values(indexed_rows, "theme")

with st.sidebar:
    st.markdown("### Conversation")
    if st.button("Nouvelle conversation"):
        for key in ["messages", "last_question", "last_answer", "last_documents", "last_model", "pending_question"]:
            st.session_state.pop(key, None)
        st.rerun()

    search_engine = st.selectbox(
        "Moteur documentaire",
        ["Recherche locale", "Gemini File Search"],
        index=0,
        help="Recherche locale évite le quota d'embedding Gemini. Gemini File Search garde l'ancien comportement.",
    )

    st.markdown("#### Cadrer la prochaine question")
    st.selectbox("Type", document_types, key="rag_document_type")
    st.selectbox("Année", years, key="rag_year")
    st.selectbox("Thème", themes, key="rag_theme")

    st.markdown("### Questions suggérées")
    for index, suggested_question in enumerate(SUGGESTED_QUESTIONS):
        if st.button(suggested_question, key=f"sidebar_suggested_question_{index}"):
            st.session_state.pending_question = suggested_question
            st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

pending_question = st.session_state.pop("pending_question", None)
chat_question = st.chat_input("Ex. Quels documents parlent de mobilité durable ?")
question = pending_question or chat_question

chat_tab, catalogue_tab, coverage_tab, limits_tab, instructions_tab = st.tabs(
    [
        "Questionner Archie",
        "Catalogue",
        "Couverture",
        "Limites",
        "Instructions d'Archie",
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
            with st.spinner("Archie fouille les documents..."):
                try:
                    if search_engine == "Recherche locale":
                        answer, linked_documents, source_titles = generate_with_local_retrieval(question, model)
                    else:
                        answer, linked_documents, source_titles = generate_with_gemini_file_search(question, model)

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

                except LocalRetrievalUnavailable as e:
                    error_message = f"Recherche locale indisponible : {e}"
                    st.warning(error_message)
                    st.info("Passe temporairement le moteur documentaire sur Gemini File Search, ou construis l'index local.")
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
                except Exception as e:
                    error_message = f"Erreur pendant la génération : {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})

with catalogue_tab:
    render_catalogue(DATABASE_COVERAGE)

with coverage_tab:
    render_coverage_tab(DATABASE_COVERAGE)

with limits_tab:
    render_limits_tab()

with instructions_tab:
    render_instructions(ARCHIE_INSTRUCTIONS, assistant_name="Archie")
