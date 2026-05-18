"""
03_generate_blocks.py
=====================
Generates 60 annotation blocks for the full Prolific study.
Each block = 50 real samples + 5 gold standards (attention checks), shuffled.

INPUT:
    - ../data/corpus_final_decide_madrid.csv  (3,000 samples, semicolon-separated)
    - ../annotation/gold_standard.csv         (10 attention checks, semicolon-separated)

OUTPUT:
    - bloques_60/bloque_01.csv ... bloque_60.csv

USAGE:
    python 03_generate_blocks.py
"""

import pandas as pd
import os

# --- CONFIGURATION ---
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA_FILE = os.path.join(ROOT, "data", "corpus_final_decide_madrid.csv")
GOLD_FILE = os.path.join(ROOT, "annotation", "gold_standard.csv")
BLOCKS_FOLDER = os.path.join(BASE, "bloques_60")
SAMPLES_PER_BLOCK = 50
GOLD_PER_BLOCK = 5
SEED = 42

# --- EXECUTION ---
data = pd.read_csv(DATA_FILE, sep=";")
gold = pd.read_csv(GOLD_FILE, sep=";")

print(f"Samples loaded: {len(data)}")
print(f"Gold standards loaded: {len(gold)}")

assert len(data) == 3000, f"Expected 3000 samples, found {len(data)}"
assert len(gold) >= GOLD_PER_BLOCK, f"Need at least {GOLD_PER_BLOCK} gold standards, found {len(gold)}"

# Shuffle data
data = data.sample(frac=1, random_state=SEED).reset_index(drop=True)

os.makedirs(BLOCKS_FOLDER, exist_ok=True)

num_blocks = len(data) // SAMPLES_PER_BLOCK

for i in range(num_blocks):
    start = i * SAMPLES_PER_BLOCK
    end = start + SAMPLES_PER_BLOCK
    block = data.iloc[start:end].copy()
    block["is_gold"] = False
    block["gold_label"] = ""

    # Gold standard with replacement across blocks (10 gold, 5 per block)
    gold_selection = gold.sample(n=GOLD_PER_BLOCK, random_state=SEED + i).copy()
    gold_selection["is_gold"] = True

    for col in block.columns:
        if col not in gold_selection.columns:
            gold_selection[col] = ""

    final_block = pd.concat([block, gold_selection], ignore_index=True)
    final_block = final_block.sample(frac=1, random_state=SEED + i).reset_index(drop=True)

    name = f"bloque_{i+1:02d}.csv"
    final_block.to_csv(os.path.join(BLOCKS_FOLDER, name), index=False, sep=";")
    print(f"  Created {name}: {len(final_block)} questions ({GOLD_PER_BLOCK} gold)")

print(f"\nTotal: {num_blocks} blocks created in '{BLOCKS_FOLDER}'")
print(f"Samples per block: {SAMPLES_PER_BLOCK} real + {GOLD_PER_BLOCK} gold = {SAMPLES_PER_BLOCK + GOLD_PER_BLOCK}")
print(f"Participants needed: {num_blocks * 3} (3 per block)")
