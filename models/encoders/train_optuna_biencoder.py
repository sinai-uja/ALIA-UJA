"""
Bi-Encoder Hyperparameter Search with Optuna
=============================================
This script performs an automated hyperparameter search for fine-tuning a
bi-encoder (SentenceTransformer) retrieval model using the Optuna framework.

Pipeline overview:
    1. Load triplet dataset  (anchor, positive, negative)
    2. Build a SequentialEvaluator combining:
         - TripletEvaluator            → pairwise cosine accuracy
         - InformationRetrievalEvaluator → MRR@k, NDCG@k, MAP@k, Recall@k
    3. For each Optuna trial, train a SentenceTransformer with
       CachedMultipleNegativesRankingLoss
    4. Optimise toward minimum eval loss
    5. Report the best hyperparameters at the end of the search

Dependencies:
    torch, optuna, datasets, sentence-transformers

Configuration is imported from ``config_optuna.py``. 

Usage:
    bash alia/models/encoders/launchers/train/launcher_optuna_parent.sh --values 128, 256, 512
"""
# Library imports
import os, sys, json
try:
    import torch
    import optuna
    from datasets import Dataset
    from sentence_transformers.training_args import BatchSamplers
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        models,
        losses,
    )
    from transformers import TrainerCallback
    from sentence_transformers.evaluation import (
        TripletEvaluator,
        InformationRetrievalEvaluator,
        SequentialEvaluator,
    )
except ImportError as exc:
    print(f"[ERROR] Missing dependency: {exc}")
    print("Please install: torch, optuna, datasets, sentence-transformers")
    raise

# Project-level imports
from config_optuna import (
    MODEL_PATH,
    DATASET_OPTUNA_PATH,
    OUTPUT_BASE_DIR_TEMPLATE,
    ALIA_UTILS_PATH,
    EPOCHS,
    N_TRIALS,
    MAX_SEQ_LENGTH,
    TRAIN_SIZE_OPTUNA,
    EVAL_SPLIT_RATIO,
    RANDOM_SEED,
    LEARNING_RATE_RANGE,
    MINI_BATCH_SIZE_OPTIONS,
    WARMUP_RATIO_RANGE,
    WEIGHT_DECAY_RANGE,
    OPTUNA_STARTUP_TRIALS,
    OPTUNA_STUDY_NAME_TEMPLATE,
    OPTUNA_DB_TEMPLATE,
    RUN_NAME_TEMPLATE,
    IR_EVALUATOR_BATCH_SIZE,
    EVALUATION_K_BIENCODER,
    LOGGING_STEPS,
    WANDB_OFFLINE,
    PYTORCH_CUDA_ALLOC_CONF
)

sys.path.append(os.path.realpath(ALIA_UTILS_PATH))
from utils.utils_alia import RichArgumentParser

print("✓ All libraries imported successfully.")

# CLI arguments

def get_args():
    """Parse command-line arguments for batch size and GPU selection."""
    parser = RichArgumentParser(
        description="Optuna hyperparameter search for a SentenceTransformer bi-encoder."
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=64,
        help="Per-device training batch size (default: 64).",
    )
    parser.add_argument(
        "--gpu",
        type=int,
        default=0,
        help="CUDA device index to use (default: 0).",
    )
    return parser.parse_args()


ARGS = get_args()
print(f"→ batch_size={ARGS.batch_size}  gpu={ARGS.gpu}")

# Environment setup
os.environ["WANDB_MODE"] = "offline" if WANDB_OFFLINE else "online"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = PYTORCH_CUDA_ALLOC_CONF
os.environ["CUDA_VISIBLE_DEVICES"] = str(ARGS.gpu)

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"→ Using device: {DEVICE}")

# Derive run metadata from config templates
output_base_dir = OUTPUT_BASE_DIR_TEMPLATE.format(batch_size=ARGS.batch_size)
type_hn  = "random" if "random" in DATASET_OPTUNA_PATH else "top"
run_name = RUN_NAME_TEMPLATE.format(type_hn=type_hn)

