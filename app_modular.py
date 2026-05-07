import streamlit as st
from google.genai import types

from src.config import create_gemini_client, load_config
from src.inventory import compute_database_coverage, database_coverage_sentence, load_inventory
from src.prompts import ARCHIE_INSTRUCTIONS, build_prompt
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
    st.write(f"**Mode de sélection :** `{database_coverage.get('selection_mode', '')}`")
    st.write(f"**Fichier de sélection :** `{database_coverage.get('selection_file', '')}`")
    st.write(f"**Fichier trouvé :** {'oui' if database_coverage.get('selection_file_found') else 'non'}")
    st.write(f"**Document le plus ancien :** {database_coverage.get('oldest_date_fr', 'date inconnue')}")
    st.write(f"**Document le plus récent :** {database_coverage.get('newest_date_fr', 'date inconnue')}")


def render_limits_tab() -> None:
    st.markdown("### Limites d'Archie")
    st.info(
        "Archie ne consulte que les documents indexés dans la base Gemini File Search. "
        "Il ne voit pas automatiquement tout l'inventaire complet."
    )
    st.markdown(
        """
- Archie peut ne pas connaître certains documents non sélectionnés ou non indexés.
- Archie répond à partir des documents retrouvés par File Search, pas à partir d'une recherche web générale.
- Les liens affichés viennent de l'inventaire local et des métadonnées disponibles.
- Une réponse d'Archie doit rester une aide documentaire : elle ne remplace pas une validation juridique, institutionnelle ou éditoriale.
- Les réponses peuvent varier légèrement selon le modèle choisi et les documents retrouvés.
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

with st.sidebar:
    if st.button("Nouvelle conversation"):
        for key in ["messages", "last_question", "last_answer", "last_documents", "last_model", "pending_question"]:
            st.session_state.pop(key, None)
        st.rerun()

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

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    try:
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

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "documents": linked_documents,
                "source_titles": source_titles,
            }
        )

    except Exception as e:
        error_message = f"Erreur pendant la génération : {e}"
        st.session_state.messages.append({"role": "assistant", "content": error_message})

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
    indexed_rows = DATABASE_COVERAGE.get("indexed_rows", [])
    document_types = ["Tous"] + distinct_values(indexed_rows, "document_type")
    years = ["Toutes"] + sorted(distinct_values(indexed_rows, "year"), reverse=True)
    themes = ["Tous"] + distinct_values(indexed_rows, "theme")

    st.markdown("### Cadrer la prochaine question")
    col_type, col_year, col_theme = st.columns(3)
    with col_type:
        st.selectbox("Type", document_types, key="rag_document_type")
    with col_year:
        st.selectbox("Année", years, key="rag_year")
    with col_theme:
        st.selectbox("Thème", themes, key="rag_theme")

    st.markdown("### Conversation")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                display_linked_documents(message.get("documents", []))
                if message.get("source_titles"):
                    with st.expander("Sources techniques détectées"):
                        for title in message.get("source_titles", []):
                            st.write("-", title)

with catalogue_tab:
    render_catalogue(DATABASE_COVERAGE)

with coverage_tab:
    render_coverage_tab(DATABASE_COVERAGE)

with limits_tab:
    render_limits_tab()

with instructions_tab:
    render_instructions(ARCHIE_INSTRUCTIONS, assistant_name="Archie")
