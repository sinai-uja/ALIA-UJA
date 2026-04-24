"""
Sequential Cross-Encoder Training Script
=========================================
Trains a CrossEncoder model in multiple phases using progressively harder
negative samples. Each phase loads the model saved by the previous one,
enabling curriculum learning across difficulty levels.
"""
import torch.distributed as dist
import gc
import json
import os
from collections import defaultdict
import torch
import wandb
import random
from datasets import Dataset
from sentence_transformers.cross_encoder import (
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
        losses,
        CrossEncoder,
    )
from config_train import (
    BASE_OUTPUT_DIR,
    BATCH_SIZE,
    DATASETS_DIR_DOMAIN,
    DATASETS_DIR_GENERALS,
    LEARNING_RATE,
    MAX_SEQ_LENGTH,
    MODEL_PATH,
    WARMUP_RATIO,
    WEIGHT_DECAY,
    WANDB_OFFLINE,
    WANDB_PROJECT,
    GRADIENT_ACCUMULATION_STEPS,
    LOGGING_STEPS
)

# Environment setup
# Disable Weights & Biases online sync (run in offline mode)
os.environ["WANDB_MODE"] = "offline"

# Allow PyTorch to use expandable CUDA memory segments to reduce fragmentation
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# Determine the local GPU rank for distributed training
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
    "cross_general_random",
    "cross_facil_top",
    "cross_medio_top",
    "cross_dificil_top",
    "cross_general_top",
]

# ---------------------------------------------------------------------------
# Training phases configuration
# Each entry is (dataset_path, num_epochs).
# Order follows a curriculum: easy → medium → hard, then random → top negatives.
# ---------------------------------------------------------------------------
dataset_configs = [
    (f"{DATASETS_DIR_GENERALS}hard_negatives_generales_random.jsonl",1, None), # general, random negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_facil_top.jsonl",     1, 100000),  # easy,   top negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_medio_top.jsonl",     1, 100000),  # medium, top negatives
    (f"{DATASETS_DIR_DOMAIN}hard_negatives_dataset_dificil_top.jsonl",   1, 100000),  # hard,   top negatives
    (f"{DATASETS_DIR_GENERALS}hard_negatives_generales_top.jsonl",1, None), # general, top negatives
]

def load_reranker_sft(path: str, max_samples: int | None = None, seed: int = 42) -> Dataset:
    import random
    rng = random.Random(seed)

    queries, documents, labels = [], [], []
    reservoir_size = max_samples  # None = sin límite

    count = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                item = json.loads(line)
                query = item["messages"][0]["content"]

                rows = []
                for pos in item["positive_messages"]:
                    rows.append((query, pos[0]["content"], 1.0))
                if item.get("negative_messages"):
                    for neg_group in item["negative_messages"]:
                        rows.append((query, neg_group[0]["content"], 0.0))

                for row in rows:
                    if reservoir_size is None or count < reservoir_size:
                        queries.append(row[0])
                        documents.append(row[1])
                        labels.append(row[2])
                    else:
                        # Reservoir sampling de Vitter
                        j = rng.randint(0, count)
                        if j < reservoir_size:
                            queries[j]   = row[0]
                            documents[j] = row[1]
                            labels[j]    = row[2]
                    count += 1

            except (KeyError, IndexError):
                continue

    total_read = count
    dataset = Dataset.from_dict({"query": queries, "document": documents, "label": labels})

    if max_samples is not None and max_samples < total_read:
        print(f"  ↳ Subsampled to {max_samples} / {total_read} samples (reservoir sampling)")

    return dataset

# Sequential training loop
total_phases = len(dataset_configs)
current_model_path = MODEL_PATH

for phase, (dataset_path, epochs, max_samples)  in enumerate(dataset_configs, start=1):
    final_phase_path = os.path.join(BASE_OUTPUT_DIR, f"checkpoint_{phase}", "final_model")
    
    # Resume support: skip phases that already produced a saved model
    if os.path.exists(final_phase_path):
        print(f"⏭️  Phase {phase} already completed, skipping...")
        current_model_path = final_phase_path
        continue

    print(f"\n{'='*60}")
    print(f"PHASE {phase}/{total_phases}  |  Epochs: {epochs}")
    print(f"{'='*60}")

    output_dir = os.path.join(BASE_OUTPUT_DIR, f"checkpoint_{phase}")
    os.makedirs(output_dir, exist_ok=True)
    #-------------a
    label = PHASE_LABELS[phase- 1]
    print("--------------label",label)
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
                "gradient_accumulation_steps": GRADIENT_ACCUMULATION_STEPS,
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
    #-------------

    # --- Load model from the previous phase (or the base model on phase 1) ---
    print(f"Loading model from: {current_model_path}")
    model = CrossEncoder(
        current_model_path,
        num_labels=1,           # Regression head: outputs a single relevance score
        max_length=MAX_SEQ_LENGTH,
        device=str(device),
        trust_remote_code=True,
    )

    # Enable gradient checkpointing to trade compute for lower VRAM usage
    model.model.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False}
    )

    # --- Load dataset for this phase ---
    print(f"Loading dataset: {dataset_path}")
    train_dataset = load_reranker_sft(dataset_path, max_samples=max_samples)
    print(f"Samples loaded: {len(train_dataset)}")

    # ── Training arguments ────────────────────────────────────────────────
    # run_name matches the wandb.init name so the Trainer doesn't create
    # a second run; WANDB_RUN_ID forces the Trainer to log into our run.
    os.environ["WANDB_RUN_ID"] = run_id or ""

    training_args = CrossEncoderTrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        warmup_ratio=WARMUP_RATIO,
        weight_decay=WEIGHT_DECAY,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
        fp16=False,
        bf16=True,                              # Use bfloat16 mixed precision
        gradient_checkpointing=True,
        ddp_find_unused_parameters=False,
        save_strategy="epoch",
        logging_steps=LOGGING_STEPS,
        push_to_hub=False,
        report_to="wandb",
        run_name=f"phase{phase:02d}_{label}",
    )

    # CachedMNRL: efficient in-batch negative ranking loss with gradient caching
    loss = losses.BinaryCrossEntropyLoss(model=model)
    trainer = CrossEncoderTrainer(
        model=model,
        loss=loss,
        args=training_args,
        train_dataset=train_dataset,
    )

    print(f"Starting training — phase {phase} on {torch.cuda.device_count()} GPU(s)...")

    try:
        trainer.train()
    except RuntimeError as e:
        print(f"\nERROR in phase {phase}: {e}")
        raise

    # Save the fine-tuned model so the next phase can load it
    if not dist.is_initialized() or dist.get_rank() == 0:
        os.makedirs(final_phase_path, exist_ok=True)
        model.model.save_pretrained(final_phase_path)      # pesos + config
        model.tokenizer.save_pretrained(final_phase_path)  # tokenizer files
        print(f"✓ Phase {phase} checkpoint saved to: {final_phase_path}")

    if dist.is_initialized():
        dist.barrier()  # otros ranks esperan antes de continuar
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

# Summary
print(f"\n{'='*60}")
print("Sequential training complete.")
print(f"Checkpoints saved under: {BASE_OUTPUT_DIR}/checkpoint_{{1..{total_phases}}}/final_model")
print(f"{'='*60}")