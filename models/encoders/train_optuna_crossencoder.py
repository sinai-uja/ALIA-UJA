"""
CrossEncoder Hyperparameter Search with Optuna
===============================================
This script performs an automated hyperparameter search for fine-tuning a
CrossEncoder reranking model using the Optuna framework.

Pipeline overview:
    1. Load triplet dataset  (query, positive, negative)
    2. Build a CrossEncoderRerankingEvaluator from the eval split
    3. For each Optuna trial, train a CrossEncoder with CachedMNRL loss
    4. Optimise toward NDCG@K (falls back to MRR@K if unavailable)
    5. Report the best hyperparameters at the end of the search

Dependencies:
    torch, optuna, datasets, sentence-transformers

Configuration is imported from ``config_optuna.py``.  

Usage:
    bash alia/models/encoders/launchers/train/launcher_optuna_parent.sh --values 128, 256, 512
"""

# Library imports
import os, sys
import gc
try:
    import json
    import random
    import torch
    import optuna
    from datasets import Dataset
    from collections import defaultdict
    from sentence_transformers.cross_encoder import (
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
        losses,
        CrossEncoder,
    )
    from sentence_transformers.cross_encoder.evaluation import (
        CrossEncoderRerankingEvaluator,
    )
    from transformers import TrainerCallback
    import optuna.exceptions

except ImportError as e:
    print(f"Error importing modules: {e}")
    raise e


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
    WARMUP_RATIO_RANGE,
    WEIGHT_DECAY_RANGE,
    OPTUNA_STARTUP_TRIALS,
    OPTUNA_STUDY_NAME_TEMPLATE,
    OPTUNA_DB_TEMPLATE,
    RUN_NAME_TEMPLATE,
    LOGGING_STEPS,
    WANDB_OFFLINE,
    PYTORCH_CUDA_ALLOC_CONF,
    EVALUATION_K_CROSSENCODER,
    GRADIENT_ACCUMULATION_STEPS_OPTIONS,
)

sys.path.append(os.path.realpath(ALIA_UTILS_PATH))
from utils.utils_alia import RichArgumentParser

print("✓ All libraries imported successfully.")

# CLI arguments
def get_args():
    parser = RichArgumentParser(description="Optuna CrossEncoder hyperparameter search")
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--gpu", type=int, default=0)
    args = parser.parse_args()
    return args

ARGS = get_args()

# Environment setup
os.environ["WANDB_MODE"] = "offline" if WANDB_OFFLINE else "online"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = PYTORCH_CUDA_ALLOC_CONF
os.environ["CUDA_VISIBLE_DEVICES"] = str(ARGS.gpu)

DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
print(f"→ Using device: {DEVICE}")

output_base_dir = OUTPUT_BASE_DIR_TEMPLATE.format(batch_size=ARGS.batch_size)
type_hn = "random" if "random" in DATASET_OPTUNA_PATH else "top"
run_name = RUN_NAME_TEMPLATE.format(type_hn=type_hn)

def load_reranker_sft(path: str):
    """Devuelve grupos por query, no pares aplanados."""
    query_groups = defaultdict(lambda: {"positives": [], "negatives": []})
    
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            item = json.loads(line)
            query = item["messages"][0]["content"]
            query_groups[query]["positives"].append(
                item["positive_messages"][0][0]["content"]
            )
            if item.get("negative_messages"):
                for neg_group in item["negative_messages"]:
                    query_groups[query]["negatives"].append(
                        neg_group[0]["content"]
                    )
    return query_groups


def split_and_flatten(query_groups: dict, eval_ratio: float, seed: int):
    """Split por query, luego aplana a pares."""
    queries = list(query_groups.keys())
    
    import random
    random.seed(seed)
    random.shuffle(queries)
    
    n_eval = max(1, int(len(queries) * eval_ratio))
    eval_queries = set(queries[:n_eval])
    train_queries = set(queries[n_eval:])
    
    def flatten(query_set):
        texts1, texts2, labels = [], [], []
        for q in query_set:
            group = query_groups[q]
            for pos in group["positives"]:
                texts1.append(q)
                texts2.append(pos)
                labels.append(1.0)
            for neg in group["negatives"]:
                texts1.append(q)
                texts2.append(neg)
                labels.append(0.0)
        return Dataset.from_dict({"sentence1": texts1, "sentence2": texts2, "label": labels})
    
    return flatten(train_queries), flatten(eval_queries)


# Uso
print("Loading dataset …")
query_groups = load_reranker_sft(DATASET_OPTUNA_PATH)

# Subsample por queries, no por pares
all_queries = list(query_groups.keys())
random.seed(RANDOM_SEED)
random.shuffle(all_queries)
query_groups = {q: query_groups[q] for q in all_queries[:TRAIN_SIZE_OPTUNA]}

train_dataset, eval_dataset = split_and_flatten(
    query_groups, eval_ratio=EVAL_SPLIT_RATIO, seed=RANDOM_SEED
)
print(f"  → Train: {len(train_dataset):,} | Eval: {len(eval_dataset):,}")

