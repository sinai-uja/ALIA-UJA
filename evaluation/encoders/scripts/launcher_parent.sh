#!/bin/bash
set -euo pipefail

# ------------------------------------------------------------------
# 1) Guardar args originales (los que quieres reenviar al script)
orig_args=( "$@" )

# ------------------------------------------------------------------
# 2) Parse mínimo (sin perder los originales)
SCRIPT_NAME=""
MODEL_NAME=""
DOMAIN=""
DATASET=""
TASK=""
ENV_NAME=""

VALID_SCRIPTS=("launcher_evaluation_biencoder" "launcher_evaluation_crossencoder" "launcher_format_data")

# Usamos un array temporal para poder hacer shift sin romper orig_args
tmp_args=( "$@" )
while [[ ${#tmp_args[@]} -gt 0 ]]; do
  case "${tmp_args[0]}" in
    --script)
      SCRIPT_NAME="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --model_name)
      MODEL_NAME="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --domain)
      DOMAIN="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --dataset)
      DATASET="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --task)
      TASK="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --env)
      ENV_NAME="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    *)
      tmp_args=( "${tmp_args[@]:1}" )
      ;;
  esac
done

# ------------------------------------------------------------------
# 3) Validación del script
if [[ -z "$SCRIPT_NAME" ]]; then
  echo "ERROR: argumento obligatorio: --script <SCRIPT_NAME>" >&2
  echo "Scripts válidos: ${VALID_SCRIPTS[*]}" >&2
  exit 2
fi

# Comprobar que el script es válido
SCRIPT_VALID=false
for valid in "${VALID_SCRIPTS[@]}"; do
  if [[ "$SCRIPT_NAME" == "$valid" ]]; then
    SCRIPT_VALID=true
    break
  fi
done

if [[ "$SCRIPT_VALID" == false ]]; then
  echo "ERROR: script '$SCRIPT_NAME' no válido." >&2
  echo "Scripts válidos: ${VALID_SCRIPTS[*]}" >&2
  exit 2
fi

# ------------------------------------------------------------------
# 4) Validación de parámetros según el script
case "$SCRIPT_NAME" in
  launcher_evaluation_biencoder|launcher_evaluation_crossencoder)
    if [[ -z "$MODEL_NAME" || -z "$DOMAIN" || -z "$DATASET" || -z "$ENV_NAME" ]]; then
      echo "ERROR: para '$SCRIPT_NAME' son obligatorios: --model_name <NAME>, --domain <DOMAIN>, --dataset <SET> y --env <ENV>" >&2
      echo "Ejemplo: bash $0 --script $SCRIPT_NAME --model_name \"Qwen/Qwen3-Embedding-0.6B\" --domain legal --dataset \"justicio-Retrieval\" --env venv" >&2
      exit 2
    fi
    ;;
  launcher_format_data)
    if [[ -z "$DOMAIN" || -z "$TASK" || -z "$ENV_NAME" ]]; then
      echo "ERROR: para '$SCRIPT_NAME' son obligatorios: --domain <DOMAIN>, --task <TASK> y --env <ENV>" >&2
      echo "Ejemplo: bash $0 --script $SCRIPT_NAME --domain \"biomedical\" --task \"task\" --env venv" >&2
      exit 2
    fi
    ;;
esac

USER_NAME="${USER:-unknown}"

# ------------------------------------------------------------------
# 5) Logs dinámicos según el script y sus parámetros
LOG_DIR="$(pwd)/evaluation/encoder/logs/${SCRIPT_NAME}/${DOMAIN}"
mkdir -p "$LOG_DIR"

case "$SCRIPT_NAME" in
  launcher_evaluation_biencoder|launcher_evaluation_crossencoder)
    # Reemplazar "/" por "_" en el nombre del modelo para evitar problemas en nombres de archivos
    FORMATTED_MODEL_NAME="${MODEL_NAME//\//_}"
    LOG_PREFIX="%A_ALIA-${DOMAIN}-${FORMATTED_MODEL_NAME}-${DATASET}-${USER_NAME}"
    ;;
  launcher_format_data)
    LOG_PREFIX="%A_ALIA-${DOMAIN}-${TASK}-${USER_NAME}"
    ;;
esac

OUT_FILE="${LOG_DIR}/${LOG_PREFIX}.out.log"
ERR_FILE="${LOG_DIR}/${LOG_PREFIX}.err.log"

# ------------------------------------------------------------------
# 6) Eliminar --script y su valor del array de args antes de reenviar
filtered_args=()
skip_next=false
for arg in "${orig_args[@]}"; do
  if $skip_next; then
    skip_next=false
    continue
  fi
  if [[ "$arg" == "--script" ]]; then
    skip_next=true
    continue
  fi
  filtered_args+=( "$arg" )
done

# ------------------------------------------------------------------
# 7) Submit real y reenviar args filtrados al script destino
RUN_SCRIPT_PATH="$(dirname "$0")/${SCRIPT_NAME}.sh"

if [[ ! -f "$RUN_SCRIPT_PATH" ]]; then
  echo "ERROR: no se encontró el script '$RUN_SCRIPT_PATH'" >&2
  exit 2
fi

echo "Submitting job: SCRIPT='$SCRIPT_NAME', args: ${filtered_args[*]}"
sbatch \
  --output="$OUT_FILE" \
  --error="$ERR_FILE" \
  "$RUN_SCRIPT_PATH" "${filtered_args[@]}"

# USO: 
# biencoders
# bash launcher_parent.sh --script launcher_evaluation_biencoder --model_name <model> --domain biomedical --dataset <dataset> --env venv
# crossencoders
# bash launcher_parent.sh --script launcher_evaluation_crossencoder --model_name <model> --domain biomedical --dataset <dataset> --env venv
# format_data
# bash launcher_parent.sh --script launcher_format_data --domain biomedical --dataset <dataset> --env venv
