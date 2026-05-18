# RAG documentaire public

Application Streamlit permettant d'interroger des documents publics via Hector, l'assistant documentaire hybride du CCE.

La branche `feature/local-embeddings-hybrid` ajoute un mode hybride :

- recherche documentaire et embeddings en local avec Chroma + SentenceTransformers ;
- recherche locale directe ou via API interne ;
- génération finale avec Gemini ;
- ancien mode Gemini File Search conservé en secours.

## Lancement rapide

```bash
python -m pip install -r requirements.txt
python -m streamlit run app_modular.py
```

Pour utiliser le moteur local ou l'API locale, il faut aussi installer les dépendances locales et construire l'index.

## 1. Installer les dépendances locales

Les dépendances lourdes du moteur local sont séparées pour ne pas alourdir inutilement le déploiement Streamlit Cloud.

```bash
python -m pip install -r requirements-local.txt
```

Ce fichier installe notamment :

- `chromadb` pour la base vectorielle locale ;
- `sentence-transformers` pour les embeddings locaux ;
- `pypdf` pour extraire le texte des PDF ;
- `fastapi` et `uvicorn` pour exposer l'index local via API.

## 2. Préparer les données

Le script d'indexation attend :

```text
data/
inventaire.json
```

Le dossier `data/` doit contenir les PDF avec les chemins référencés dans `inventaire.json`.

Exemple :

```text
data/article/2024-01-01-document.pdf
inventaire.json
```

Le dossier `data/` reste ignoré par Git.

## 3. Construire l'index local

Lancer :

```bash
python scripts/build_local_index.py --reset
```

Le script :

1. lit `inventaire.json` ;
2. retrouve les PDF dans `data/` ;
3. extrait le texte des PDF ;
4. découpe les textes en passages ;
5. calcule les embeddings localement ;
6. stocke le tout dans `chroma_db/`.

Par défaut :

```text
Modèle d'embedding : intfloat/multilingual-e5-base
Base vectorielle    : chroma_db/
Collection Chroma   : archie_documents
Taille de chunk     : 1800 caractères
Chevauchement       : 250 caractères
```

Options utiles :

```bash
python scripts/build_local_index.py --reset --embedding-model intfloat/multilingual-e5-base
python scripts/build_local_index.py --reset --chunk-size 2200 --chunk-overlap 300
python scripts/build_local_index.py --data-dir data --inventory inventaire.json --chroma-dir chroma_db
```

Le dossier `chroma_db/` est ignoré par Git. Il doit être recréé ou copié sur la machine qui exécute le moteur local.

## 4. Lancer l'API locale de recherche

Sur le serveur où se trouvent `chroma_db/`, `data/` et `inventaire.json` :

```bash
python -m uvicorn api_local_search:app --host 0.0.0.0 --port 8000
```

Test santé :

```bash
curl http://127.0.0.1:8000/health
```

Réponse attendue :

```json
{"status":"ok"}
```

### Sécuriser avec un token

Définir une variable d'environnement sur le serveur API :

```bash
export LOCAL_SEARCH_API_TOKEN="un_token_secret"
```

Sous PowerShell :

```powershell
$env:LOCAL_SEARCH_API_TOKEN="un_token_secret"
```

Puis lancer l'API dans le même terminal.

Si `LOCAL_SEARCH_API_TOKEN` est défini côté API, les appels doivent fournir le header :

```text
X-API-Token: un_token_secret
```

Exemple de test :

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -H "X-API-Token: un_token_secret" \
  -d '{"question":"Quels documents parlent de mobilité durable ?","top_k":5}'