# 2. Evaluator construction

def build_evaluator(eval_ds: Dataset, name_prefix: str = "") -> CrossEncoderRerankingEvaluator:
    # Agrupamos por sentence1 (la query)
    query_map = defaultdict(lambda: {"positive": [], "negative": []})

    for i in range(len(eval_ds)):
        query = eval_ds[i]["sentence1"]
        doc = eval_ds[i]["sentence2"]
        label = eval_ds[i]["label"]
        
        if label == 1.0:
            query_map[query]["positive"].append(doc)
        else:
            query_map[query]["negative"].append(doc)

    samples = []
    for q, docs in query_map.items():
        # Un evaluador de reranking necesita al menos un positivo y un negativo
        if docs["positive"] and docs["negative"]:
            samples.append({
                "query": q,
                "positive": docs["positive"],
                "negative": docs["negative"]
            })

    return CrossEncoderRerankingEvaluator(
        samples=samples,
        name=f"{name_prefix}reranking",
        at_k=EVALUATION_K_CROSSENCODER,
        show_progress_bar=False,
        batch_size=ARGS.batch_size 
    )
print("Building evaluator …")
evaluator = build_evaluator(eval_dataset, name_prefix="eval_")
print("  → Evaluator ready.")

# 3. Model factory
def build_model(model_path: str = MODEL_PATH) -> CrossEncoder:
    """
    Instantiate and configure a ``CrossEncoder`` model for training.

    Gradient checkpointing is enabled to reduce GPU memory usage during
    back-propagation.

    Args:
        model_path: Path or HuggingFace Hub identifier for the base model.

    Returns:
        A ``CrossEncoder`` ready for fine-tuning.
    """
    model = CrossEncoder(
        model_path,
        num_labels=1,
        max_length=MAX_SEQ_LENGTH,
        device=DEVICE,
        trust_remote_code=True,
    )
    model.model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )
    return model

# 4. Metrics summary helper
def print_metrics_summary(log_history: list, trial_number: int | None = None) -> None:
    """
    Print a concise summary of training and evaluation metrics for a trial.

    Args:
        log_history:   ``trainer.state.log_history`` list produced by
                       ``CrossEncoderTrainer``.
        trial_number:  Optuna trial index; ``None`` for the final run.
    """
    label = f"[Trial {trial_number}]" if trial_number is not None else "[Final]"
    sep   = "─" * 60
    print(f"\n{sep}\n{label} Trial metrics\n{sep}")

    # ── Training loss trajectory ──────────────────────────────────────────────
    train_losses = [
        (e["step"], e["loss"])
        for e in log_history
        if "loss" in e and "eval_loss" not in e
    ]
    if train_losses:
        _, vals = zip(*train_losses)
        direction = "↓" if vals[-1] < vals[0] else "↑"
        print(
            f"  Train loss → start: {vals[0]:.4f}  end: {vals[-1]:.4f}  {direction}"
        )

    # ── Evaluation IR metrics ─────────────────────────────────────────────────
    eval_entries = [e for e in log_history if any("reranking" in k for k in e)]
    if eval_entries:
        last = eval_entries[-1]
        ir_keys = [
            k for k in last
            if any(m in k for m in ("mrr", "ndcg", "map", "accuracy", "precision",
                                    "recall", "reranking"))
        ]
        for key in sorted(ir_keys):
            print(f"    {key:<50}: {float(last[key]):.4f}")

    print(sep)


# 5. Optuna 
class OptunaPruningCallback(TrainerCallback):
    """Callback para reportar métricas a Optuna y aplicar pruning."""
    def __init__(self, trial: optuna.Trial):
        self.trial = trial

    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if not metrics:
            return

        # Buscamos la métrica objetivo dinámicamente, igual que haces en tu objective
        ndcg_key = next((k for k in metrics if "ndcg" in k.lower() and "10" in k), None)
        mrr_key = next((k for k in metrics if "mrr" in k.lower() and "10" in k), None)
        
        target_key = ndcg_key or mrr_key
        
        if target_key:
            score = float(metrics[target_key])
            
            # 1. Reportamos el rendimiento actual al trial de Optuna
            self.trial.report(score, state.global_step)

            # 2. Le preguntamos a Optuna si vale la pena continuar
            if self.trial.should_prune():
                print(f"\n[!] Trial {self.trial.number} podado (pruned) en el paso {state.global_step}.")
                raise optuna.exceptions.TrialPruned()