# 1. Dataset loading
def load_triplets(path: str) -> Dataset:
    """
    Load a JSONL file of training triplets into a HuggingFace ``Dataset``.
    Each line is expected to have the following structure::
        {
            "messages":          [{"content": "<query>"}],
            "positive_messages": [[{"content": "<positive doc>"}]],
            "negative_messages": [[{"content": "<negative doc>"}]]
        }
    Lines that are malformed or lack a negative are silently skipped.
    Args:
        path: Path to the ``.jsonl`` triplet file.

    Returns:
        A ``Dataset`` with columns ``["query", "positive", "negative"]``.
    """
    queries, positives, negatives = [], [], []

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                item = json.loads(line)
                query    = item["messages"][0]["content"]
                positive = item["positive_messages"][0][0]["content"]

                # Only include examples that have at least one hard negative
                if item.get("negative_messages") and item["negative_messages"][0]:
                    negative = item["negative_messages"][0][0]["content"]
                    queries.append(query)
                    positives.append(positive)
                    negatives.append(negative)
            except (KeyError, IndexError):
                continue  # Skip malformed lines

    return Dataset.from_dict(
        {"query": queries, "positive": positives, "negative": negatives}
    )


print("Loading dataset …")
full_dataset = load_triplets(DATASET_OPTUNA_PATH)
print(f"  → {len(full_dataset):,} triplets loaded.")

# Subsample, then split into train / eval
full_dataset = full_dataset.train_test_split(
    train_size=TRAIN_SIZE_OPTUNA, seed=RANDOM_SEED
)["train"]

split         = full_dataset.train_test_split(test_size=EVAL_SPLIT_RATIO, seed=RANDOM_SEED)
train_dataset = split["train"]
eval_dataset  = split["test"]
print(f"  → Train: {len(train_dataset):,} | Eval: {len(eval_dataset):,}")


# 2. Evaluator construction
def build_evaluator(eval_ds: Dataset, name_prefix: str = "") -> SequentialEvaluator:
    """
    Build a ``SequentialEvaluator`` combining two complementary evaluators:

    1. **TripletEvaluator** — measures the fraction of triplets where
       ``sim(anchor, positive) > sim(anchor, negative)`` (cosine similarity).

    2. **InformationRetrievalEvaluator** — constructs a retrieval corpus from
       the positives and negatives, marks only the positive as relevant for each
       query, and computes MRR@k, NDCG@k, MAP@k, and Recall@k.

    Args:
        eval_ds:     Evaluation ``Dataset`` with columns
                     ``["anchor", "positive", "negative"]``.
        name_prefix: Optional string prepended to each evaluator's name tag.

    Returns:
        A ``SequentialEvaluator`` that runs both evaluators in sequence.
    """
    anchors   = eval_ds["query"]
    positives = eval_ds["positive"]
    negatives = eval_ds["negative"]

    # ── TripletEvaluator ──────────────────────────────────────────────────────
    triplet_evaluator = TripletEvaluator(
        anchors=anchors,
        positives=positives,
        negatives=negatives,
        name=f"{name_prefix}triplet",
        # Uses cosine distance by default
    )

    # ── InformationRetrievalEvaluator ─────────────────────────────────────────
    # Build a minimal corpus: one positive + one negative per query.
    # Each query has exactly one relevant document (its positive).
    queries  = {str(i): q for i, q in enumerate(anchors)}
    corpus   = {}
    relevant = {}

    for i, (pos, neg) in enumerate(zip(positives, negatives)):
        pos_id = f"pos_{i}"
        neg_id = f"neg_{i}"
        corpus[pos_id] = pos
        corpus[neg_id] = neg
        relevant[str(i)] = {pos_id}   # Only the positive is relevant

    ir_evaluator = InformationRetrievalEvaluator(
        queries=queries,
        corpus=corpus,
        relevant_docs=relevant,
        name=f"{name_prefix}ir",
        mrr_at_k=EVALUATION_K_BIENCODER,
        ndcg_at_k=EVALUATION_K_BIENCODER,
        map_at_k=EVALUATION_K_BIENCODER,
        show_progress_bar=False,
        batch_size=IR_EVALUATOR_BATCH_SIZE,
    )

    return SequentialEvaluator([triplet_evaluator, ir_evaluator])

