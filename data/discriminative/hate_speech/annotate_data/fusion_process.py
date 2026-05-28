#!/usr/bin/env python3
"""Fusion of Experts inference pipeline.

This module provides utilities to load collected annotations, build features
used by a Fusion of Experts (FoE) model, load a model artifact and run
inference. Results are written as JSON Lines (JSONL) with metadata and
predicted scores.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

try:
    import torch
    import torch.nn as nn
except Exception:
    # Allow static analysis / doc generation without PyTorch installed.
    torch = None
    nn = None


class SentimentMLP(nn.Module if nn is not None else object):
    """A small MLP used as the FoE model implementation for sentiment analysis task from reference.

    The class is defined to allow module import even when PyTorch is not
    available; attempting to instantiate the class without PyTorch will raise
    an ImportError.

    Args:
        input_dim: Dimensionality of the input feature vector.
        hidden_dim: Size of the hidden layers.
        n_classes: Number of output classes.
        dropout: Dropout probability applied before the final layer.
    """

    def __init__(self, input_dim: int, hidden_dim: int = 1024, n_classes: int = 2, dropout: float = 0.5) -> None:
        if nn is None:
            raise ImportError("PyTorch is required for SentimentMLP")
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, n_classes)
        self.dropout = nn.Dropout(p=dropout)
        self.relu = nn.ReLU()

    def forward(self, x: Any) -> Any:
        """Forward pass.

        Args:
            x: Input tensor of shape (batch_size, input_dim).

        Returns:
            Logits tensor of shape (batch_size, n_classes).
        """
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        x = self.dropout(x)
        return self.fc3(x)


class FoE:
    """Minimal wrapper around the sentiment MLP used by saved artifacts.

    The wrapper stores the instantiated model, a small resolved spec and a
    reference to the torch/nn modules so downstream code can use them.
    """

    def __init__(self, input_dim: int, model_spec: dict[str, Any] | None = None) -> None:
        """Create a FoE wrapper and instantiate the underlying MLP.

        Args:
            input_dim: Dimensionality of the input feature vector.
            model_spec: Optional dictionary with model hyperparameters
                (e.g. hidden_dim, dropout, n_classes).

        Raises:
            ImportError: If PyTorch is not available in the environment.
        """
        if torch is None or nn is None:
            raise ImportError("torch is required for FoE")
        spec = dict(model_spec or {})
        hidden_dim = int(spec.get("hidden_dim", 1024))
        dropout = float(spec.get("dropout", 0.5))
        n_classes = int(spec.get("n_classes", 2))
        self._torch = torch
        self._nn = nn
        self.model = SentimentMLP(
            input_dim=input_dim,
            hidden_dim=hidden_dim,
            n_classes=n_classes,
            dropout=dropout,
        )
        self.model_kind = "sentiment_mlp"
        self.resolved_spec = {
            "kind": self.model_kind,
            "hidden_dim": hidden_dim,
            "dropout": dropout,
            "n_classes": n_classes,
        }


def _normalize_binary_labels(series: pd.Series) -> pd.Series:
    """Normalize a series to binary labels (0/1) using pandas nullable dtype.

    Converts common boolean-like values ("true", "yes", "1", ...) to
    integer 1, false-like values to 0 and any non-convertible values to
    <NA>. The returned series uses the pandas ``Int64`` nullable integer dtype.

    Args:
        series: A pandas Series containing heterogeneous values to normalize.

    Returns:
        A pandas Series with dtype ``Int64`` containing values 0, 1 or <NA>.
    """

    mapped = {
        "true": 1,
        "false": 0,
        "1": 1,
        "0": 0,
        "yes": 1,
        "no": 0,
        "y": 1,
        "n": 0,
    }

    normalized = series.copy().where(series.notna(), pd.NA)
    bool_converted = normalized.map({True: 1, False: 0})
    normalized = bool_converted.where(bool_converted.notna(), normalized)

    is_str = normalized.apply(lambda x: isinstance(x, str))
    if is_str.any():
        normalized.loc[is_str] = normalized.loc[is_str].astype(str).str.strip().str.lower().map(mapped)

    normalized = pd.to_numeric(normalized, errors="coerce")
    normalized = normalized.where(normalized.isin([0, 1]), pd.NA)
    return normalized.astype("Int64")


def load_artifact(path: Path) -> dict[str, object]:
    """Load a model artifact serialized with pickle from disk.

    Args:
        path: Path to the pickle file containing the artifact.

    Returns:
        The deserialized Python object (expected to be a dict with the model
        artifact structure).

    Raises:
        FileNotFoundError: If the file does not exist (raised by Path.open).
        pickle.UnpicklingError: If the file content is not a valid pickle.
    """

    with path.open("rb") as f:
        return pickle.load(f)


def load_config(path: Path) -> dict[str, object]:
    """Load a YAML configuration file.

    Args:
        path: Path to the YAML file.

    Returns:
        A dict with the configuration (empty dict if the YAML is empty).

    Raises:
        ValueError: If the YAML root is not a mapping.
    """

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid config format in {path}: expected a mapping.")
    return data


def resolve_annotations_root(config_path: Path, config: dict[str, object]) -> Path:
    """Resolve the path to the annotations directory.

    The configured path can be absolute or relative to the configuration
    file directory given by ``config_path``.

    Args:
        config_path: Path to the configuration file (used as base for
            relative paths).
        config: Configuration dictionary.

    Returns:
        Absolute Path to the annotations directory.

    Raises:
        ValueError: If the key ``annotated_data_folder`` is missing from config.
        FileNotFoundError: If the resolved path does not exist.
    """

    annotated_data_value = config.get("annotated_data_folder")
    if not annotated_data_value:
        raise ValueError("Config missing required key 'annotated_data_folder'.")

    annotations_root = Path(str(annotated_data_value))
    if not annotations_root.is_absolute():
        annotations_root = (config_path.parent / annotations_root).resolve()
    if not annotations_root.exists():
        raise FileNotFoundError(f"Annotated data folder not found: {annotations_root}")
    return annotations_root


def resolve_output_jsonl(config_path: Path, config: dict[str, object]) -> Path:
    """Resolve the output JSONL path.

    Accepts absolute paths or paths relative to the configuration file.

    Args:
        config_path: Path to the configuration file.
        config: Configuration dictionary.

    Returns:
        Absolute Path to the output JSONL file.

    Raises:
        ValueError: If the key ``output_jsonl`` is missing from config.
    """

    output_value = config.get("output_jsonl")
    if not output_value:
        raise ValueError("Config missing required key 'output_jsonl'.")

    output_jsonl = Path(str(output_value))
    if not output_jsonl.is_absolute():
        output_jsonl = (config_path.parent / output_jsonl).resolve()
    return output_jsonl


def load_collected_annotations(
    annotations_root: Path,
    model_columns: list[str],
    text_column: str = "text",
) -> pd.DataFrame:
    """Load and pivot collected JSONL annotations from model outputs.

    Recursively searches for ``*.jsonl`` files under ``annotations_root`` and
    extracts records where ``model_alias`` is in ``model_columns``. The
    returned DataFrame contains one column per model with the last seen
    annotation and an associated explanation column for each model.

    Args:
        annotations_root: Root directory to search for JSONL files.
        model_columns: List of model aliases expected in the records.
        text_column: Name of the text column to extract (default: "text").

    Returns:
        A ``pd.DataFrame`` with columns: ``source``, ``id``, the text column,
        one column per model with the binary label and one ``<model>_explanation``
        column per model.

    Raises:
        ValueError: If no valid records for the requested models are found.
    """

    records: list[dict[str, object]] = []
    model_set = set(model_columns)

    for path in sorted(annotations_root.glob("**/*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    rec = json.loads(line_str)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue

                model_alias = str(rec.get("model_alias", "")).strip()
                if model_alias not in model_set:
                    continue

                source = str(rec.get("source", "")).strip()
                comment_id = str(rec.get("id", "")).strip()
                if not source or not comment_id:
                    continue

                text_value = rec.get(text_column, rec.get("text", rec.get("comment", "")))
                records.append(
                    {
                        "source": source,
                        "id": comment_id,
                        text_column: str(text_value) if text_value is not None else "",
                        "model_alias": model_alias,
                        "is_hate": rec.get("is_hate"),
                        "explanation": str(rec.get("explanation", "")) if rec.get("explanation") is not None else "",
                    }
                )

    if not records:
        raise ValueError(f"No collected annotations found for models={sorted(model_set)} under {annotations_root}")

    frame = pd.DataFrame(records)
    frame = frame[frame["id"].astype(bool)].copy()
    if frame.empty:
        raise ValueError("No valid collected annotation records were loaded.")

    index_cols = ["source", "id"]
    meta = frame[["source", "id", text_column]].drop_duplicates(subset=index_cols).reset_index(drop=True)

    pivot_bin = frame.pivot_table(index=index_cols, columns="model_alias", values="is_hate", aggfunc="last", dropna=False).reset_index()
    pivot_exp = frame.pivot_table(index=index_cols, columns="model_alias", values="explanation", aggfunc="last", dropna=False).reset_index()

    base = pivot_bin.merge(pivot_exp, on=index_cols, how="left", suffixes=("", "_expl"))
    base = base.merge(meta, on=index_cols, how="left")

    for model in model_columns:
        if model not in base.columns:
            base[model] = pd.NA
        expl_col = f"{model}_explanation"
        expl_col_alt = f"{model}_expl"
        if expl_col not in base.columns and expl_col_alt in base.columns:
            base[expl_col] = base[expl_col_alt].fillna("").astype(str)
            base = base.drop(columns=[expl_col_alt])
        elif expl_col not in base.columns:
            base[expl_col] = ""

    base[text_column] = base[text_column].fillna("").astype(str)
    for model in model_columns:
        base[f"{model}_explanation"] = base[f"{model}_explanation"].fillna("").astype(str)

    return base


def transform_text_embeddings(texts: pd.Series, meta: dict[str, object]) -> np.ndarray:
    """Generate text embeddings using SentenceTransformers.

    Args:
        texts: pandas Series with texts to encode.
        meta: Metadata describing embedding type and model name.

    Returns:
        A numpy float32 array with one embedding vector per input row.

    Raises:
        ValueError: If meta indicates an unsupported type or is missing model_name.
        ImportError: If the `sentence-transformers` package is not installed.
    """

    if str(meta.get("type", "")).lower() != "sentence_transformer":
        raise ValueError(f"Unsupported embedding meta type: {meta.get('type')}")

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise ImportError(
            "sentence-transformers is required for inference with sentence_transformer features. "
            "Install with: pip install sentence-transformers"
        ) from exc

    model_name = str(meta.get("model_name", ""))
    if not model_name:
        raise ValueError("SentenceTransformer meta is missing model_name.")
    series = texts.fillna("").astype(str)
    model = SentenceTransformer(model_name, local_files_only=True)
    return np.asarray(model.encode(series.tolist(), show_progress_bar=False), dtype=np.float32)


def build_features(
    frame: pd.DataFrame,
    foe_cfg: dict[str, object],
    feature_meta: dict[str, object],
    model_columns: list[str],
) -> tuple[np.ndarray, pd.DataFrame]:
    """Build the feature matrix used for inference from config metadata.

    All configuration that controls feature construction is expected to come
    from the external YAML config (``foe_cfg`` and ``feature_meta``). The
    binary annotation columns are specified via ``model_columns``.

    Args:
        frame: DataFrame with collected annotations (as returned by
            ``load_collected_annotations``).
        foe_cfg: Configuration dictionary describing input feature toggles
            and text column names (from the config file).
        feature_meta: Metadata describing embedding processors (from config).
        model_columns: List of model alias column names to use for binary
            annotations.

    Returns:
        A tuple ``(x, processed)`` where ``x`` is an ndarray with features
        (n_samples x n_features) and ``processed`` is the DataFrame with the
        same rows used to build ``x``.

    Raises:
        ValueError: If required entries are missing in the config or if the
            configuration disables all feature sources.
    """

    if not isinstance(model_columns, list) or not model_columns:
        raise ValueError("Config missing model_columns.")

    input_features = foe_cfg.get("input_features", {}) or {}
    use_binary = bool(input_features.get("binary_annotations", True))
    use_comment = bool(input_features.get("comment_embeddings", True))
    use_explanations = bool(input_features.get("explanation_embeddings", True))

    if not any([use_binary, use_comment, use_explanations]):
        raise ValueError("Configuration disables all feature levels.")

    frame = frame.copy()
    candidate_text_columns = [str(foe_cfg.get("text_column", "")).strip(), "text", "comment"]
    text_column = next((column for column in candidate_text_columns if column and column in frame.columns), None)
    if text_column is None and use_comment:
        raise ValueError("No usable text column found for comment embeddings.")

    if use_binary:
        for column in model_columns:
            frame[column] = _normalize_binary_labels(frame[column])
        frame = frame.dropna(subset=model_columns)

    feature_blocks: list[np.ndarray] = []
    if use_binary:
        feature_blocks.append(frame[model_columns].astype(int).to_numpy())

    if use_comment:
        meta = feature_meta.get("comment_embeddings")
        if not isinstance(meta, dict):
            raise ValueError("Config feature_meta is missing comment_embeddings metadata.")
        feature_blocks.append(transform_text_embeddings(frame[text_column], meta))

    if use_explanations:
        processors = feature_meta.get("explanation_embeddings")
        if not isinstance(processors, dict) or not processors.get("columns"):
            raise ValueError("Config feature_meta is missing explanation_embeddings metadata.")

        explanation_blocks: list[np.ndarray] = []
        for column_meta in processors["columns"]:
            model_col = str(column_meta.get("model_column", ""))
            if not model_col:
                raise ValueError("Explanation processor entry missing model_column.")
            expl_col = f"{model_col}_explanation"
            if expl_col not in frame.columns:
                raise ValueError(f"Expected explanation column not found: {expl_col}")
            explanation_blocks.append(transform_text_embeddings(frame[expl_col], column_meta.get("meta", {})))

        if not explanation_blocks:
            raise ValueError("No explanation embeddings were generated for inference.")

        stacked = np.hstack(explanation_blocks)
        pca = processors.get("pca")
        if pca is not None:
            stacked = pca.transform(stacked)
        feature_blocks.append(stacked)

    x = np.hstack(feature_blocks)
    return x, frame


def load_model(artifact: dict[str, object]):
    """Instantiate a FoE object and load its weights from the artifact.

    Args:
        artifact: Dictionary that must contain the key ``model_payload`` with
            model specification and ``state_dict``.

    Returns:
        A ``FoE`` instance with loaded weights.

    Raises:
        ValueError: If the payload is missing or not of the expected type.
    """

    payload = artifact.get("model_payload")
    if not isinstance(payload, dict):
        raise ValueError("Artifact model payload is missing or invalid.")

    model_kind = str(payload.get("model_kind", "")).lower()
    if not model_kind.startswith("torch_"):
        raise ValueError(f"Unsupported model payload: {model_kind}")

    model = FoE(input_dim=int(payload["input_dim"]), model_spec=payload["architecture_spec"])
    model.model.load_state_dict(payload["state_dict"])
    return model


def predict(model: Any, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Run inference on the feature matrix ``x``.

    Args:
        model: FoE object previously loaded with ``load_model``.
        x: Numpy feature matrix (n_samples x n_features).

    Returns:
        A tuple ``(preds, probs)`` where ``preds`` are predicted class labels
        (int array) and ``probs`` are the positive-class probabilities (float).

    Raises:
        ImportError: If PyTorch is not available in the environment.
    """

    try:
        import torch
    except ImportError as exc:
        raise ImportError("Torch is required to run a saved FoE torch model.") from exc

    model._torch = torch
    model.model.eval()
    with torch.no_grad():
        logits = model.model(torch.tensor(x, dtype=torch.float32))
        probs = torch.softmax(logits, dim=-1)[:, 1].cpu().numpy()
        preds = logits.argmax(dim=1).cpu().numpy()
    return preds, probs


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Namespace with options `config` and `model_artifact`.
    """

    parser = argparse.ArgumentParser(description="Fuse collected annotations with a saved FoE model.")
    parser.add_argument("--config", type=Path, default=None, help="Optional YAML config with input/output paths.")
    parser.add_argument("--model-artifact", type=Path, default=None, help="Path to the saved FoE artifact pickle.")
    return parser.parse_args()


def main() -> int:
    """Main entry point for the script.

    The main flow is:
    1. Load configuration and model artifact.
    2. Load collected annotations and build features.
    3. Run inference and attach results to the processed DataFrame.
    4. Save results to JSONL.

    Returns:
        Exit code (0 on success).
    """

    args = parse_args()
    config_data: dict[str, object] = {}
    config_path = args.config
    if config_path.exists():
        config_data = load_config(config_path)

    artifact_value = args.model_artifact or config_data.get("model_artifact")
    if not artifact_value:
        raise ValueError("A model artifact path must be provided via --model-artifact or config.")
    artifact_path = Path(str(artifact_value))

    annotations_root = resolve_annotations_root(config_path, config_data)
    output_jsonl = resolve_output_jsonl(config_path, config_data)

    artifact = load_artifact(artifact_path)
    model_columns = config_data.get("model_columns")
    if not isinstance(model_columns, list) or not model_columns:
        raise ValueError("Config is missing model_columns for fusion.")

    foe_cfg = config_data.get("foe_config", {}) or {}
    feature_meta = config_data.get("feature_meta", {}) or {}

    artifact_feature_meta = artifact.get("feature_meta") if isinstance(artifact, dict) else None
    artifact_pca = None
    if isinstance(artifact_feature_meta, dict):
        artifact_pca = artifact_feature_meta.get("pca")
    if artifact_pca is not None:
        processors = feature_meta.get("explanation_embeddings")
        if not isinstance(processors, dict):
            feature_meta["explanation_embeddings"] = {"columns": [], "pca": artifact_pca}
        else:
            processors["pca"] = artifact_pca

    input_models = [str(model) for model in model_columns]
    collected = load_collected_annotations(annotations_root, input_models)
    x, processed = build_features(collected, foe_cfg, feature_meta, input_models)
    model = load_model(artifact)
    preds, probs = predict(model, x)

    processed = processed.reset_index(drop=True)
    processed["foe_eval"] = preds.astype(int)
    processed["foe_score"] = probs.astype(float)

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as fh:
        for rec in processed.reset_index(drop=True).to_dict(orient="records"):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Saved fused annotations and predictions to {output_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())