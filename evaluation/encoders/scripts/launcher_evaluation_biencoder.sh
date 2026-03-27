#!/bin/bash
##SBATCH arguments (https://slurm.schedmd.com/sbatch.html#SECTION_OPTIONS)

# ------------------------------------------------------------------
# Parse --env del array de argumentos
ENV_NAME=""
tmp_args=( "$@" )
while [[ ${#tmp_args[@]} -gt 0 ]]; do
  case "${tmp_args[0]}" in
    --env)
      ENV_NAME="${tmp_args[1]:-}"
      tmp_args=( "${tmp_args[@]:2}" )
      ;;
    *)
      tmp_args=( "${tmp_args[@]:1}" )
      ;;
  esac
done

if [[ -z "$ENV_NAME" ]]; then
  echo "ERROR: argumento obligatorio: --env <ENV_NAME>" >&2
  exit 2
fi

# Activación de entorno virtual
echo "Activando entorno conda: $ENV_NAME"
source activate "$ENV_NAME"

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1

# Ejecución del script
echo "Ejecutando evaluación estática con args: evaluation_static_metrics_biencoder.py $*"
SCRIPTS_DIR="/path_to/evaluation/encoder/scripts"
srun python "$SCRIPTS_DIR/evaluation_static_metrics_biencoder.py" "$@"
