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

chat_tab, catalogue_tab, instructions_tab = st.tabs(
    ["Questionner Archie", "Catalogue", "Instructions d'Archie"]
)

with catalogue_tab:
    render_catalogue(DATABASE_COVERAGE)

with instructions_tab:
    render_instructions(ARCHIE_INSTRUCTIONS, assistant_name="Archie")

with chat_tab:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Ex. Quels documents parlent de mobilité durable ?")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})

        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Archie fouille les documents..."):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=build_prompt(question),
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
                    st.markdown(answer)

                    linked_documents = build_linked_documents(
                        response,
                        answer_text=answer,
                        inventory=INVENTORY,
                        inventory_by_path=INVENTORY_BY_PATH,
                    )
                    display_linked_documents(linked_documents)

                    with st.expander("Sources techniques détectées"):
                        source_titles = extract_used_source_titles(response)

                        if source_titles:
                            for title in source_titles:
                                st.write("-", title)
                        else:
                            st.write("Aucune source technique détectée dans la réponse.")

                    st.session_state.messages.append({"role": "assistant", "content": answer})

                except Exception as e:
                    error_message = f"Erreur pendant la génération : {e}"
                    st.error(error_message)
                    st.session_state.messages.append({"role": "assistant", "content": error_message})