def objective(trial: optuna.Trial) -> float:
    """
    Optuna objective function for one hyperparameter trial.

    Samples the following hyperparameters:
        - ``learning_rate``  — log-uniform within ``LEARNING_RATE_RANGE``
        - ``batch_size``     — fixed to the CLI value (categorical)
        - ``warmup_ratio``   — uniform within ``WARMUP_RATIO_RANGE``
        - ``weight_decay``   — uniform within ``WEIGHT_DECAY_RANGE``

    The primary optimisation metric is **NDCG@K**; if that key is absent from
    the log history, **MRR@K** is used as a fallback.  Returns ``-inf`` when
    training fails or no metric is found.

    Args:
        trial: An Optuna ``Trial`` object used to sample hyperparameters.

    Returns:
        The best evaluation score for this trial (higher is better).
    """
    # ── Sample hyperparameters ────────────────────────────────────────────────
    learning_rate = trial.suggest_float("learning_rate", *LEARNING_RATE_RANGE, log=True)
    batch_size    = trial.suggest_categorical("batch_size", [ARGS.batch_size])
    gradient_accumulation_steps = trial.suggest_categorical("gradient_accumulation_steps", GRADIENT_ACCUMULATION_STEPS_OPTIONS)
    warmup_ratio  = trial.suggest_float("warmup_ratio",  *WARMUP_RATIO_RANGE)
    weight_decay  = trial.suggest_float("weight_decay",  *WEIGHT_DECAY_RANGE)

    trial_output_dir = os.path.join(output_base_dir, f"trial_{trial.number}")
    os.makedirs(trial_output_dir, exist_ok=True)

    print(
        f"\n{'=' * 60}\n"
        f"[Trial {trial.number}]\n"
        f"  learning_rate   : {learning_rate:.2e}\n"
        f"  batch_size      : {batch_size}\n"
        f"  gradient_accumulation_steps : {gradient_accumulation_steps}\n"
        f"  warmup_ratio    : {warmup_ratio:.3f}\n"
        f"  weight_decay    : {weight_decay:.4f}\n"
        f"{'=' * 60}"
    )

    # ── Model + training arguments ────────────────────────────────────────────
    model = build_model()

    training_args = CrossEncoderTrainingArguments(
        output_dir=trial_output_dir,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_ratio=warmup_ratio,
        weight_decay=weight_decay,
        gradient_accumulation_steps=gradient_accumulation_steps,
        # NO_DUPLICATES benefits contrastive losses that use in-batch negatives
        fp16=False,
        bf16=False,
        gradient_checkpointing=True,
        ddp_find_unused_parameters=False,
        eval_strategy="epoch",
        save_strategy="no",
        logging_steps=LOGGING_STEPS,
        push_to_hub=False,
        report_to="none",
        load_best_model_at_end=False,
    )

    loss = losses.BinaryCrossEntropyLoss(model=model)
    pruning_callback = OptunaPruningCallback(trial)
    trainer = CrossEncoderTrainer(
        model=model,
        args=training_args,
        loss=loss,
        train_dataset=train_dataset,
        eval_dataset=None,   # Evaluation is handled by `evaluator`
        evaluator=evaluator,
        callbacks=[pruning_callback]
    )

    # ── Training ──────────────────────────────────────────────────────────────
    try:
        trainer.train()
    except optuna.exceptions.TrialPruned as e:
        # Dejamos que Optuna maneje su propia excepción para registrar el estado "PRUNED"
        del model, trainer
        torch.cuda.empty_cache()
        raise e
    except RuntimeError as exc:
        print(f"[Trial {trial.number}] Runtime error: {exc}")
        del model, trainer
        torch.cuda.empty_cache()
        return float("-inf")

    log_history = trainer.state.log_history
    print_metrics_summary(log_history, trial_number=trial.number)

    # ── Extract objective metric ──────────────────────────────────────────────
    eval_entries = [e for e in log_history if any("reranking" in k for k in e)]
    last_eval    = eval_entries[-1] if eval_entries else {}

    ndcg_key = next(
        (k for k in last_eval if "ndcg" in k.lower() and "10" in k), None
    )
    mrr_key = next(
        (k for k in last_eval if "mrr" in k.lower() and "10" in k), None
    )

    if ndcg_key:
        score = float(last_eval[ndcg_key])
        print(f"[Trial {trial.number}] Objective → {ndcg_key}: {score:.4f}")
    elif mrr_key:
        score = float(last_eval[mrr_key])
        print(f"[Trial {trial.number}] Objective → {mrr_key} (MRR fallback): {score:.4f}")
    else:
        print(f"[Trial {trial.number}] WARNING: no evaluation metric found → -inf")
        score = float("-inf")

    # ── Clean up GPU memory ───────────────────────────────────────────────────
    del model, trainer
    torch.cuda.empty_cache()
    gc.collect()

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
        direction="maximize",
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
        f"Best score (NDCG@{EVALUATION_K_CROSSENCODER}): {study.best_value:.4f}  "
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
        "params_warmup_ratio",
        "params_weight_decay",
    ]
    available_cols = [c for c in desired_cols if c in trials_df.columns]
    print("\nTop-5 trials:")
    print(
        trials_df[available_cols]
        .sort_values("value", ascending=False)
        .head(5)
        .to_string(index=False)
    )