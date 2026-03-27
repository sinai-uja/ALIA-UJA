#!/bin/bash
set -euo pipefail

RUN_SCRIPT_PATH="$(dirname "$0")/launcher_job.sh"

# ------------------------------------------------------------------
# 1) Guardar args originales (los que quieres reenviar a Python)
orig_args=( "$@" )

# ------------------------------------------------------------------
# 2) Parse mínimo (sin perder los originales)
DOMAIN=""
LANG=""
SINGLE_STEP=""
START_STEP=""
END_STEP=""

# Usamos un array temporal para poder hacer shift sin romper orig_args
tmp_args=( "$@" )
while [[ ${#tmp_args[@]} -gt 0 ]]; do
  case "${tmp_args[0]}" in
    --domain)
      DOMAIN="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    --lang)
      LANG="${tmp_args[1]:-}"
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

# Comprobar que DOMAIN no esté vacío
if [[ -z "$DOMAIN" ]]; then
  echo "Error: --domain no especificado. Uso: $0 --domain <nombre_del_dominio> --lang <es|en>"
  echo 'Argumentos opcionales: --single_step <task> --start_step <task> --end_step <task> ' >&2
  exit 1
fi

# Comprobar que LANG no esté vacío
if [[ -z "$LANG" ]]; then
  echo "Error: --lang no especificado. Uso: $0 --domain <nombre_del_dominio> --lang <es|en>"
  exit 1
fi

# ------------------------------------------------------------------

USER_NAME="${USER:-unknown}"

# ------------------------------------------------------------------
# 4) Logs dinámicos según tarea
LOG_DIR="$(pwd)/data/llms/logs/instructions/${DOMAIN}-${LANG}"
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

OUT_FILE="${LOG_DIR}/%A_ALIA_instructions${LOG_SUFFIX}_${USER_NAME}.out.log"
ERR_FILE="${LOG_DIR}/%A_ALIA_instructions${LOG_SUFFIX}_${USER_NAME}.err.log"

# ------------------------------------------------------------------
# 5) Submit real (job-name = "INST-<first 3 characters of ${DOMAIN}>-${LANG}") y reenviar args originales
DOMAIN=${DOMAIN:-XXX}  # Fallback if unset
LANG=${LANG:-es}       # Fallback if unset
sbatch \
  --job-name="INST-${DOMAIN:0:3}-${LANG}" \
  --output="$OUT_FILE" \
  --error="$ERR_FILE" \
  --export=ALL \
  "$RUN_SCRIPT_PATH" "$@"

# USE:
# bash launcher_parent.sh --domain "biomedical" --lang "es" --end_step "downsampling"