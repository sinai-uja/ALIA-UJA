#!/usr/bin/env bash

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

usage() {
        cat <<'EOF'
Uso: bash launcher.sh [opciones]

Opciones principales:
    --domain <valor>
    --task <valor>              (retrieval|generation|all|precision)
    --force <true|false>
    --config <ruta>
    --python-bin <comando>

Samples:
    --query-sample <n>
    --context-sample <n>
    --sample-query <n>           (alias de --retrieval-query-sample)
    --sample-context <n>         (alias de --retrieval-context-sample)
    --retrieval-query-sample <n>
    --retrieval-context-sample <n>
    --format-query-sample <n>
    --format-context-sample <n>
    --ragas-query-sample <n>
    --ragas-context-sample <n>

Opcionales de ejecución:
    --top-k <n>
    --batch-size <n>
    --index-name <archivo>
    --metadata-name <archivo>
    --no-normalize
    --help
EOF
}

# ============================================================
# Configuración general
# ============================================================
PYTHON_BIN="${PYTHON_BIN:-python}"
CONFIG_FILE="${CONFIG_FILE:-config.yaml}"

DOMAIN="${DOMAIN:-absanitas}" # legal|justicio|wilfredo|biomedical|cowese|absanitas|heritage
TASK="${TASK:-retrieval}" # retrieval|generation|all|precision
FORCE="${FORCE:-false}" # true|false

# step 1 y step 2 usan un único sample.
QUERY_SAMPLE="${QUERY_SAMPLE:-800}"
CONTEXT_SAMPLE="${CONTEXT_SAMPLE:-12596}"

# step 3, 4 y 5 pueden usar muestras distintas para queries y contexts.
RETRIEVAL_QUERY_SAMPLE="${RETRIEVAL_QUERY_SAMPLE:-$QUERY_SAMPLE}"
RETRIEVAL_CONTEXT_SAMPLE="${RETRIEVAL_CONTEXT_SAMPLE:-$CONTEXT_SAMPLE}"

FORMAT_QUERY_SAMPLE="${FORMAT_QUERY_SAMPLE:-$RETRIEVAL_QUERY_SAMPLE}"
FORMAT_CONTEXT_SAMPLE="${FORMAT_CONTEXT_SAMPLE:-$RETRIEVAL_CONTEXT_SAMPLE}"

RAGAS_QUERY_SAMPLE="${RAGAS_QUERY_SAMPLE:-$FORMAT_QUERY_SAMPLE}"
RAGAS_CONTEXT_SAMPLE="${RAGAS_CONTEXT_SAMPLE:-$FORMAT_CONTEXT_SAMPLE}"

TOP_K="${TOP_K:-5}"
BATCH_SIZE="${BATCH_SIZE:-64}"
INDEX_NAME="${INDEX_NAME:-faiss.index}"
METADATA_NAME="${METADATA_NAME:-metadata.jsonl}"
NO_NORMALIZE="${NO_NORMALIZE:-false}"

STEP1_INPUT_FILE="${STEP1_INPUT_FILE:-}"
STEP1_OUTPUT_DIR="${STEP1_OUTPUT_DIR:-}"

STEP2_INPUT_FILE="${STEP2_INPUT_FILE:-}"
STEP2_OUTPUT_DIR="${STEP2_OUTPUT_DIR:-}"

STEP3_QUERIES_FILE="${STEP3_QUERIES_FILE:-}"
STEP3_INDEX_FILE="${STEP3_INDEX_FILE:-}"
STEP3_METADATA_FILE="${STEP3_METADATA_FILE:-}"
STEP3_OUTPUT_FILE="${STEP3_OUTPUT_FILE:-}"

STEP4_INPUT_FILE="${STEP4_INPUT_FILE:-}"
STEP4_REFERENCES_FILE="${STEP4_REFERENCES_FILE:-}"
STEP4_REFERENCE_CONTEXTS_FILE="${STEP4_REFERENCE_CONTEXTS_FILE:-}"
STEP4_OUTPUT_FILE="${STEP4_OUTPUT_FILE:-}"

