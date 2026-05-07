import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_CATEGORIES = None


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Calcule la taille des PDF de l'inventaire et determine jusqu'a quelle date "
            "remonter avant d'atteindre une limite Gemini File Search estimee."
        )
    )
    parser.add_argument("--inventory", default="inventaire.json", help="Chemin vers inventaire.json")
    parser.add_argument("--data-dir", default="data", help="Dossier racine contenant les PDF")
    parser.add_argument(
        "--categories",
        nargs="+",
        default=DEFAULT_CATEGORIES,
        help=(
            "Categories a inclure dans l'analyse. "
            "Par defaut, toutes les categories presentes dans inventaire.json sont prises."
        ),
    )
    parser.add_argument(
        "--store-limit-mb",
        type=float,
        default=1024.0,
        help="Limite estimee du store Gemini en Mo. Free tier typique: 1024 Mo",
    )
    parser.add_argument(
        "--multiplier",
        type=float,
        default=3.0,
        help="Multiplicateur d'estimation store = taille PDF x multiplicateur",
    )
    parser.add_argument(
        "--raw-limit-mb",
        type=float,
        default=None,
        help="Limite directe en Mo de PDF. Si indiquee, remplace store-limit-mb / multiplier",
    )
    parser.add_argument(
        "--output-dir",
        default="analyse_gemini",
        help="Dossier de sortie pour les CSV/JSON generes",
    )
    return parser.parse_args()


def bytes_to_mb(value):
    return value / (1024 * 1024)


def safe_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_mb(value):
    return round(value, 3)


