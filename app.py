import os

import streamlit as st
from google import genai
from google.genai import types


st.set_page_config(
    page_title="RAG documentaire public",
    page_icon="📚",
    layout="wide",
)


def get_secret(name: str, default: str | None = None) -> str | None:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
FILE_SEARCH_STORE = get_secret("FILE_SEARCH_STORE")

if not GEMINI_API_KEY:
    st.error("Secret manquant : GEMINI_API_KEY")
    st.stop()

if not FILE_SEARCH_STORE:
    st.error("Secret manquant : FILE_SEARCH_STORE")
    st.stop()


client = genai.Client(api_key=GEMINI_API_KEY)


st.title("📚 Assistant documentaire public")
st.caption(
    "Pose une question sur les avis, rapports, notes et documents publics indexés."
)

with st.sidebar:
    st.header("Paramètres")
    model = st.selectbox(
        "Modèle",
        [
   	    "gemini-2.5-flash-lite",
            "gemini-3.1-flash-lite-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-3.1-pro-preview",
        ],
        index=0,
    )

    st.markdown("### Conseils")
    st.write(
        "Pose des questions précises : thème, période, type de document, recommandation, position, comparaison."
    )

    st.markdown("### Store utilisé")
    st.code(FILE_SEARCH_STORE)


if "messages" not in st.session_state:
    st.session_state.messages = []


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


question = st.chat_input("Ex. Quels documents parlent de mobilité durable ?")

if question:
    st.session_state.messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Recherche dans les documents et génération de la réponse..."):
            prompt = f"""
Tu es un assistant documentaire d'une institution.

Réponds uniquement à partir des documents retrouvés par la recherche de fichiers.
N'invente pas d'information.
Si les documents ne permettent pas de répondre, dis-le clairement.

Réponds en français.
Sois précis, neutre et factuel.
Structure la réponse avec des puces si utile.
Mentionne les noms des sources ou documents utilisés quand ils sont disponibles.

Question :
{question}
"""

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[
                                    FILE_SEARCH_STORE
                                ]
                            )
                        )
                    ],
                ),
            )

            answer = response.text or "Aucune réponse générée."

            st.markdown(answer)

            grounding = None
            try:
                grounding = response.candidates[0].grounding_metadata
            except Exception:
                grounding = None

            if grounding:
                with st.expander("Métadonnées de grounding / citations"):
                    st.write(grounding)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )