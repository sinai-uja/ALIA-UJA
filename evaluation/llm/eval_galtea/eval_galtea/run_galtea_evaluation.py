"""
Run Galtea Evaluations — Generic script

Usage:
    python run_galtea_evaluation.py -c config.yaml

Expects a YAML config with sections:
  - galtea.api_key
  - test.test_id, test.version_id, test.limit (0 = no limit)
  - galtea_metrics (list of {name: ...})
  - evaluation.export_only_success, evaluation.wait_timeout_s, evaluation.wait_poll_s
  - predictions_file (path to CSV)
  - output_file (path for output CSV)

The predictions CSV must contain columns: input, expected_output, actual_output.
"""

import argparse
import csv
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import tqdm
import yaml

from galtea import Galtea
from galtea.domain.models.metric import Metric


# =========================
# UTILITIES
# =========================


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_predictions(csv_path: str) -> List[Dict]:
    """Load predictions CSV with columns: input, expected_output, actual_output."""
    rows: List[Dict] = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("input", "").strip():
                rows.append({
                    "input": row["input"].strip(),
                    "expected_output": row.get("expected_output", "").strip(),
                    "actual_output": row.get("actual_output", "").strip(),
                })
    print(f"Loaded {len(rows)} predictions from: {csv_path}")
    return rows


# =========================
# CREATE EVALUATIONS
# =========================


def run_evaluations(
    galtea: Galtea,
    cfg: dict,
    test_id: str,
    version_id: str,
    predictions: List[Dict],
) -> List[Dict]:
    """
    For each prediction row:
      1. Find the existing Galtea test case by input text
      2. Create evaluation with the LLM Judge(s) (actual_output)
    Returns list of dicts with eval_id + original data.
    """
    limit = cfg.get("test", {}).get("limit", 0)
    if limit > 0:
        predictions = predictions[:limit]

    # Build input -> test_case_id lookup from already-uploaded test cases
    print("Loading test cases from Galtea...")
    all_tcs = galtea.test_cases.list(test_id=test_id)
    tc_lookup: Dict[str, str] = {tc.input.strip(): tc.id for tc in all_tcs}
    print(f"  {len(tc_lookup)} test cases found in Galtea.")

    created: List[Dict] = []

    for row in tqdm.tqdm(predictions, desc="Sending to Galtea"):
        tc_id = tc_lookup.get(row["input"])
        if not tc_id:
            print(f"  Warning: test case not found for: {row['input'][:60]}...")
            continue
        try:
            evals = galtea.evaluations.create_single_turn(
                version_id=version_id,
                test_case_id=tc_id,
                metrics=cfg["galtea_metrics"],
                actual_output=row["actual_output"],
            )
            for e in evals:
                created.append({
                    "eval_id": e.id,
                    "input": row["input"],
                    "expected_output": row["expected_output"],
                    "actual_output": row["actual_output"],
                })
        except Exception as ex:
            print(f"  Error: {ex}")

    return created


# =========================
# WAIT FOR EVALUATIONS
# =========================


def wait_until_done(
    galtea: Galtea,
    eval_ids: List[str],
    timeout_s: int = 2400,
    poll_s: float = 5.0,
) -> None:
    if not eval_ids:
        return

    deadline = time.time() + timeout_s
    pending: Set[str] = set(eval_ids)

    print(f"Waiting for {len(pending)} evaluations (timeout: {timeout_s}s)...")
    while pending and time.time() < deadline:
        done_now = []
        for eid in pending:
            try:
                ev = galtea.evaluations.get(evaluation_id=eid)
                if getattr(ev, "status", None) in ("SUCCESS", "FAILED"):
                    done_now.append(eid)
            except Exception:
                continue
        for eid in done_now:
            pending.remove(eid)
        if pending:
            time.sleep(poll_s)

    if pending:
        print(f"Warning: {len(pending)} evaluations still pending after {timeout_s}s")
    else:
        print("All evaluations completed.")


# =========================
# EXPORT TO CSV
# =========================


def export_to_csv(
    galtea: Galtea,
    created: List[Dict],
    output_file: str,
    export_only_success: bool = True,
) -> str:
    metrics_cache: Dict[str, Optional[Metric]] = {}
    rows: List[Dict] = []

    status_counts: Dict[str, int] = {}
    ev_cache: Dict[str, object] = {}
    for item in created:
        eid = item["eval_id"]
        try:
            ev = galtea.evaluations.get(evaluation_id=eid)
        except Exception:
            ev = None
        ev_cache[eid] = ev
        st = getattr(ev, "status", "MISSING") if ev else "MISSING"
        status_counts[st] = status_counts.get(st, 0) + 1

    print(f"Status summary: {status_counts}")

    for item in created:
        eid = item["eval_id"]
        ev = ev_cache.get(eid)
        if ev is None:
            continue
        if export_only_success and getattr(ev, "status", None) != "SUCCESS":
            continue

        metric_name = ""
        mid = getattr(ev, "metric_id", None)
        if mid:
            if mid not in metrics_cache:
                try:
                    metrics_cache[mid] = galtea.metrics.get(mid)
                except Exception:
                    metrics_cache[mid] = None
            m = metrics_cache.get(mid)
            if m:
                metric_name = m.name or ""

        rows.append({
            "metric_name": metric_name,
            "evaluation_id": ev.id,
            "score": ev.score if ev.score is not None else "",
            "reason": ev.reason or "",
            "question": item["input"],
            "expected_answer": item["expected_output"],
            "model_answer": item["actual_output"],
            "status": ev.status,
            "created_at": ev.created_at,
        })

    fieldnames = [
        "metric_name", "evaluation_id", "score", "reason",
        "question", "expected_answer", "model_answer",
        "status", "created_at",
    ]

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Exported {len(rows)} evaluations to: {output_file}")
    return output_file


# =========================
# MAIN
# =========================


def main(config_path: str) -> None:
    cfg = load_config(path=config_path)

    if not cfg.get("galtea", {}).get("api_key"):
        raise ValueError("galtea.api_key is empty in the config")

    eval_cfg = cfg["evaluation"]
    test_cfg = cfg["test"]

    predictions = load_predictions(cfg["predictions_file"])

    with Galtea(api_key=cfg["galtea"]["api_key"]) as galtea:
        created = run_evaluations(
            galtea=galtea,
            cfg=cfg,
            test_id=test_cfg["test_id"],
            version_id=test_cfg["version_id"],
            predictions=predictions,
        )

        print(f"\nCreated {len(created)} evaluations. Waiting for results...")
        wait_until_done(
            galtea=galtea,
            eval_ids=[item["eval_id"] for item in created],
            timeout_s=eval_cfg["wait_timeout_s"],
            poll_s=eval_cfg["wait_poll_s"],
        )

        output_csv = cfg["output_file"].rsplit(".", 1)
        output_csv = f"{output_csv[0]}_galtea_ev.csv"
        export_to_csv(
            galtea=galtea,
            created=created,
            output_file=output_csv,
            export_only_success=eval_cfg["export_only_success"],
        )

        print(f"\nDone. CSV saved at: {output_csv}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate LLM predictions with Galtea LLM Judges")
    parser.add_argument("-c", "--config", required=True, help="Path to YAML config file")
    args = parser.parse_args()
    main(config_path=args.config)