print("Building evaluators …")
evaluator = build_evaluator(eval_dataset, name_prefix="eval_")
print("  → Evaluators ready.")

# 3. Model factory
def build_model() -> SentenceTransformer:
    """
    Instantiate and configure a ``SentenceTransformer`` bi-encoder for training.

    Architecture:
        - **Transformer** backbone loaded from ``MODEL_PATH``
        - **Mean pooling** over token embeddings

    Gradient checkpointing is enabled on the backbone to reduce peak GPU memory.

    Returns:
        A ``SentenceTransformer`` ready for fine-tuning.
    """
    transformer = models.Transformer(
        MODEL_PATH,
        max_seq_length=MAX_SEQ_LENGTH,
        model_args={"trust_remote_code": True},
    )
    transformer.auto_model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )

    pooling = models.Pooling(
        transformer.get_word_embedding_dimension(),
        pooling_mode="mean",
    )

    return SentenceTransformer(modules=[transformer, pooling], device=DEVICE)


# 4. Metrics summary helper
def print_metrics_summary(
    log_history: list,
    trial_number: int | None = None,
    is_final: bool = False,
) -> None:
    """
    Print a detailed summary of training and evaluation metrics for a trial.

    Displays:
        - Training loss trajectory (start, end, min, max, trend)
        - Per-epoch evaluation table with all logged metrics
        - Best eval checkpoint (by ``eval_loss``)
        - IR / triplet metrics from the last checkpoint

    Args:
        log_history:   ``trainer.state.log_history`` list produced by
                       ``SentenceTransformerTrainer``.
        trial_number:  Optuna trial index; ``None`` for the final run.
        is_final:      Use a heavier separator for the final summary.
    """
    label = f"[Trial {trial_number}]" if trial_number is not None else "[Final]"
    sep   = "=" * 70 if is_final else "─" * 60

    print(f"\n{sep}")
    print(f"{label} {'Full metrics summary' if is_final else 'Trial metrics'}")
    print(sep)

    train_losses = [
        (e["step"], e["loss"])
        for e in log_history
        if "loss" in e and "eval_loss" not in e
    ]
    eval_entries = [e for e in log_history if "eval_loss" in e]

    # ── Training loss trajectory ──────────────────────────────────────────────
    if train_losses:
        steps, vals = zip(*train_losses)
        trend = "↓ improving" if vals[-1] < vals[0] else "↑ worsening"
        print(f"\n  Train Loss")
        print(f"    Start  (step {steps[0]:>6}): {vals[0]:.4f}")
        print(f"    End    (step {steps[-1]:>6}): {vals[-1]:.4f}")
        print(f"    Min               : {min(vals):.4f}")
        print(f"    Max               : {max(vals):.4f}")
        print(f"    Trend             : {trend}")

    # ── Per-checkpoint evaluation table ──────────────────────────────────────
    if eval_entries:
        print(f"\n  Evaluation checkpoints")
        skip_keys = {"step", "epoch", "eval_runtime",
                     "eval_samples_per_second", "eval_steps_per_second"}
        all_metric_keys = sorted(
            {k for e in eval_entries for k in e if k not in skip_keys}
        )

        header = f"  {'Step':>6}  {'Epoch':>6}  " + "  ".join(
            f"{k[:30]:>30}" for k in all_metric_keys
        )
        print(header)
        print("  " + "─" * (len(header) - 2))

        for e in eval_entries:
            row  = f"  {int(e.get('step', 0)):>6}  {e.get('epoch', 0):>6.2f}  "
            row += "  ".join(
                f"{e.get(k, float('nan')):>30.4f}" for k in all_metric_keys
            )
            print(row)

        # ── Best checkpoint by eval_loss ──────────────────────────────────────
        if "eval_loss" in all_metric_keys:
            best = min(eval_entries, key=lambda e: e.get("eval_loss", float("inf")))
            print(
                f"\n  ★ Best eval_loss: {best['eval_loss']:.4f}  "
                f"(step={int(best.get('step', 0))}, epoch={best.get('epoch', 0):.2f})"
            )

        # ── IR / triplet metrics at last checkpoint ───────────────────────────
        last    = eval_entries[-1]
        ir_keys = [
            k for k in last
            if any(m in k for m in ("ndcg", "mrr", "accuracy", "precision",
                                    "recall", "map", "triplet"))
        ]
        if ir_keys:
            print("\n  IR / Triplet metrics (last checkpoint):")
            for key in sorted(ir_keys):
                print(f"    {key:<50}: {last[key]:.4f}")

    print(sep + "\n")

