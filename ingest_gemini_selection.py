import os
import sys
import json
import csv
import time
import tomllib
import traceback
from datetime import datetime
from pathlib import Path

import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
os.environ["CURL_CA_BUNDLE"] = certifi.where()

from google import genai


DATA_DIR = Path("data")
INVENTAIRE_JSON_FILE = Path("inventaire.json")
INVENTAIRE_CSV_FILE = Path("inventaire.csv")
STORE_NAME_FILE = Path("store_name.txt")
SELECTION_JSON_FILE = Path("analyse_gemini/inventaire_selection_gemini.json")
SELECTION_MANIFEST_FILE = Path("analyse_gemini/manifest_paths_selection.txt")
SECRETS_FILE = Path(".streamlit/secrets.toml")
LOG_DIR = Path("logs")
LATEST_LOG_FILE = LOG_DIR / "ingest_gemini_latest.log"
RUN_LOG_FILE = None

MAX_OPERATION_WAIT_SECONDS = 15 * 60  # 15 minutes par fichier
POLL_SECONDS = 10
DEDUP_MODE_DEFAULT = "skip"  # "skip" = ignorer les PDF déjà présents, "none" = toujours uploader



def load_secrets():
    if not SECRETS_FILE.exists():
        raise RuntimeError("Fichier .streamlit/secrets.toml introuvable.")

    with open(SECRETS_FILE, "rb") as f:
        return tomllib.load(f)


def configure_console_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def setup_log_file():
    """
    Crée un fichier de log horodaté pour cette exécution.

    Toutes les lignes passées à log() sont écrites à la fois dans la console,
    dans logs/ingest_gemini_latest.log et dans le fichier horodaté.
    """
    global RUN_LOG_FILE

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    RUN_LOG_FILE = LOG_DIR / f"ingest_gemini_{timestamp}.log"

    header = [
        "=" * 80,
        f"Démarrage ingest_gemini : {datetime.now().isoformat(timespec='seconds')}",
        f"Fichier de log : {RUN_LOG_FILE}",
        "=" * 80,
    ]

    for line in header:
        write_log_line(line, add_timestamp=False)

    return RUN_LOG_FILE


def write_log_line(message, add_timestamp=True):
    text = str(message)
    if add_timestamp and text:
        text = f"[{datetime.now().isoformat(timespec='seconds')}] {text}"

    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.flush()

    log_files = []
    if RUN_LOG_FILE is not None:
        log_files.append(RUN_LOG_FILE)
        log_files.append(LATEST_LOG_FILE)

    for log_file in log_files:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            # Le logging ne doit jamais arrêter l'indexation.
            pass


def log(message=""):
    write_log_line(message)


def log_exception(title, exc):
    log("")
    log(title)
    log(str(exc))
    for line in traceback.format_exc().rstrip().splitlines():
        log(line)


def format_duration(seconds):
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}min {seconds}s"
    if minutes:
        return f"{minutes}min {seconds}s"
    return f"{seconds}s"


def normalize_inventory_path(value):
    """
    Normalise un chemin d'inventaire pour faire la correspondance avec
    pdf_path.relative_to(DATA_DIR).

    Exemples acceptés :
    - article/document.pdf
    - .\\data\\article\\document.pdf
    - data/article/document.pdf
    """
    value = str(value or "").strip().replace("\\", "/")

    if not value:
        return ""

    while value.startswith("./"):
        value = value[2:]

    data_prefix = DATA_DIR.as_posix().strip("/") + "/"

    if value.startswith(data_prefix):
        value = value[len(data_prefix):]

    return value.lower().strip()


