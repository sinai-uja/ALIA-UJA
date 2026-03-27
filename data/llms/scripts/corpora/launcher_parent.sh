#!/bin/bash
set -euo pipefail

RUN_SCRIPT_PATH="$(dirname "$0")/launcher_job.sh"

# ------------------------------------------------------------------
# 1) Guardar args originales (los que quieres reenviar a Python)
orig_args=( "$@" )

# ------------------------------------------------------------------
# 2) Parse mínimo (sin perder los originales)
CORPUS_NAME=""
CORPUS_DOMAIN=""
SINGLE_STEP=""
START_STEP=""
END_STEP=""

# Usamos un array temporal para poder hacer shift sin romper orig_args
tmp_args=( "$@" )
while [[ ${#tmp_args[@]} -gt 0 ]]; do
  case "${tmp_args[0]}" in
    --name)
      CORPUS_NAME="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --domain)
      CORPUS_DOMAIN="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --single_step)
      SINGLE_STEP="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --start_step)
      START_STEP="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --end_step)
      END_STEP="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    *)
      tmp_args=( "${tmp_args[@]:1}" )
      ;;
  esac
done


# ------------------------------------------------------------------
# 3) Validación obligatorios
if [[ -z "$CORPUS_NAME" || -z "$CORPUS_DOMAIN" ]]; then
  echo "ERROR: argumentos obligatorios: --name <NAME> y --domain <DOMAIN>" >&2
  echo 'Ejemplo: bash launcher.sh --name biomedical --domain biomedical' >&2
  echo 'Argumentos opcionales: --single_step <task> --start_step <task> --end_step <task> ' >&2
  echo '- Tareas disponibles (en orden): initial, clean, split, datatrove, complete, downsampling' >&2
  exit 2
fi

USER_NAME="${USER:-unknown}"

# ------------------------------------------------------------------
# 4) Logs dinámicos según tarea
LOG_DIR="$(pwd)/data/llms/logs/corpora/${CORPUS_DOMAIN}"
mkdir -p "$LOG_DIR"

# Construir sufijo del nombre del log según las tareas
LOG_SUFFIX=""
if [[ -n "$SINGLE_STEP" ]]; then
  LOG_SUFFIX="_${SINGLE_STEP}"
elif [[ -n "$START_STEP" && -n "$END_STEP" ]]; then
  LOG_SUFFIX="_start-${START_STEP}_end-${END_STEP}"
elif [[ -n "$START_STEP" ]]; then
  LOG_SUFFIX="_start-${START_STEP}"
elif [[ -n "$END_STEP" ]]; then
  LOG_SUFFIX="_end-${END_STEP}"
fi

OUT_FILE="${LOG_DIR}/%A_ALIA_corpora_${CORPUS_NAME}${LOG_SUFFIX}_${USER_NAME}.out.log"
ERR_FILE="${LOG_DIR}/%A_ALIA_corpora_${CORPUS_NAME}${LOG_SUFFIX}_${USER_NAME}.err.log"

# ------------------------------------------------------------------
# 5) Submit real (job-name = --name) y reenviar args originales
sbatch \
  --job-name="${CORPUS_NAME}" \
  --output="$OUT_FILE" \
  --error="$ERR_FILE" \
  "$RUN_SCRIPT_PATH" "${orig_args[@]}"

# USE:
# launcher_parent.sh --name "biomedical" --domain "biomedical" --end_step "downsampling"
