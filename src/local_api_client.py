import os

import requests


class LocalSearchApiUnavailable(RuntimeError):
    pass


def get_api_settings() -> tuple[str, str]:
    api_url = os.getenv("LOCAL_SEARCH_API_URL", "").strip()
    api_token = os.getenv("LOCAL_SEARCH_API_TOKEN", "").strip()
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