STEP5_INPUT_FILE="${STEP5_INPUT_FILE:-}"
STEP5_OUTPUT_FILE="${STEP5_OUTPUT_FILE:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)
            DOMAIN="$2"; shift 2 ;;
        --task)
            TASK="$2"; shift 2 ;;
        --force)
            FORCE="$2"; shift 2 ;;
        --config)
            CONFIG_FILE="$2"; shift 2 ;;
        --python-bin)
            PYTHON_BIN="$2"; shift 2 ;;

        --query-sample)
            QUERY_SAMPLE="$2"; shift 2 ;;
        --context-sample)
            CONTEXT_SAMPLE="$2"; shift 2 ;;
        --sample-query|--retrieval-query-sample)
            RETRIEVAL_QUERY_SAMPLE="$2"; shift 2 ;;
        --sample-context|--retrieval-context-sample)
            RETRIEVAL_CONTEXT_SAMPLE="$2"; shift 2 ;;
        --format-query-sample)
            FORMAT_QUERY_SAMPLE="$2"; shift 2 ;;
        --format-context-sample)
            FORMAT_CONTEXT_SAMPLE="$2"; shift 2 ;;
        --ragas-query-sample)
            RAGAS_QUERY_SAMPLE="$2"; shift 2 ;;
        --ragas-context-sample)
            RAGAS_CONTEXT_SAMPLE="$2"; shift 2 ;;

        --top-k)
            TOP_K="$2"; shift 2 ;;
        --batch-size)
            BATCH_SIZE="$2"; shift 2 ;;
        --index-name)
            INDEX_NAME="$2"; shift 2 ;;
        --metadata-name)
            METADATA_NAME="$2"; shift 2 ;;
        --no-normalize)
            NO_NORMALIZE="true"; shift ;;

        --step1-input-file)
            STEP1_INPUT_FILE="$2"; shift 2 ;;
        --step1-output-dir)
            STEP1_OUTPUT_DIR="$2"; shift 2 ;;
        --step2-input-file)
            STEP2_INPUT_FILE="$2"; shift 2 ;;
        --step2-output-dir)
            STEP2_OUTPUT_DIR="$2"; shift 2 ;;
        --step3-queries-file)
            STEP3_QUERIES_FILE="$2"; shift 2 ;;
        --step3-index-file)
            STEP3_INDEX_FILE="$2"; shift 2 ;;
        --step3-metadata-file)
            STEP3_METADATA_FILE="$2"; shift 2 ;;
        --step3-output-file)
            STEP3_OUTPUT_FILE="$2"; shift 2 ;;
        --step4-input-file)
            STEP4_INPUT_FILE="$2"; shift 2 ;;
        --step4-references-file)
            STEP4_REFERENCES_FILE="$2"; shift 2 ;;
        --step4-reference-contexts-file)
            STEP4_REFERENCE_CONTEXTS_FILE="$2"; shift 2 ;;
        --step4-output-file)
            STEP4_OUTPUT_FILE="$2"; shift 2 ;;
        --step5-input-file)
            STEP5_INPUT_FILE="$2"; shift 2 ;;
        --step5-output-file)
            STEP5_OUTPUT_FILE="$2"; shift 2 ;;

        --help|-h)
            usage
            exit 0 ;;
        *)
            echo "[ERROR] Argumento no reconocido: $1"
            usage
            exit 1 ;;
    esac
done

case "$TASK" in
    retrieval|generation|all|precision)
        ;;
    *)
        echo "[ERROR] Valor inválido para --task: $TASK"
        echo "        Valores válidos: retrieval | generation | all | precision"
        usage
        exit 1
        ;;
esac

# Si se redefinen samples base por CLI/env, y no se definieron explícitamente
# los samples específicos de cada paso, heredan los valores base.
if [[ -z "${RETRIEVAL_QUERY_SAMPLE:-}" ]]; then
    RETRIEVAL_QUERY_SAMPLE="$QUERY_SAMPLE"
fi
if [[ -z "${RETRIEVAL_CONTEXT_SAMPLE:-}" ]]; then
    RETRIEVAL_CONTEXT_SAMPLE="$CONTEXT_SAMPLE"