def load_metadata_from_csv():
    """
    Fallback si inventaire.json n'existe pas.
    Structure attendue :
    category,title,theme,date,post_url,file_url,path
    """
    if not INVENTAIRE_CSV_FILE.exists():
        raise RuntimeError(
            "Aucun inventaire trouvé. Il faut inventaire.json ou inventaire.csv."
        )

    metadata = {}

    with open(INVENTAIRE_CSV_FILE, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        required_columns = {
            "category",
            "title",
            "theme",
            "date",
            "post_url",
            "file_url",
            "path",
        }
        found_columns = set(reader.fieldnames or [])
        missing_columns = required_columns - found_columns

        if missing_columns:
            raise RuntimeError(
                "Colonnes manquantes dans inventaire.csv : "
                + ", ".join(sorted(missing_columns))
            )

        for row in reader:
            inventory_path = (row.get("path") or "").strip()
            path_key = normalize_inventory_path(inventory_path)

            if not path_key:
                continue

            metadata[path_key] = {
                "category": (row.get("category") or "").strip(),
                "title": (row.get("title") or "").strip(),
                "theme": (row.get("theme") or "").strip(),
                "date": (row.get("date") or "").strip(),
                "post_url": (row.get("post_url") or "").strip(),
                "file_url": (row.get("file_url") or "").strip(),
                "path": inventory_path,
            }

    return metadata


def load_metadata():
    """
    Charge les métadonnées depuis inventaire.json en priorité.
    Sinon, fallback vers inventaire.csv.
    """
    if INVENTAIRE_JSON_FILE.exists():
        with open(INVENTAIRE_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        metadata = {}

        for path, meta in data.items():
            inventory_path = (meta.get("path") or path).strip()
            path_key = normalize_inventory_path(inventory_path)

            if not path_key:
                continue

            metadata[path_key] = {
                "category": (meta.get("category") or "").strip(),
                "title": (meta.get("title") or "").strip(),
                "theme": (meta.get("theme") or "").strip(),
                "date": (meta.get("date") or "").strip(),
                "post_url": (meta.get("post_url") or "").strip(),
                "file_url": (meta.get("file_url") or "").strip(),
                "path": inventory_path,
            }

        return metadata

    return load_metadata_from_csv()


def resolve_selection_file(secrets):
    """
    Détermine quel fichier de sélection utiliser.

    Par défaut, le script utilise le fichier généré par analyse_quota_gemini.py :
    analyse_gemini/inventaire_selection_gemini.json

    Tu peux forcer un autre chemin dans .streamlit/secrets.toml :
    FILE_SEARCH_SELECTION_FILE = "analyse_gemini/inventaire_selection_gemini.json"

    Tu peux désactiver le filtrage avec :
    FILE_SEARCH_SELECTION_FILE = ""
    """
    configured = secrets.get("FILE_SEARCH_SELECTION_FILE", str(SELECTION_JSON_FILE))

    if configured is None:
        return SELECTION_JSON_FILE

    configured = str(configured).strip()

    if configured.lower() in {"", "none", "false", "off"}:
        return None

    return Path(configured)


def add_selection_key(selection_keys, seen_keys, value):
    """
    Ajoute un chemin normalisé à la sélection en conservant l'ordre.

    Important : analyse_quota_gemini.py trie la sélection du plus récent au plus ancien.
    On conserve donc cet ordre ici, au lieu de repasser par l'ordre alphabétique du dossier data.
    """
    path_key = normalize_inventory_path(value)
    if path_key and path_key not in seen_keys:
        selection_keys.append(path_key)
        seen_keys.add(path_key)


def load_selection_keys(selection_file):
    """
    Charge les chemins sélectionnés par analyse_quota_gemini.py.

    Formats acceptés :
    - JSON dictionnaire : inventaire_selection_gemini.json
    - JSON liste : liste de chemins ou d'objets avec champ path
    - TXT : un chemin relatif par ligne, ex. manifest_paths_selection.txt

    Retourne une LISTE ordonnée, pas un set, pour respecter l'ordre :
    plus récent -> plus ancien.
    """
    if selection_file is None:
        log("Filtrage par sélection désactivé : tous les PDF du dossier data sont candidats.")
        return None

    if not selection_file.exists():
        log(
            f"Fichier de sélection introuvable : {selection_file}. "
            "Tous les PDF du dossier data seront candidats."
        )
        return None

    selection_keys = []
    seen_keys = set()
    suffix = selection_file.suffix.lower()

    if suffix == ".json":
        with open(selection_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            # Les dictionnaires Python gardent l'ordre du JSON.
            # analyse_quota_gemini.py écrit déjà la sélection dans l'ordre chronologique décroissant.
            for key, meta in data.items():
                if isinstance(meta, dict):
                    value = meta.get("path") or key
                else:
                    value = key
                add_selection_key(selection_keys, seen_keys, value)

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    value = item.get("path") or item.get("relative_path") or item.get("filename")
                else:
                    value = item
                add_selection_key(selection_keys, seen_keys, value)
        else:
            raise RuntimeError(
                "Format JSON de sélection invalide : attendu dictionnaire ou liste."
            )

    else:
        with open(selection_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                add_selection_key(selection_keys, seen_keys, line)

    if not selection_keys:
        raise RuntimeError(f"Le fichier de sélection ne contient aucun chemin exploitable : {selection_file}")

    log(f"Fichier de sélection utilisé : {selection_file}")
    log(f"Documents sélectionnés dans ce fichier : {len(selection_keys)}")
    return selection_keys


def filter_pdfs_by_selection(pdfs, selection_keys):
    """
    Garde uniquement les PDF dont le chemin relatif est présent dans la sélection.
    L'ordre de sortie suit le fichier de sélection : plus récent -> plus ancien.
    """
    if selection_keys is None:
        return pdfs, []

    pdfs_by_key = {
        normalize_inventory_path(pdf_path.relative_to(DATA_DIR)): pdf_path
        for pdf_path in pdfs
    }
    selection_key_set = set(selection_keys)

    selected_pdfs = []
    found_keys = set()

    for selection_key in selection_keys:
        pdf_path = pdfs_by_key.get(selection_key)
        if pdf_path is not None:
            selected_pdfs.append(pdf_path)
            found_keys.add(selection_key)

    ignored_pdfs = [
        pdf_path
        for key, pdf_path in pdfs_by_key.items()
        if key not in selection_key_set
    ]

    missing_selected_keys = [
        key for key in selection_keys
        if key not in found_keys
    ]

    log(f"PDF candidats avant sélection : {len(pdfs)}")
    log(f"PDF retenus par la sélection : {len(selected_pdfs)}")
    log(f"PDF ignorés hors sélection : {len(ignored_pdfs)}")
    log("Ordre d'indexation : ordre du fichier de sélection, du plus récent au plus ancien.")

    if selected_pdfs:
        first_path = selected_pdfs[0].relative_to(DATA_DIR)
        last_path = selected_pdfs[-1].relative_to(DATA_DIR)
        log(f"Premier PDF retenu : {str(first_path).replace(chr(92), '/')}")
        log(f"Dernier PDF retenu : {str(last_path).replace(chr(92), '/')}")

    if missing_selected_keys:
        log(
            f"Attention : {len(missing_selected_keys)} chemin(s) de la sélection "
            "ne correspondent à aucun PDF local."
        )

        preview = missing_selected_keys[:20]
        for missing_key in preview:
            log(f"Chemin sélectionné introuvable localement : {missing_key}")

        if len(missing_selected_keys) > len(preview):
            log(f"... et {len(missing_selected_keys) - len(preview)} autre(s).")

    return selected_pdfs, ignored_pdfs


def build_custom_metadata(filename, relative_path, meta):
    """
    Prépare les métadonnées au format attendu par Gemini File Search.

    Gemini attend une liste de champs :
    {"key": "...", "string_value": "..."}
    """
    fields = {
        "filename": filename,
        "relative_path": str(relative_path).replace("\\", "/"),
        "category": meta.get("category", ""),
        "title": meta.get("title", ""),
        "theme": meta.get("theme", ""),
        "date": meta.get("date", ""),
        "post_url": meta.get("post_url", ""),
        "file_url": meta.get("file_url", ""),
        "path": meta.get("path", str(relative_path).replace("\\", "/")),
    }

    return [
        {"key": key, "string_value": str(value)}
        for key, value in fields.items()
        if value is not None
    ]


def wait_for_operation(client, operation, label="fichier"):
    start = time.time()

    while not operation.done:
        elapsed = time.time() - start

        if elapsed > MAX_OPERATION_WAIT_SECONDS:
            raise TimeoutError(
                f"Timeout après {format_duration(elapsed)} pour {label}. "
                "L'opération Gemini n'a pas terminé."
            )

        log(f"Indexation en cours pour {label}... attente : {format_duration(elapsed)}")
        time.sleep(POLL_SECONDS)

        operation = client.operations.get(operation)

        error = getattr(operation, "error", None)
        if error:
            raise RuntimeError(f"Erreur Gemini pendant l'indexation de {label} : {error}")

    return operation



def metadata_fields_to_dict(custom_metadata):
    """
    Convertit les métadonnées d'un document Gemini en dictionnaire simple.

    Le SDK peut exposer les champs comme objets Python ou comme dictionnaires
    selon la version installée. Cette fonction accepte les deux formes.
    """
    result = {}

    for field in custom_metadata or []:
        if isinstance(field, dict):
            key = field.get("key")
            value = (
                field.get("string_value")
                or field.get("stringValue")
                or field.get("numeric_value")
                or field.get("numericValue")
                or field.get("bool_value")
                or field.get("boolValue")
            )
        else:
            key = getattr(field, "key", None)
            value = (
                getattr(field, "string_value", None)
                or getattr(field, "stringValue", None)
                or getattr(field, "numeric_value", None)
                or getattr(field, "numericValue", None)
                or getattr(field, "bool_value", None)
                or getattr(field, "boolValue", None)
            )

        if key:
            result[str(key)] = "" if value is None else str(value)

    return result


def get_document_display_name(document):
    if isinstance(document, dict):
        return document.get("display_name") or document.get("displayName") or ""

    return getattr(document, "display_name", None) or getattr(document, "displayName", None) or ""


def get_document_name(document):
    if isinstance(document, dict):
        return document.get("name") or ""

    return getattr(document, "name", None) or ""


def get_document_metadata(document):
    if isinstance(document, dict):
        custom_metadata = document.get("custom_metadata") or document.get("customMetadata") or []
    else:
        custom_metadata = (
            getattr(document, "custom_metadata", None)
            or getattr(document, "customMetadata", None)
            or []
        )

    return metadata_fields_to_dict(custom_metadata)


def get_document_relative_key(document):
    metadata = get_document_metadata(document)

    for key in ("relative_path", "path", "filename"):
        value = metadata.get(key)
        if value:
            return normalize_inventory_path(value)

    display_name = get_document_display_name(document)
    if display_name:
        return normalize_inventory_path(display_name)

    return ""


def load_existing_documents_by_relative_path(client, file_search_store_name):
    """
    Liste les documents déjà présents dans le File Search Store et les indexe
    par chemin relatif normalisé.

    Permet d'éviter les doublons quand le script est relancé sur le même corpus.
    """
    existing_documents = {}
    total_documents = 0
    documents_without_key = 0

    for document in client.file_search_stores.documents.list(parent=file_search_store_name):
        total_documents += 1
        document_key = get_document_relative_key(document)

        if not document_key:
            documents_without_key += 1
            continue

        existing_documents.setdefault(document_key, []).append(document)

    duplicate_keys = sum(1 for docs in existing_documents.values() if len(docs) > 1)

    log(f"Documents déjà présents dans le store : {total_documents}")
    log(f"Documents reconnus par chemin relatif : {sum(len(docs) for docs in existing_documents.values())}")

    if duplicate_keys:
        log(f"Attention : {duplicate_keys} chemin(s) ont déjà plusieurs documents dans le store.")

    if documents_without_key:
        log(
            f"Attention : {documents_without_key} document(s) existant(s) n'ont pas de métadonnée exploitable "
            "pour la déduplication."
        )

    return existing_documents


def delete_documents(client, documents, reason):
    deleted = 0
    failed = []

    for document in documents:
        document_name = get_document_name(document)

        if not document_name:
            failed.append({"name": "", "error": "Nom de document introuvable"})
            continue

        try:
            log(f"Suppression du document existant ({reason}) : {document_name}")
            client.file_search_stores.documents.delete(
                name=document_name,
                config={"force": True},
            )
            deleted += 1
        except Exception as e:
            log(f"ERREUR pendant la suppression de {document_name} : {e}")
            failed.append({"name": document_name, "error": str(e)})

    return deleted, failed


def normalize_dedup_mode(value):
    """
    Mode anti-doublons volontairement conservateur.

    - skip : si le PDF existe déjà dans le store, on ne l'upload pas.
    - none : désactive la protection et upload toujours.

    Les anciens modes de remplacement sont convertis en skip pour éviter toute
    suppression ou réindexation forcée.
    """
    raw_value = str(value or DEDUP_MODE_DEFAULT).strip().lower().replace("-", "_")

    aliases = {
        "replace": "skip",
        "update": "skip",
        "upsert": "skip",
        "replace_before_upload": "skip",
        "replace_after_upload": "skip",
        "delete_then_upload": "skip",
        "upload": "none",
        "off": "none",
        "false": "none",
    }

    normalized = aliases.get(raw_value, raw_value)
    allowed = {"skip", "none"}

    if normalized not in allowed:
        raise RuntimeError(
            "FILE_SEARCH_DEDUP_MODE invalide. Valeurs acceptées : "
            + ", ".join(sorted(allowed))
        )

    if raw_value != normalized:
        log(
            f"FILE_SEARCH_DEDUP_MODE={raw_value!r} converti en {normalized!r} : "
            "aucune suppression ni réindexation forcée ne sera effectuée."
        )

    return normalized


def main():
    configure_console_utf8()
    log_file = setup_log_file()
    log(f"Journal détaillé activé : {log_file}")

    secrets = load_secrets()

    api_key = secrets.get("GEMINI_API_KEY")
    existing_store_name = secrets.get("FILE_SEARCH_STORE")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY manquant dans .streamlit/secrets.toml")

    if not DATA_DIR.exists():
        raise RuntimeError("Le dossier data n'existe pas.")

    all_pdfs = sorted(DATA_DIR.rglob("*.pdf"))

    if not all_pdfs:
        raise RuntimeError("Aucun PDF trouvé dans le dossier data.")

    selection_file = resolve_selection_file(secrets)
    selection_keys = load_selection_keys(selection_file)
    pdfs, ignored_by_selection = filter_pdfs_by_selection(all_pdfs, selection_keys)

    if not pdfs:
        raise RuntimeError(
            "Aucun PDF à indexer après application de la sélection. "
            "Vérifie analyse_gemini/inventaire_selection_gemini.json et le dossier data."
        )

    log(f"PDF trouvés dans data : {len(all_pdfs)}")
    log(f"PDF à traiter après sélection : {len(pdfs)}")

    metadata_map = load_metadata()
    log(f"Métadonnées chargées : {len(metadata_map)} lignes")

    client = genai.Client(api_key=api_key)
    dedup_mode = normalize_dedup_mode(secrets.get("FILE_SEARCH_DEDUP_MODE"))
    log(f"Mode anti-doublons : {dedup_mode}")

    if existing_store_name:
        file_search_store_name = existing_store_name
        log(f"Utilisation du File Search Store existant : {file_search_store_name}")
    else:
        log("Création du File Search Store...")

        file_search_store = client.file_search_stores.create(
            config={
                "display_name": "rag-documents-publics"
            }
        )

        file_search_store_name = file_search_store.name
        log(f"Store créé : {file_search_store_name}")

    STORE_NAME_FILE.write_text(file_search_store_name, encoding="utf-8")

    if dedup_mode == "none":
        existing_documents_by_key = {}
        log("Déduplication désactivée : les uploads seront toujours ajoutés.")
    else:
        log("Lecture des documents existants pour éviter les doublons...")
        existing_documents_by_key = load_existing_documents_by_relative_path(
            client, file_search_store_name
        )

    missing_metadata = 0
    skipped_uploads = []
    replaced_documents = []
    failed_deletions = []
    failed_uploads = []
    total_pdfs = len(pdfs)
    start_time = time.time()

    for index, pdf_path in enumerate(pdfs, start=1):
        relative_path = pdf_path.relative_to(DATA_DIR)
        relative_path_str = str(relative_path).replace("\\", "/")
        relative_key = normalize_inventory_path(relative_path)
        filename = pdf_path.name
        meta = metadata_map.get(relative_key, {})

        if not meta:
            missing_metadata += 1

        display_name = meta.get("title") or relative_path_str
        custom_metadata = build_custom_metadata(filename, relative_path, meta)

        elapsed = time.time() - start_time
        average_per_pdf = elapsed / max(1, index - 1) if index > 1 else 0
        remaining_pdfs = total_pdfs - index + 1
        estimated_remaining = average_per_pdf * remaining_pdfs if average_per_pdf else 0

        log("")
        log(f"[{index}/{total_pdfs}] Upload du fichier : {relative_path_str}")
        log(f"Titre : {display_name}")

        if index > 1:
            log(f"Temps écoulé : {format_duration(elapsed)}")
            log(f"Temps moyen par PDF : {format_duration(average_per_pdf)}")
            log(f"Temps restant estimé : {format_duration(estimated_remaining)}")
        else:
            log("Estimation du temps disponible après le premier PDF.")

        if meta.get("file_url"):
            log(f"Lien PDF : {meta['file_url']}")

        matching_existing_documents = existing_documents_by_key.get(relative_key, [])

        if matching_existing_documents:
            log(
                f"Document déjà présent dans le store pour ce chemin : "
                f"{len(matching_existing_documents)} occurrence(s)."
            )

            if dedup_mode == "skip":
                log("Upload ignoré : le document existe déjà dans le store.")
                skipped_uploads.append(
                    {
                        "path": relative_path_str,
                        "filename": filename,
                        "title": display_name,
                        "existing_documents": [
                            get_document_name(document)
                            for document in matching_existing_documents
                        ],
                    }
                )
                continue

        pdf_start_time = time.time()

        try:
            operation = client.file_search_stores.upload_to_file_search_store(
                file=str(pdf_path),
                file_search_store_name=file_search_store_name,
                config={
                    "display_name": display_name,
                    "custom_metadata": custom_metadata,
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": 500,
                            "max_overlap_tokens": 80,
                        }
                    },
                },
            )

            wait_for_operation(client, operation, label=relative_path_str)

            if matching_existing_documents and dedup_mode == "replace_after_upload":
                deleted, deletion_errors = delete_documents(
                    client, matching_existing_documents, reason="après ré-upload réussi"
                )
                failed_deletions.extend(deletion_errors)

                if deleted:
                    replaced_documents.append(
                        {
                            "path": relative_path_str,
                            "deleted_after_upload": deleted,
                        }
                    )

                if deletion_errors:
                    log(
                        "Attention : le nouveau document est indexé, mais au moins une "
                        "ancienne occurrence n'a pas pu être supprimée."
                    )

                existing_documents_by_key[relative_key] = []

        except KeyboardInterrupt:
            log("")
            log("Interruption demandée par l'utilisateur.")
            raise

        except Exception as e:
            pdf_duration = time.time() - pdf_start_time

            log("")
            log(f"ERREUR sur le fichier : {relative_path_str}")
            log(f"Après : {format_duration(pdf_duration)}")
            log(str(e))
            log("Le script continue avec le fichier suivant.")

            failed_uploads.append(
                {
                    "path": relative_path_str,
                    "filename": filename,
                    "title": display_name,
                    "error": str(e),
                }
            )

            continue

        pdf_duration = time.time() - pdf_start_time
        total_elapsed = time.time() - start_time
        remaining = total_pdfs - index
        average_done = total_elapsed / max(1, index)
        estimated_remaining_after = average_done * remaining

        log(f"Fichier indexé en : {format_duration(pdf_duration)}")
        if remaining:
            log(f"Progression : {index}/{total_pdfs}")
            log(f"Temps restant estimé : {format_duration(estimated_remaining_after)}")

    total_duration = time.time() - start_time

    log("")
    log("Indexation terminée.")
    log(f"Durée totale : {format_duration(total_duration)}")
    log("Nom du File Search Store :")
    log(file_search_store_name)
    log("")
    log("Ce nom a été sauvegardé dans store_name.txt.")

    if ignored_by_selection:
        ignored_selection_path = Path("ignored_by_selection.json")
        ignored_selection = [
            str(pdf_path.relative_to(DATA_DIR)).replace("\\", "/")
            for pdf_path in ignored_by_selection
        ]
        ignored_selection_path.write_text(
            json.dumps(ignored_selection, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log("")
        log(f"PDF ignorés car hors sélection : {len(ignored_by_selection)}")
        log(f"Liste sauvegardée dans : {ignored_selection_path}")

    if skipped_uploads:
        skipped_path = Path("skipped_uploads.json")
        skipped_path.write_text(
            json.dumps(skipped_uploads, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log("")
        log(f"Uploads ignorés pour éviter les doublons : {len(skipped_uploads)}")
        log(f"Liste sauvegardée dans : {skipped_path}")

    if replaced_documents:
        replaced_path = Path("replaced_documents.json")
        replaced_path.write_text(
            json.dumps(replaced_documents, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log("")
        log(f"Documents remplacés/nettoyés : {len(replaced_documents)}")
        log(f"Liste sauvegardée dans : {replaced_path}")

    if failed_deletions:
        failed_deletions_path = Path("failed_deletions.json")
        failed_deletions_path.write_text(
            json.dumps(failed_deletions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log("")
        log(
            f"Attention : {len(failed_deletions)} suppression(s) de document existant ont échoué."
        )
        log(f"Liste sauvegardée dans : {failed_deletions_path}")

    if failed_uploads:
        failed_path = Path("failed_uploads.json")
        failed_path.write_text(
            json.dumps(failed_uploads, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log("")
        log(f"Attention : {len(failed_uploads)} fichier(s) n'ont pas été indexés.")
        log(f"Liste sauvegardée dans : {failed_path}")

    if missing_metadata:
        log("")
        log(
            f"Attention : {missing_metadata} PDF n'avaient pas de métadonnées "
            "dans l'inventaire."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("")
        log("Arrêt du script après interruption utilisateur.")
        raise
    except Exception as e:
        log_exception("ERREUR FATALE : le script s'est arrêté.", e)
        raise