def main():
    args = parse_args()
    inventory_path = Path(args.inventory)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not inventory_path.exists():
        raise SystemExit(f"Inventaire introuvable : {inventory_path}")
    if not data_dir.exists():
        raise SystemExit(f"Dossier data introuvable : {data_dir}")

    with inventory_path.open("r", encoding="utf-8") as f:
        inventory = json.load(f)

    wanted_categories = set(args.categories) if args.categories else None
    raw_limit_mb = args.raw_limit_mb
    if raw_limit_mb is None:
        raw_limit_mb = args.store_limit_mb / args.multiplier

    rows = []
    missing_files = []

    for key, meta in inventory.items():
        category = (meta.get("category") or "").strip()
        if wanted_categories is not None and category not in wanted_categories:
            continue

        relative_path = (meta.get("path") or key).replace("\\", "/")
        pdf_path = data_dir / relative_path
        exists = pdf_path.exists()
        size_bytes = pdf_path.stat().st_size if exists else 0
        date_iso = meta.get("date_iso") or ""
        parsed_date = safe_date(date_iso)

        row = {
            "include_initial": "yes",
            "category": category,
            "document_type": meta.get("document_type", ""),
            "section": meta.get("section", ""),
            "title": meta.get("title", ""),
            "date_iso": date_iso,
            "year": meta.get("year", ""),
            "size_bytes": size_bytes,
            "size_mb": format_mb(bytes_to_mb(size_bytes)),
            "estimated_store_mb": format_mb(bytes_to_mb(size_bytes) * args.multiplier),
            "path": relative_path,
            "file_url": meta.get("file_url", ""),
            "post_url": meta.get("post_url", ""),
            "exists": "yes" if exists else "no",
            "_parsed_date": parsed_date,
        }
        rows.append(row)
        if not exists:
            missing_files.append(row)

    # Tri: plus recent d'abord, puis chemin pour stabiliser.
    rows.sort(key=lambda r: (r["_parsed_date"] or datetime.min.date(), r["path"]), reverse=True)

    selected = []
    excluded_by_quota = []
    cumulative_bytes = 0

    for row in rows:
        if row["exists"] != "yes":
            row["selection_status"] = "missing_file"
            excluded_by_quota.append(row)
            continue

        candidate_mb = bytes_to_mb(cumulative_bytes + row["size_bytes"])
        if candidate_mb <= raw_limit_mb:
            cumulative_bytes += row["size_bytes"]
            row["selection_status"] = "selected"
            row["cumulative_pdf_mb"] = format_mb(bytes_to_mb(cumulative_bytes))
            row["cumulative_store_estimated_mb"] = format_mb(bytes_to_mb(cumulative_bytes) * args.multiplier)
            selected.append(row)
        else:
            row["selection_status"] = "excluded_quota"
            row["cumulative_pdf_mb"] = format_mb(bytes_to_mb(cumulative_bytes))
            row["cumulative_store_estimated_mb"] = format_mb(bytes_to_mb(cumulative_bytes) * args.multiplier)
            excluded_by_quota.append(row)

    all_rows_for_csv = selected + excluded_by_quota
    public_fields = [
        "selection_status",
        "category",
        "document_type",
        "section",
        "title",
        "date_iso",
        "year",
        "size_mb",
        "estimated_store_mb",
        "cumulative_pdf_mb",
        "cumulative_store_estimated_mb",
        "path",
        "exists",
        "file_url",
        "post_url",
    ]

    per_file_csv = output_dir / "inventaire_tailles_et_selection.csv"
    with per_file_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=public_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows_for_csv)

    # Synthese par categorie sur fichiers presents seulement.
    stats = defaultdict(lambda: {"count": 0, "size_bytes": 0, "selected_count": 0, "selected_bytes": 0})
    for row in rows:
        if row["exists"] == "yes":
            s = stats[row["category"]]
            s["count"] += 1
            s["size_bytes"] += row["size_bytes"]
        if row.get("selection_status") == "selected":
            s = stats[row["category"]]
            s["selected_count"] += 1
            s["selected_bytes"] += row["size_bytes"]

    summary_csv = output_dir / "synthese_categories.csv"
    with summary_csv.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "category",
            "files_present",
            "size_mb",
            "estimated_store_mb",
            "selected_files",
            "selected_size_mb",
            "selected_estimated_store_mb",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for category in sorted(stats):
            s = stats[category]
            writer.writerow({
                "category": category,
                "files_present": s["count"],
                "size_mb": format_mb(bytes_to_mb(s["size_bytes"])),
                "estimated_store_mb": format_mb(bytes_to_mb(s["size_bytes"]) * args.multiplier),
                "selected_files": s["selected_count"],
                "selected_size_mb": format_mb(bytes_to_mb(s["selected_bytes"])),
                "selected_estimated_store_mb": format_mb(bytes_to_mb(s["selected_bytes"]) * args.multiplier),
            })

    selected_inventory = {}
    for row in selected:
        # Retrouver l'objet meta original par chemin.
        for key, meta in inventory.items():
            relative_path = (meta.get("path") or key).replace("\\", "/")
            if relative_path == row["path"]:
                selected_inventory[key] = meta
                break

    selected_json = output_dir / "inventaire_selection_gemini.json"
    with selected_json.open("w", encoding="utf-8") as f:
        json.dump(selected_inventory, f, ensure_ascii=False, indent=2)

    manifest_txt = output_dir / "manifest_paths_selection.txt"
    manifest_txt.write_text("\n".join(row["path"] for row in selected) + "\n", encoding="utf-8")

    selected_dates = [row["_parsed_date"] for row in selected if row.get("_parsed_date")]
    cutoff = min(selected_dates).isoformat() if selected_dates else "Aucune date"

    total_present_bytes = sum(row["size_bytes"] for row in rows if row["exists"] == "yes")
    print("Analyse terminee")
    categories_label = ", ".join(args.categories) if args.categories else "toutes les categories"
    scope_label = "ces categories" if args.categories else "toutes les categories"
    print(f"Categories analysees : {categories_label}")
    print(f"Fichiers dans l'inventaire pour {scope_label} : {len(rows)}")
    print(f"Fichiers manquants localement : {len(missing_files)}")
    print(f"Taille PDF totale presente : {format_mb(bytes_to_mb(total_present_bytes))} Mo")
    print(f"Estimation store totale : {format_mb(bytes_to_mb(total_present_bytes) * args.multiplier)} Mo")
    print(f"Limite PDF retenue : {format_mb(raw_limit_mb)} Mo")
    print(f"Fichiers selectionnes : {len(selected)}")
    print(f"Taille PDF selectionnee : {format_mb(bytes_to_mb(cumulative_bytes))} Mo")
    print(f"Estimation store selectionnee : {format_mb(bytes_to_mb(cumulative_bytes) * args.multiplier)} Mo")
    print(f"Date la plus ancienne incluse : {cutoff}")
    print("")
    print(f"CSV detaille : {per_file_csv}")
    print(f"Synthese categories : {summary_csv}")
    print(f"Inventaire selection : {selected_json}")
    print(f"Manifest chemins : {manifest_txt}")


if __name__ == "__main__":
    main()
