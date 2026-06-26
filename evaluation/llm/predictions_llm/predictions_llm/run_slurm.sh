#!/bin/bash
# ============================================================
# Template SLURM generico para lanzar inferencia LLM
# ============================================================
# Edita las variables de entorno o pasalas al script antes de ejecutar.
#
# Ejemplo de uso:
#   MODEL_PATH="/ruta/al/modelo" \
#   MODEL_NAME="mi-modelo" \
#   INPUT_FILE="dataset.csv" \
#   PROMPT_FILE="prompt.txt" \
#   OUTPUT_CSV="resultados.csv" \
#   BACKEND="transformers" \
#   GPUS=1 \
#   bash run_slurm.sh
#
# O edita directamente las variables mas abajo.
# ============================================================

# --- Configuracion editable ---
MODEL_PATH="${MODEL_PATH:-/ruta/al/modelo}"
MODEL_NAME="${MODEL_NAME:-mi-modelo}"
INPUT_FILE="${INPUT_FILE:-dataset.csv}"
PROMPT_FILE="${PROMPT_FILE:-prompt.txt}"
OUTPUT_CSV="${OUTPUT_CSV:-resultados.csv}"
BACKEND="${BACKEND:-transformers}"
GPUS="${GPUS:-1}"
CONDA_ENV="${CONDA_ENV:-mi_entorno}"
CONDA_SH="${CONDA_SH:-/ruta/a/conda.sh}"
LOG_DIR="${LOG_DIR:-./logs}"
# ------------------------------

mkdir -p "$LOG_DIR"

sbatch \
    --job-name="eval_${MODEL_NAME}" \
    --partition=normal \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=8 \
    --mem=60G \
    --gres="gpu:${GPUS}" \
    --output="${LOG_DIR}/eval_${MODEL_NAME}.out" \
    --error="${LOG_DIR}/eval_${MODEL_NAME}.err" \
    --wrap="
        source ${CONDA_SH}
        conda activate ${CONDA_ENV}

        export VLLM_WORKER_MULTIPROC_METHOD=spawn

        echo '======================================================'
        echo '  Evaluacion LLM  --  ${MODEL_NAME}'
        echo '======================================================'
        echo 'Job ID: \$SLURM_JOB_ID'
        echo 'Nodo:   \$SLURM_NODELIST'
        echo 'GPU:    \$CUDA_VISIBLE_DEVICES'
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
        echo ''

        python -u run_inference.py \
            --backend '${BACKEND}' \
            --model_path '${MODEL_PATH}' \
            --input_file '${INPUT_FILE}' \
            --prompt_file '${PROMPT_FILE}' \
            --output_csv '${OUTPUT_CSV}'

        echo '======================================================'
        echo 'Job finalizado: \$SLURM_JOB_ID'
        echo '======================================================'
    "
