#!/bin/bash
##SBATCH arguments (https://slurm.schedmd.com/sbatch.html#SECTION_OPTIONS)

set -euo pipefail

BASE_SCRIPT_PATH="/path_to/scripts"
SCRIPT_PATH="$BASE_SCRIPT_PATH/corpora/corpora_manager.py"

source activate venv

echo "Running: srun python $SCRIPT_PATH $*"
srun python "$SCRIPT_PATH" "$@"