# 5. Optuna pruning callback
class OptunaPruningCallback(TrainerCallback):
    """
    HuggingFace ``TrainerCallback`` that integrates Optuna pruning into the
    ``SentenceTransformerTrainer`` evaluation loop.

    After each evaluation epoch the callback reports the current NDCG@10
    score (falling back to MRR@10 if unavailable) to Optuna and raises
    ``TrialPruned`` when the pruner decides the trial is unpromising.
    """

    def __init__(self, trial: optuna.Trial) -> None:
        self.trial = trial

    def on_evaluate(self, args, state, control, metrics=None, **kwargs) -> None:
        if not metrics:
            return

        ndcg_key = next((k for k in metrics if "ndcg" in k.lower() and "10" in k), None)
        mrr_key  = next((k for k in metrics if "mrr"  in k.lower() and "10" in k), None)
        target_key = ndcg_key or mrr_key

        if target_key:
            score = float(metrics[target_key])
            self.trial.report(score, state.global_step)
            if self.trial.should_prune():
                print(f"\n[!] Trial {self.trial.number} pruned at step {state.global_step}.")
                raise optuna.exceptions.TrialPruned()


# 5. Optuna objective
def objective(trial: optuna.Trial) -> float:
    """
    Optuna objective function for one hyperparameter trial.

    Samples the following hyperparameters:
        - ``learning_rate``   — log-uniform within ``LEARNING_RATE_RANGE``
        - ``batch_size``      — fixed to the CLI value (categorical)
        - ``mini_batch_size`` — categorical from ``MINI_BATCH_SIZE_OPTIONS``
        - ``warmup_ratio``    — uniform within ``WARMUP_RATIO_RANGE``
        - ``weight_decay``    — uniform within ``WEIGHT_DECAY_RANGE``

    The optimisation target is **eval loss** (minimise).  Returns ``+inf``
    when training fails so that Optuna deprioritises the configuration.

    Args:
        trial: An Optuna ``Trial`` object used to sample hyperparameters.

    Returns:
        The final eval loss for this trial (lower is better).
    """
    # ── Sample hyperparameters ────────────────────────────────────────────────
    learning_rate   = trial.suggest_float("learning_rate",   *LEARNING_RATE_RANGE, log=True)
    batch_size      = trial.suggest_categorical("batch_size",      [ARGS.batch_size])
    mini_batch_size = trial.suggest_categorical("mini_batch_size", MINI_BATCH_SIZE_OPTIONS)
    warmup_ratio    = trial.suggest_float("warmup_ratio",    *WARMUP_RATIO_RANGE)
    weight_decay    = trial.suggest_float("weight_decay",    *WEIGHT_DECAY_RANGE)

    trial_output_dir = os.path.join(output_base_dir, f"trial_{trial.number}")
    os.makedirs(trial_output_dir, exist_ok=True)

    print(
        f"\n{'=' * 60}\n"
        f"[Trial {trial.number}]\n"
        f"  learning_rate   : {learning_rate:.2e}\n"
        f"  batch_size      : {batch_size}\n"
        f"  mini_batch_size : {mini_batch_size}\n"
        f"  warmup_ratio    : {warmup_ratio:.3f}\n"
        f"  weight_decay    : {weight_decay:.4f}\n"
        f"{'=' * 60}"
    )

    # ── Model + loss + training arguments ─────────────────────────────────────
    model = build_model()

    # CachedMNRL: memory-efficient contrastive loss; mini_batch_size controls
    # the sub-batch used for gradient caching, enabling larger effective batches
    train_loss = losses.CachedMultipleNegativesRankingLoss(
        model, mini_batch_size=mini_batch_size
    )

    training_args = SentenceTransformerTrainingArguments(
        output_dir=trial_output_dir,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        fp16=False,
        bf16=False,
        gradient_checkpointing=True,
        ddp_find_unused_parameters=False,
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        # Drop the last incomplete batch to avoid shape mismatches with MNRL
        dataloader_drop_last=True,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=LOGGING_STEPS,
        push_to_hub=False,
        report_to="none",
        load_best_model_at_end=False,
    )

    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        loss=train_loss,
        evaluator=evaluator,  # Rich IR + triplet evaluation
        callbacks=[OptunaPruningCallback(trial)],
    )

    # ── Training ──────────────────────────────────────────────────────────────
    try:
        trainer.train()
    except optuna.exceptions.TrialPruned as e:
        del model, trainer, train_loss
        torch.cuda.empty_cache()
        raise e
    except RuntimeError as exc:
        print(f"[Trial {trial.number}] Runtime error: {exc}")
        del model, trainer, train_loss
        torch.cuda.empty_cache()
        return float("-inf")

    log_history = trainer.state.log_history
    print_metrics_summary(log_history, trial_number=trial.number)

    # ── Extract objective metric (NDCG@10, fallback MRR@10) ──────────────────
    eval_entries = [e for e in log_history if any("ir" in k for k in e)]
    last_eval    = eval_entries[-1] if eval_entries else {}

    ndcg_key = next((k for k in last_eval if "ndcg" in k.lower() and "10" in k), None)
    mrr_key  = next((k for k in last_eval if "mrr"  in k.lower() and "10" in k), None)

    if ndcg_key:
        score = float(last_eval[ndcg_key])
        print(f"[Trial {trial.number}] Objective → {ndcg_key}: {score:.4f}")
    elif mrr_key:
        score = float(last_eval[mrr_key])
        print(f"[Trial {trial.number}] Objective → {mrr_key} (MRR fallback): {score:.4f}")
    else:
        print(f"[Trial {trial.number}] WARNING: no NDCG/MRR metric found → -inf")
        score = float("-inf")

    # ── Clean up GPU memory ───────────────────────────────────────────────────
    del model, trainer, train_loss
    torch.cuda.empty_cache()

    return score