fi
if [[ -z "${FORMAT_QUERY_SAMPLE:-}" ]]; then
    FORMAT_QUERY_SAMPLE="$RETRIEVAL_QUERY_SAMPLE"
fi
if [[ -z "${FORMAT_CONTEXT_SAMPLE:-}" ]]; then
    FORMAT_CONTEXT_SAMPLE="$RETRIEVAL_CONTEXT_SAMPLE"
fi
if [[ -z "${RAGAS_QUERY_SAMPLE:-}" ]]; then
    RAGAS_QUERY_SAMPLE="$FORMAT_QUERY_SAMPLE"
fi
if [[ -z "${RAGAS_CONTEXT_SAMPLE:-}" ]]; then
    RAGAS_CONTEXT_SAMPLE="$FORMAT_CONTEXT_SAMPLE"
fi

EMBEDDING_MODEL_ID="$($PYTHON_BIN - "$CONFIG_FILE" <<'PY'
import sys
from pathlib import Path
import yaml

cfg_path = Path(sys.argv[1])
if not cfg_path.is_absolute():
    cfg_path = Path.cwd() / cfg_path

try:
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
except Exception:
    cfg = {}

model_name = str((cfg.get("encoder-api") or {}).get("model_name") or "").strip()
model_id = model_name.split("/")[-1].strip() if model_name else "unknown-model"
print(model_id or "unknown-model")
PY
)"

PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYTHONUNBUFFERED

run_step() {
    local step_name="$1"
    shift
    echo ""
    echo "============================================================"
    echo "${step_name}"
    echo "============================================================"
    "$PYTHON_BIN" "$@"
}

echo "Launching RAGAS pipeline"
echo "- Domain: ${DOMAIN}"
echo "- Task: ${TASK}"
echo "- Query sample: ${QUERY_SAMPLE}"
echo "- Context sample: ${CONTEXT_SAMPLE}"
echo "- Retrieval query/context samples: ${RETRIEVAL_QUERY_SAMPLE}/${RETRIEVAL_CONTEXT_SAMPLE}"
echo "- Format query/context samples: ${FORMAT_QUERY_SAMPLE}/${FORMAT_CONTEXT_SAMPLE}"
echo "- RAGAS query/context samples: ${RAGAS_QUERY_SAMPLE}/${RAGAS_CONTEXT_SAMPLE}"
echo "- Config: ${CONFIG_FILE}"
echo "- Embedding model id: ${EMBEDDING_MODEL_ID}"

# ============================================================
# Paso 1: generar queries/references/reference_contexts
# ============================================================
STEP1_ARGS=(
    step_1_data.py
    --domain "$DOMAIN"
    --sample "$QUERY_SAMPLE"
)

if [[ -n "$STEP1_INPUT_FILE" ]]; then
    STEP1_ARGS+=(--input_file "$STEP1_INPUT_FILE")
fi
if [[ -n "$STEP1_OUTPUT_DIR" ]]; then
    STEP1_ARGS+=(--output_dir "$STEP1_OUTPUT_DIR")
fi

run_step "STEP 1: Data preparation" "${STEP1_ARGS[@]}"

# ============================================================
# Paso 2: construir base vectorial FAISS
# ============================================================
STEP2_ARGS=(
    step_2_database.py
    --domain "$DOMAIN"
    --config "$CONFIG_FILE"
    --sample "$CONTEXT_SAMPLE"
    --index_name "$INDEX_NAME"
    --metadata_name "$METADATA_NAME"
)

if [[ -n "$STEP2_INPUT_FILE" ]]; then
    STEP2_ARGS+=(--input_file "$STEP2_INPUT_FILE")
fi
if [[ -n "$STEP2_OUTPUT_DIR" ]]; then
    STEP2_ARGS+=(--output_dir "$STEP2_OUTPUT_DIR")
fi
if [[ "$NO_NORMALIZE" == "true" ]]; then
    STEP2_ARGS+=(--no_normalize)
fi

run_step "STEP 2: Build vector DB" "${STEP2_ARGS[@]}"

