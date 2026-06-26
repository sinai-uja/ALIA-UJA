"""
05_process_responses.py
=======================
Processes the 60 response files from the full Prolific study.

1. Reads the 60 xlsx response files from Google Forms.
2. Verifies gold standards for each annotator.
3. Generates corpus_final_3000_anotado.csv with the 3 annotations per sample.
4. Computes Fleiss' kappa and agreement statistics.

INPUT:
    - respuestas/*.xlsx               (60 files, 3 responses each)
    - ../data/corpus_final_decide_madrid.csv
    - ../annotation/gold_standard.csv

OUTPUT:
    - ../data/corpus_final_3000_anotado.csv

USAGE:
    python 05_process_responses.py [path_to_responses_folder]

    If no argument is passed, looks in ./respuestas/
"""

import os
import re
import sys
from collections import Counter

import openpyxl
import csv

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)

if len(sys.argv) > 1:
    RESPONSES_DIR = sys.argv[1]
else:
    RESPONSES_DIR = os.path.join(BASE, "respuestas")

CORPUS_ORIGINAL = os.path.join(ROOT, "data", "corpus_final_decide_madrid.csv")
GOLD_FILE = os.path.join(ROOT, "annotation", "gold_standard.csv")
OUTPUT = os.path.join(ROOT, "data", "corpus_final_3000_anotado.csv")

LABEL_MAP = {"A favor": "favor", "En contra": "contra", "Neutral": "neutral"}