# 6. Entry point
if __name__ == "__main__":
    os.makedirs(output_base_dir, exist_ok=True)

    storage_url = OPTUNA_DB_TEMPLATE.format(
        output_base_dir=output_base_dir, type_hn=type_hn
    )
    study_name = OPTUNA_STUDY_NAME_TEMPLATE.format(type_hn=type_hn)

    # Delete any existing study to start fresh
    try:
        optuna.delete_study(study_name=study_name, storage=storage_url)
        print(f"Existing study '{study_name}' deleted. Starting from scratch.")
    except KeyError:
        print("No existing study found. Creating a new one.")

    sampler = optuna.samplers.TPESampler(seed=RANDOM_SEED)
    pruner  = optuna.pruners.MedianPruner(
        n_startup_trials=OPTUNA_STARTUP_TRIALS,
        n_warmup_steps=0,
    )

    study = optuna.create_study(
        direction="maximize",   # Optimise toward lower eval loss
        sampler=sampler,
        pruner=pruner,
        study_name=study_name,
        storage=storage_url,
        load_if_exists=True,
    )

    print(f"Launching search: {N_TRIALS} trials on GPU {ARGS.gpu} …")
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=True)

    # ── Final report ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SEARCH COMPLETE — OPTUNA SUMMARY")
    print("=" * 70)
    print(
        f"Best eval loss: {study.best_value:.4f}  "
        f"(Trial #{study.best_trial.number})"
    )
    print("\nBest hyperparameters:")
    for key, value in study.best_params.items():
        print(f"  {key:<20}: {value}")

    trials_df = study.trials_dataframe()
    desired_cols = [
        "number",
        "value",
        "params_learning_rate",
        "params_batch_size",
        "params_mini_batch_size",
        "params_warmup_ratio",
        "params_weight_decay",
    ]
    available_cols = [c for c in desired_cols if c in trials_df.columns]
    print("\nTop-5 trials by eval loss:")
    print(
        trials_df[available_cols]
        .sort_values("value")
        .head(5)
        .to_string(index=False)
    )