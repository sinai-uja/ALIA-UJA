"""
Sequential Sentence Transformer Training Script
=================================================
Trains a SentenceTransformer bi-encoder in multiple phases using progressively
harder negative samples (curriculum learning).

Phase 1 builds the model from the raw transformer backbone (adding a mean-pooling
head). Subsequent phases reload the saved SentenceTransformer checkpoint directly.
Each phase saves its final model so the next one can continue from it, and any
already-completed phase is automatically skipped on resume.
"""

import gc
import json
import os
import json, pathlib
import wandb
import torch
from datasets import Dataset
from sentence_transformers import (
    SentenceTransformer,
    SentenceTransformerTrainer,
    SentenceTransformerTrainingArguments,
    losses,
    models,
)
from sentence_transformers.training_args import BatchSamplers
from config_train import (
    BASE_OUTPUT_DIR,
    BATCH_SIZE,
    CACHE_MINI_BATCH_SIZE,
    DATASETS_DIR_GENERALS,
    DATASETS_DIR_DOMAIN,
    LEARNING_RATE,
    LOGGING_STEPS,
    MAX_SEQ_LENGTH,
    MODEL_PATH,
    WANDB_OFFLINE,
    WARMUP_RATIO,
    WEIGHT_DECAY,
    WANDB_PROJECT
)

# Environment setup

# Run Weights & Biases in offline mode (no network upload during training)
os.environ["WANDB_MODE"] = "offline"

# Allow PyTorch to use expandable CUDA memory segments to reduce fragmentation
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# Determine local GPU rank for distributed training
local_rank = int(os.environ.get("LOCAL_RANK", 0))
torch.cuda.set_device(local_rank)
device = torch.device(f"cuda:{local_rank}")

# ---------------------------------------------------------------------------
# Training phases configuration
# Each entry is (dataset_path, num_epochs).
# Order follows a curriculum: easy → medium → hard, random → top negatives.
# ---------------------------------------------------------------------------

# ── Curriculum phases ─────────────────────────────────────────────────────────
PHASE_LABELS = [
    "general_random",
    "facil_random",
    "medio_random",
    "dificil_random",
    "general_top",
    "facil_top",
    "medio_top",
    "dificil_top",
]

dataset_configs = [
    (f"{DATASETS_DIR_GENERALS}hard_negatives_generales_random.jsonl",     2, None),  # general, random negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_facil_random.jsonl",   2, 100000),  # easy,   random negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_medio_random.jsonl",   2, 100000),  # medium, random negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_dificil_random.jsonl", 2, 100000),  # hard,   random negatives
    (f"{DATASETS_DIR_GENERALS}hard_negatives_generales_top.jsonl",        1, None),  # general,top negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_facil_top.jsonl",      1, 100000),  # easy,   top negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_medio_top.jsonl",      1, 100000),  # medium, top negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_dificil_top.jsonl",    1, 100000),  # hard,   top negatives
]
def fix_tokenizer_config(model_dir: str) -> None:
    """Remove stale absolute vocab_file paths that break cross-machine loading."""
    cfg_path = pathlib.Path(model_dir) / "tokenizer_config.json"
    if not cfg_path.exists():
        return
    cfg = json.loads(cfg_path.read_text())
    vocab_file = cfg.get("vocab_file", "")
    if vocab_file and not pathlib.Path(vocab_file).exists():
        cfg["vocab_file"] = ""
        cfg_path.write_text(json.dumps(cfg, indent=2))
        print(f"  ↳ Patched stale vocab_file in {cfg_path}")
        
# Dataset loading
def load_triplets(path: str, max_samples: int | None = None, seed: int = 42) -> Dataset:
    queries, positives, negatives = [], [], []

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                item = json.loads(line)
                query    = item["messages"][0]["content"]
                positive = item["positive_messages"][0][0]["content"]
                if item.get("negative_messages") and item["negative_messages"][0]:
                    negative = item["negative_messages"][0][0]["content"]
                    queries.append(query)
                    positives.append(positive)
                    negatives.append(negative)
            except (KeyError, IndexError):
                continue

    dataset = Dataset.from_dict(
        {"query": queries, "positive": positives, "negative": negatives}
    )

    if max_samples is not None and max_samples < len(dataset):
        dataset = dataset.shuffle(seed=seed).select(range(max_samples))
        print(f"  ↳ Subsampled to {max_samples} / {len(queries)} samples")

    return dataset


# 4. Función de construcción del modelo

# Model construction
# ---------------------------------------------------------------------------
def build_model(model_path: str, device: torch.device) -> SentenceTransformer:
    """
    Build a SentenceTransformer from a raw transformer checkpoint.

    Used only in phase 1, when the base model has no pooling head yet.
    Attaches a mean-pooling layer on top of the transformer encoder and
    enables gradient checkpointing to reduce VRAM usage.

    Args:
        model_path: Path to the pretrained transformer checkpoint.
        device:     CUDA device to load the model onto.

    Returns:
        A SentenceTransformer with [Transformer → MeanPooling] architecture.
    """
    # Transformer encoder (tokenizer + backbone)
    word_embedding_model = models.Transformer(
        model_path,
        max_seq_length=MAX_SEQ_LENGTH,
        model_args={"trust_remote_code": True},
    )

    # Gradient checkpointing trades recomputation for lower VRAM
    word_embedding_model.auto_model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )

    # Mean pooling over token embeddings to produce a fixed-size sentence vector
    pooling_model = models.Pooling(
        word_embedding_model.get_word_embedding_dimension(),
        pooling_mode="mean",
    )

    return SentenceTransformer(
        modules=[word_embedding_model, pooling_model],
        device=str(device),
    )