def load_gold_labels():
    gold = {}
    with open(GOLD_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            gold[row["id"]] = row["gold_label"]
    return gold


def parse_xlsx(filepath):
    """
    Reads a Google Forms response xlsx.
    Returns:
      - annotations: {item_id: [label1, label2, label3]}
      - observations: {item_id: [obs1, obs2, obs3]}
      - annotators: [prolific_id1, ...]
    """
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    rows_data = []
    for row in ws.iter_rows(values_only=True):
        rows_data.append(list(row))
    wb.close()

    if len(rows_data) < 2:
        return {}, {}, []

    headers = [str(h) if h else "" for h in rows_data[0]]
    data_rows = rows_data[1:]

    id_pattern = re.compile(r"^\[(\w+)\] Tema:")
    obs_pattern = re.compile(r"^\[(\w+)\] Observaciones")

    col_map = {}
    obs_map = {}
    for i, h in enumerate(headers):
        m = id_pattern.match(h)
        if m:
            col_map[m.group(1)] = i
        m2 = obs_pattern.match(h)
        if m2:
            obs_map[m2.group(1)] = i

    prolific_col = 1
    annotators = []
    for row in data_rows:
        pid = str(row[prolific_col]) if row[prolific_col] else ""
        annotators.append(pid)

    annotations = {}
    observations = {}
    for item_id, col_idx in col_map.items():
        annotations[item_id] = []
        for row in data_rows:
            val = str(row[col_idx]) if col_idx < len(row) and row[col_idx] else ""
            annotations[item_id].append(val)

    for item_id, col_idx in obs_map.items():
        observations[item_id] = []
        for row in data_rows:
            val = str(row[col_idx]) if col_idx < len(row) and row[col_idx] else ""
            if val == "None":
                val = ""
            observations[item_id].append(val)

    return annotations, observations, annotators


def verify_gold(annotations, gold_labels, block_num, annotators):
    """Verifies gold standards. Returns list of annotators who fail."""
    n_annotators = len(annotators)
    failures = []

    for a_idx in range(n_annotators):
        correct = 0
        total = 0
        errors = []
        for gs_id, expected in gold_labels.items():
            if gs_id not in annotations:
                continue
            raw_response = annotations[gs_id][a_idx]
            response = LABEL_MAP.get(raw_response, raw_response.lower().strip())
            total += 1
            if response == expected:
                correct += 1
            else:
                errors.append(f"{gs_id}: answered '{response}', expected '{expected}'")

        pct = (correct / total * 100) if total > 0 else 0
        if correct < total:
            failures.append({
                "prolific_id": annotators[a_idx],
                "block": block_num,
                "correct": correct,
                "total": total,
                "errors": errors,
            })
            print(f"  FAIL Block {block_num} - {annotators[a_idx]}: {correct}/{total} ({pct:.0f}%)")
            for e in errors:
                print(f"    {e}")

    return failures


def compute_fleiss_kappa(table):
    n_items = len(table)
    if n_items == 0:
        return 0.0

    categories = sorted(set(k for row in table for k in row))
    n_raters = sum(table[0].values())

    if n_raters <= 1:
        return 1.0

    P_i = []
    for row in table:
        total = sum(row.values())
        sum_sq = sum(v * v for v in row.values())
        P_i.append((sum_sq - total) / (total * (total - 1)) if total > 1 else 1.0)
    P_bar = sum(P_i) / n_items

    p_j = {}
    for cat in categories:
        p_j[cat] = sum(row.get(cat, 0) for row in table) / (n_items * n_raters)
    P_e = sum(p ** 2 for p in p_j.values())

    if P_e == 1.0:
        return 1.0

    return (P_bar - P_e) / (1 - P_e)


def main():
    gold_labels = load_gold_labels()

    # Collect all response files
    files = sorted([
        f for f in os.listdir(RESPONSES_DIR)
        if f.endswith(".xlsx") and "Bloque" in f
    ])
    print(f"Files found: {len(files)}")

    all_annotations = {}  # {item_id: [label1, label2, label3]}
    all_observations = {}  # {item_id: [obs1, obs2, obs3]}
    all_failures = []
    total_annotators = 0

    for archivo in files:
        m = re.search(r"Bloque (\d+)", archivo)
        if not m:
            print(f"  Skipping (unrecognized block): {archivo}")
            continue
        block_num = int(m.group(1))

        filepath = os.path.join(RESPONSES_DIR, archivo)
        annotations, observations, annotators = parse_xlsx(filepath)

        if not annotators:
            print(f"  Block {block_num}: NO RESPONSES")
            continue

        total_annotators += len(annotators)

        # Verify gold
        failures = verify_gold(annotations, gold_labels, block_num, annotators)
        all_failures.extend(failures)

        # Save real annotations (not gold)
        for item_id, labels in annotations.items():
            if item_id.startswith("GS"):
                continue
            if item_id in all_annotations:
                all_annotations[item_id].extend(labels)
            else:
                all_annotations[item_id] = list(labels)

        for item_id, obs in observations.items():
            if item_id.startswith("GS"):
                continue
            if item_id in all_observations:
                all_observations[item_id].extend(obs)
            else:
                all_observations[item_id] = list(obs)

    # Gold standards summary
    print(f"\n=== Gold Standards ===")
    print(f"Total annotators: {total_annotators}")
    if all_failures:
        print(f"Annotators with failures: {len(all_failures)}")
        for f in all_failures:
            print(f"  Prolific ID: {f['prolific_id']} | Block {f['block']} | {f['correct']}/{f['total']}")
    else:
        print("All annotators passed 100% of gold standards.")

    # Read original corpus
    corpus = []
    with open(CORPUS_ORIGINAL, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            corpus.append(row)

    # Combine
    output_rows = []
    fleiss_table = []
    unanimous_agreement = 0
    no_majority = 0
    no_annotation = 0

    for row in corpus:
        item_id = str(row["id"])
        new_row = {
            "id": row["id"],
            "target": row["target"],
            "descripcion": row["descripcion"],
            "comentario": row["comentario"],
        }

        if item_id in all_annotations:
            labels = all_annotations[item_id]
            # Only the first 3 annotations (ignore extras for consistency)
            for i in range(min(len(labels), 3)):
                new_row[f"anotacion_{i+1}"] = LABEL_MAP.get(labels[i], labels[i])

            labels_norm = [LABEL_MAP.get(l, l) for l in labels[:3]]
            counter = Counter(labels_norm)
            majority = counter.most_common(1)[0]
            new_row["etiqueta_mayoria"] = majority[0]
            new_row["acuerdo"] = f"{majority[1]}/{len(labels_norm)}"

            if majority[1] == len(labels_norm):
                unanimous_agreement += 1
            if majority[1] == 1:
                no_majority += 1

            fleiss_row = {"favor": 0, "contra": 0, "neutral": 0}
            for l in labels_norm:
                if l in fleiss_row:
                    fleiss_row[l] += 1
            fleiss_table.append(fleiss_row)

            # Only the first 3 observations
            if item_id in all_observations:
                obs_list = all_observations[item_id][:3]
                for i, obs in enumerate(obs_list):
                    if obs.strip():
                        new_row[f"observacion_{i+1}"] = obs.strip()
        else:
            new_row["anotacion_1"] = ""
            new_row["anotacion_2"] = ""
            new_row["anotacion_3"] = ""
            new_row["etiqueta_mayoria"] = ""
            new_row["acuerdo"] = ""
            no_annotation += 1

        output_rows.append(new_row)

    # Fixed columns
    fieldnames = ["id", "target", "descripcion", "comentario",
                  "anotacion_1", "anotacion_2", "anotacion_3",
                  "etiqueta_mayoria", "acuerdo",
                  "observacion_1", "observacion_2", "observacion_3"]

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)

    with_annotations = len(corpus) - no_annotation
    print(f"\n=== Result ===")
    print(f"Saved: {OUTPUT}")
    print(f"Total samples: {len(corpus)}")
    print(f"With annotations: {with_annotations}")
    print(f"Without annotations: {no_annotation}")

    if with_annotations > 0:
        pct_unanimous = unanimous_agreement / with_annotations * 100
        print(f"\n=== Annotator Agreement ===")
        print(f"Unanimous agreement (3/3): {unanimous_agreement}/{with_annotations} ({pct_unanimous:.1f}%)")
        print(f"No majority (1/3): {no_majority}")

        kappa = compute_fleiss_kappa(fleiss_table)
        print(f"Fleiss' kappa: {kappa:.3f}")
        if kappa < 0.20:
            interp = "Poor"
        elif kappa < 0.40:
            interp = "Slight"
        elif kappa < 0.60:
            interp = "Moderate"
        elif kappa < 0.80:
            interp = "Substantial"
        else:
            interp = "Almost perfect"
        print(f"Interpretation (Landis & Koch): {interp}")

        # Distribution
        all_labels = []
        for item_id, labels in all_annotations.items():
            for l in labels[:3]:
                all_labels.append(LABEL_MAP.get(l, l))
        label_dist = Counter(all_labels)
        total_labels = sum(label_dist.values())
        print(f"\n=== Label Distribution ===")
        for label, count in sorted(label_dist.items()):
            print(f"  {label}: {count} ({count/total_labels*100:.1f}%)")

        # Cases without majority
        if no_majority > 0:
            print(f"\n=== Cases without majority (1/3) ===")
            for row in output_rows:
                if row.get("acuerdo") == "1/3":
                    print(f"  id={row['id']}: {row.get('anotacion_1','')}, {row.get('anotacion_2','')}, {row.get('anotacion_3','')} -> {row['etiqueta_mayoria']}")


if __name__ == "__main__":
    main()
