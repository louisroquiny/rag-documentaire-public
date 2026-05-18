# RAG documentaire public

Application Streamlit permettant d'interroger des documents publics via Hector, l'assistant documentaire hybride du CCE.

La branche `feature/local-embeddings-hybrid` ajoute un mode hybride :

- recherche documentaire et embeddings en local avec Chroma + SentenceTransformers ;
- génération finale avec Gemini ;
- ancien mode Gemini File Search conservé en secours.

## Lancement rapide

```bash
python -m pip install -r requirements.txt
python -m streamlit run app_modular.py
```

Pour utiliser le moteur local, il faut aussi installer les dépendances locales et construire l'index.

## 1. Installer les dépendances locales

Les dépendances lourdes du moteur local sont séparées pour ne pas alourdir inutilement le déploiement Streamlit Cloud.

```bash
python -m pip install -r requirements-local.txt
```

Ce fichier installe notamment :

- `chromadb` pour la base vectorielle locale ;
- `sentence-transformers` pour les embeddings locaux ;
- `pypdf` pour extraire le texte des PDF.

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

## 4. Lancer Hector en mode hybride

```bash
python -m streamlit run app_modular.py
```

Dans la sidebar, choisir :

```text
Moteur documentaire : Recherche locale
```

C'est le mode par défaut sur cette branche.

Le fonctionnement devient :

```text
Question utilisateur
→ embedding local de la question
→ recherche dans chroma_db/
→ récupération des meilleurs extraits
→ envoi des extraits à Gemini
→ réponse finale d'Hector
```

Ce mode évite le quota d'embedding Gemini File Search, car l'embedding de recherche est fait localement.

## 5. Mode de secours Gemini File Search

Dans la sidebar, il est possible de choisir :

```text
Moteur documentaire : Gemini File Search
```

Ce mode garde l'ancien comportement :

```text
Question utilisateur
→ Gemini File Search
→ grounding metadata Gemini
→ réponse finale
```

À utiliser si :

- l'index local n'est pas encore construit ;
- `chroma_db/` est absent ;
- les dépendances locales ne sont pas installées ;
- tu veux comparer les résultats local vs Gemini File Search.

## 6. Déploiement Streamlit Cloud

Attention : Streamlit Cloud n'a pas automatiquement accès à ton dossier local `data/` ni à `chroma_db/`.

Pour Streamlit Cloud, deux options :

### Option A — continuer avec Gemini File Search

Ne pas installer `requirements-local.txt` sur Streamlit Cloud, et choisir dans l'interface :

```text
Moteur documentaire : Gemini File Search
```

### Option B — héberger Hector en interne

Recommandé pour le mode local :

```text
Utilisateur connecté au VPN
→ Hector hébergé sur serveur interne
→ chroma_db/ local ou partagé
→ Gemini utilisé seulement pour générer la réponse
```

C'est l'option la plus propre si la recherche locale doit accéder à des données internes ou à un index construit sur serveur.

## 7. Fichiers ajoutés

```text
requirements-local.txt
scripts/build_local_index.py
src/local_retrieval.py
```

Fichiers modifiés :

```text
app_modular.py
src/prompts.py
.gitignore
README.md
```

## 8. Dépannage

### Erreur : Recherche locale indisponible

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
Recherche locale
```

Ainsi, l'embedding de recherche est fait localement.

### Les documents cités ne s'affichent pas

En mode Recherche locale, les documents cités viennent directement des métadonnées stockées dans Chroma.

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

## 9. Commandes Git utiles

```bash
git fetch origin
git switch feature/local-embeddings-hybrid
git pull origin feature/local-embeddings-hybrid
```

Pour revenir à la branche précédente :

```bash
git switch refactor/partition-app
```
