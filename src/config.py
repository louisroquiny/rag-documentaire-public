import os
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from google import genai


@dataclass(frozen=True)
class AppConfig:
    gemini_api_key: str
    file_search_store: str
    file_search_selection_file: str
    inventory_json_file: Path = Path("inventaire.json")
    inventory_csv_file: Path = Path("inventaire.csv")
    data_dir: Path = Path("data")


def get_secret(name: str, default: str | None = None) -> str | None:
    """
    Lit d'abord les secrets Streamlit, puis les variables d'environnement.
    Pratique pour fonctionner à la fois en local et sur Streamlit Cloud.
    """
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


def load_config() -> AppConfig:
    gemini_api_key = get_secret("GEMINI_API_KEY")
    file_search_store = get_secret("FILE_SEARCH_STORE")
    file_search_selection_file = get_secret(
        "FILE_SEARCH_SELECTION_FILE",
        "analyse_gemini/inventaire_selection_gemini.json",
    )

    if not gemini_api_key:
        st.error("Secret manquant : GEMINI_API_KEY")
        st.stop()

    if not file_search_store:
        st.error("Secret manquant : FILE_SEARCH_STORE")
        st.stop()

    return AppConfig(
        gemini_api_key=gemini_api_key,
        file_search_store=file_search_store,
        file_search_selection_file=file_search_selection_file or "",
    )


def create_gemini_client(config: AppConfig):
    return genai.Client(api_key=config.gemini_api_key)