# ============================================================
# Paso 3: compute retrieval
# ============================================================
STEP3_ARGS=(
    step_3_compute_retrieval.py
    --domain "$DOMAIN"
    --config "$CONFIG_FILE"
    # --top_k "$TOP_K"
    # --batch_size "$BATCH_SIZE"
    --sample-query "$RETRIEVAL_QUERY_SAMPLE"
    --sample-context "$RETRIEVAL_CONTEXT_SAMPLE"
)

if [[ "$FORCE" == "true" ]]; then
    STEP3_ARGS+=(--force)
fi
if [[ -n "$STEP3_QUERIES_FILE" ]]; then
    STEP3_ARGS+=(--queries_file "$STEP3_QUERIES_FILE")
fi
if [[ -n "$STEP3_INDEX_FILE" ]]; then
    STEP3_ARGS+=(--index_file "$STEP3_INDEX_FILE")
elif [[ -n "$INDEX_NAME" ]]; then
    STEP3_ARGS+=(--index_file "data/${DOMAIN}/ALIA-${DOMAIN}-contexts-${RETRIEVAL_CONTEXT_SAMPLE}/vector_db/${EMBEDDING_MODEL_ID}/${INDEX_NAME}")
fi
if [[ -n "$STEP3_METADATA_FILE" ]]; then
    STEP3_ARGS+=(--metadata_file "$STEP3_METADATA_FILE")
elif [[ -n "$METADATA_NAME" ]]; then
    STEP3_ARGS+=(--metadata_file "data/${DOMAIN}/ALIA-${DOMAIN}-contexts-${RETRIEVAL_CONTEXT_SAMPLE}/vector_db/${EMBEDDING_MODEL_ID}/${METADATA_NAME}")
fi
if [[ -n "$STEP3_OUTPUT_FILE" ]]; then
    STEP3_ARGS+=(--output_file "$STEP3_OUTPUT_FILE")
fi

run_step "STEP 3: Compute retrieval" "${STEP3_ARGS[@]}"

# ============================================================
# Paso 4: formatear para RAGAS
# ============================================================
STEP4_ARGS=(
    step_4_format_for_ragas.py
    --domain "$DOMAIN"
    --config "$CONFIG_FILE"
    --sample-query "$FORMAT_QUERY_SAMPLE"
    --sample-context "$FORMAT_CONTEXT_SAMPLE"
)

if [[ "$FORCE" == "true" ]]; then
    STEP4_ARGS+=(--force)
fi
if [[ -n "$STEP4_INPUT_FILE" ]]; then
    STEP4_ARGS+=(--input_file "$STEP4_INPUT_FILE")
fi
if [[ -n "$STEP4_REFERENCES_FILE" ]]; then
    STEP4_ARGS+=(--references_file "$STEP4_REFERENCES_FILE")
fi
if [[ -n "$STEP4_REFERENCE_CONTEXTS_FILE" ]]; then
    STEP4_ARGS+=(--reference_contexts_file "$STEP4_REFERENCE_CONTEXTS_FILE")
fi
if [[ -n "$STEP4_OUTPUT_FILE" ]]; then
    STEP4_ARGS+=(--output_file "$STEP4_OUTPUT_FILE")
fi

run_step "STEP 4: Format for RAGAS" "${STEP4_ARGS[@]}"

# ============================================================
# Paso 5: ejecutar RAGAS
# ============================================================
STEP5_ARGS=(
    step_5_run_ragas.py
    --domain "$DOMAIN"
    --task "$TASK"
    --config "$CONFIG_FILE"
    --sample-query "$RAGAS_QUERY_SAMPLE"
    --sample-context "$RAGAS_CONTEXT_SAMPLE"
)

if [[ "$FORCE" == "true" ]]; then
    STEP5_ARGS+=(--force)
fi
if [[ -n "$STEP5_INPUT_FILE" ]]; then
    STEP5_ARGS+=(--input_file "$STEP5_INPUT_FILE")
fi
if [[ -n "$STEP5_OUTPUT_FILE" ]]; then
    STEP5_ARGS+=(--output_file "$STEP5_OUTPUT_FILE")
fi

run_step "STEP 5: Run RAGAS" "${STEP5_ARGS[@]}"

echo ""
echo "============================================================"
echo "Pipeline completed successfully"
echo "============================================================"