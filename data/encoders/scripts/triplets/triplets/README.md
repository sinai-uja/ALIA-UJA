## Folder structure

- `api_generation/`: Code for API-based generation.
   - `api_generation/multi/`: Generators and utilities for multi-query generation (contains `config.yaml.example`, `generators.py`, `main.py`, `models.py`, `process_folder.py`, `utils.py`).
   - `api_generation/single/`: Generators and utilities for single-query generation (contains `config.yaml.example`, `generators.py`, `main.py`, `models.py`, `process_folder.py`, `utils.py`).
- `local_generation/`: Scripts and configuration for local generation (`config.yaml.example`, `generators.py`, `main.py`, `models.py`, `utils.py`).
- `prompts_biomedical/`: Prompts tailored for the biomedical domain.
- `prompts_legal/`: Prompts tailored for the legal domain.

## Configuration

1. Copy `config.yaml.example` to `config.yaml`
2. Update the following required fields:
   - `model`: Path to your model or HuggingFace model ID
   - `dataset_path`: Path to your input Parquet file
   - `output_dir`: Where to save generated files
3. Adjust generation parameters based on your hardware:
   - `tensor_parallel_size`: Set to number of available GPUs
   - `gpu_memory_utilization`: Lower if you encounter OOM errors
   - `batch_size`: Lower for less memory usage, higher for speed

## Input Dataset Format

Your Parquet file must contain these columns:
- `id_chunk`: Unique identifier for each text chunk
- `id_document`: Document identifier
- `passage`: The text passage to generate questions from
- `character`: Character/persona perspective for queries
- `source_id`: Source identifier (e.g., document name)