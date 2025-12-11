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