```

## 5. Connecter l'app Streamlit à l'API

Configurer l'app Streamlit avec :

```bash
export LOCAL_SEARCH_API_URL="http://IP_DU_SERVEUR:8000/search"
export LOCAL_SEARCH_API_TOKEN="un_token_secret"
```

Sous PowerShell :

```powershell
$env:LOCAL_SEARCH_API_URL="http://IP_DU_SERVEUR:8000/search"
$env:LOCAL_SEARCH_API_TOKEN="un_token_secret"
```

Puis lancer :

```bash
python -m streamlit run app_modular.py
```

Dans la sidebar, choisir :

```text
Moteur documentaire : API locale
```

C'est le mode par défaut sur cette branche.

Le fonctionnement devient :

```text
Question utilisateur
→ app Streamlit Hector
→ POST vers l'API locale /search
→ recherche dans chroma_db/ côté serveur
→ retour des meilleurs extraits et métadonnées
→ envoi des extraits à Gemini
→ réponse finale d'Hector
```

## 6. Autres moteurs documentaires

Dans la sidebar, trois modes sont disponibles :

```text
API locale
Recherche locale directe
Gemini File Search
```

### API locale

Recommandé si l'index `chroma_db/` est sur un serveur interne et que l'app Streamlit doit y accéder via HTTP.

### Recherche locale directe

À utiliser si Streamlit tourne sur la même machine que `chroma_db/`.

### Gemini File Search

Garde l'ancien comportement :

```text
Question utilisateur
→ Gemini File Search
→ grounding metadata Gemini
→ réponse finale
```

À utiliser si :

- l'API locale n'est pas disponible ;
- l'index local n'est pas encore construit ;
- `chroma_db/` est absent ;
- les dépendances locales ne sont pas installées ;
- tu veux comparer les résultats local vs Gemini File Search.

## 7. Déploiement Streamlit Cloud

Attention : Streamlit Cloud n'a pas automatiquement accès à ton VPN ni à ton serveur interne.

Pour utiliser `API locale` depuis Streamlit Cloud, il faut que l'API soit accessible depuis Streamlit Cloud, par exemple via :

```text
https://api-hector.ccecrb.fgov.be/search
```

avec :

```text
HTTPS
Token API
Accès réseau autorisé par l'IT
```

Si l'API reste accessible uniquement via VPN, alors il vaut mieux héberger Streamlit aussi en interne.

Architecture recommandée :

```text
Utilisateur connecté au VPN
→ Hector hébergé sur serveur interne
→ API locale ou chroma_db/ local
→ Gemini utilisé seulement pour générer la réponse
```

## 8. Fichiers ajoutés

```text
requirements-local.txt
scripts/build_local_index.py
src/local_retrieval.py
src/local_api_client.py
api_local_search.py
```

Fichiers modifiés :

```text
app_modular.py
src/prompts.py
.gitignore
README.md
```

## 9. Dépannage

### Erreur : API locale indisponible

Causes probables :

- `LOCAL_SEARCH_API_URL` non configuré ;
- API non démarrée ;
- port bloqué par firewall/VPN ;
- token incorrect ;
- URL doit finir par `/search`.

Vérifier :

```bash
curl http://IP_DU_SERVEUR:8000/health
```

Puis configurer :

```bash
export LOCAL_SEARCH_API_URL="http://IP_DU_SERVEUR:8000/search"
export LOCAL_SEARCH_API_TOKEN="un_token_secret"
```

### Erreur : Recherche locale directe indisponible

Causes probables :

- `requirements-local.txt` non installé ;
- dossier `chroma_db/` absent ;
- index local pas encore construit.

Correction :

```bash
python -m pip install -r requirements-local.txt
python scripts/build_local_index.py --reset
python -m streamlit run app_modular.py
```

### Erreur Gemini 429 RESOURCE_EXHAUSTED

Cette erreur vient du quota Gemini, souvent sur File Search ou embeddings côté Google.

Solution : utiliser le moteur :

```text
API locale
```

ou :

```text
Recherche locale directe
```

Ainsi, l'embedding de recherche est fait localement.

### Les documents cités ne s'affichent pas

En mode API locale ou Recherche locale directe, les documents cités viennent directement des métadonnées stockées dans Chroma.

Vérifier que `inventaire.json` contient bien :

```text
title
post_url
file_url
path
document_type
theme
date/year
```

Puis reconstruire :

```bash
python scripts/build_local_index.py --reset
```

## 10. Commandes Git utiles

```bash
git fetch origin
git switch feature/local-embeddings-hybrid
git pull origin feature/local-embeddings-hybrid
```

Pour revenir à la branche précédente :

```bash
git switch refactor/partition-app
```