# Sequential training loop
total_phases = len(dataset_configs)
current_model_path = MODEL_PATH

for phase, (dataset_path, epochs, max_samples) in enumerate(dataset_configs, start=1):

    final_phase_path = os.path.join(BASE_OUTPUT_DIR, f"checkpoint_{phase}", "final_model")

    # Resume support: skip phases that already produced a saved model
    if os.path.exists(final_phase_path):
        print(f"⏭️  Phase {phase} already completed, skipping...")
        fix_tokenizer_config(final_phase_path) 
        current_model_path = final_phase_path
        continue

    print(f"\n{'='*60}")
    print(f"  PHASE {phase}/{total_phases}  |  Epochs: {epochs}")
    print(f"{'='*60}")

    output_dir = os.path.join(BASE_OUTPUT_DIR, f"checkpoint_{phase}")
    os.makedirs(output_dir, exist_ok=True)
    label = PHASE_LABELS[phase- 1]
    if local_rank == 0:
        run = wandb.init(
            project=WANDB_PROJECT,
            name=f"phase{phase:02d}_{label}",   # e.g. "phase01_facil_random"
            group="curriculum",                  # groups all phases in one view
            tags=[f"phase_{phase}", label],
            config={
                "phase":         phase,
                "label":         label,
                "epochs":        epochs,
                "batch_size":    BATCH_SIZE,
                "cache_mini_batch_size": CACHE_MINI_BATCH_SIZE,
                "learning_rate": LEARNING_RATE,
                "warmup_ratio":  WARMUP_RATIO,
                "weight_decay":  WEIGHT_DECAY,
                "max_seq_length": MAX_SEQ_LENGTH,
                "dataset":       dataset_path,
            },
            reinit=True,
        )
        run_id = run.id
    else:
        run_id = None

    # --- Load model ---
    # Phase 1: build from raw transformer backbone (no pooling head yet).
    # Later phases: load the full SentenceTransformer saved by the previous phase.
    print(f"Loading model from: {current_model_path}")
    if phase == 1:
        model = build_model(current_model_path, device)
    else:
        model = SentenceTransformer(current_model_path, device=str(device))
        # Re-enable gradient checkpointing (not persisted in the saved checkpoint)
        model[0].auto_model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )

    # --- Load dataset for this phase ---
    print(f"Loading dataset: {dataset_path}")
    train_dataset = load_triplets(dataset_path, max_samples=max_samples)
    print(f"Samples loaded: {len(train_dataset)}")

    # CachedMNRL: in-batch negative ranking loss with gradient caching.
    # mini_batch_size controls the cache chunk size to fit large batches in VRAM.
    train_loss = losses.CachedMultipleNegativesRankingLoss(
        model,
        mini_batch_size=CACHE_MINI_BATCH_SIZE,
    )

    # ── Training arguments ────────────────────────────────────────────────
    # run_name matches the wandb.init name so the Trainer doesn't create
    # a second run; WANDB_RUN_ID forces the Trainer to log into our run.
    os.environ["WANDB_RUN_ID"] = run_id or ""

    training_args = SentenceTransformerTrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        weight_decay=WEIGHT_DECAY,
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        fp16=False,
        bf16=True,                      # Use bfloat16 mixed precision
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        ddp_find_unused_parameters=False,
        save_strategy="epoch",
        logging_steps=LOGGING_STEPS,
        push_to_hub=False,
        report_to="wandb",
        run_name=f"phase{phase:02d}_{label}",
    )

    trainer = SentenceTransformerTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        loss=train_loss,
    )

    print(f"Starting training — phase {phase} on {torch.cuda.device_count()} GPU(s)...")

    try:
        trainer.train()
    except RuntimeError as e:
        print(f"\nERROR in phase {phase}: {e}")
        raise

    # Save the fine-tuned model so the next phase can load it
    model.save_pretrained(final_phase_path)
    fix_tokenizer_config(final_phase_path)
    print(f"✓ Phase {phase} checkpoint saved to: {final_phase_path}")

    if local_rank == 0:
        wandb.finish()
        
    # --- Free GPU memory before loading the next phase ---
    del model
    del trainer
    del train_dataset
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    gc.collect()
    print(f"🧹 Memory released after phase {phase}")

    current_model_path = final_phase_path

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*60}")
print("Sequential training complete.")
print(f"Checkpoints saved under: {BASE_OUTPUT_DIR}/checkpoint_{{1..{total_phases}}}/final_model")
print(f"{'='*60}")