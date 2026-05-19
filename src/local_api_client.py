import os

import requests


class LocalSearchApiUnavailable(RuntimeError):
    pass


def _get_streamlit_secret(name: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name, "")
        return str(value).strip() if value else ""
    except Exception:
        return ""


def get_api_settings() -> tuple[str, str]:
    api_url = os.getenv("LOCAL_SEARCH_API_URL", "").strip()
    api_token = os.getenv("LOCAL_SEARCH_API_TOKEN", "").strip()

    if not api_url:
        api_url = _get_streamlit_secret("LOCAL_SEARCH_API_URL")

    if not api_token:
        api_token = _get_streamlit_secret("LOCAL_SEARCH_API_TOKEN")

    return api_url, api_token


def search_local_api(
    question: str,
    document_type: str = "Tous",
    year: str = "Toutes",
    theme: str = "Tous",
    top_k: int = 8,
) -> list[dict]:
    api_url, api_token = get_api_settings()

    if not api_url:
        raise LocalSearchApiUnavailable(
            "LOCAL_SEARCH_API_URL n'est pas configuré. Renseigne l'URL de l'API de recherche locale."
        )

    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["X-API-Token"] = api_token

    try:
        response = requests.post(
            api_url,
            headers=headers,
            json={
                "question": question,
                "document_type": document_type,
                "year": year,
                "theme": theme,
                "top_k": top_k,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise LocalSearchApiUnavailable(f"Erreur d'appel à l'API locale : {e}") from e

    payload = response.json()
    return payload.get("hits", [])
