#!/bin/bash
#SBATCH --job-name=EncDATA
#SBATCH --partition=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --mem=48G
#SBATCH --gres=gpu:0 # !
#SBATCH --nodelist=nodo04
#SBATCH --output="/mnt/beegfs/alia-data/alia/evaluation/encoder/logs/launcher_format_data/%A_ALIA-evaluation_format_data.out"
#SBATCH --error="/mnt/beegfs/alia-data/alia/evaluation/encoder/logs/launcher_format_data/%A_ALIA-evaluation_format_data.err"

# Limpieza de módulos cargados
module purge

# Carga de módulos software
spack load miniconda3

# Activación de entorno virtual
source activate alia-eval

# Ejecución del script
echo "Ejecutando formateo de datos con args: evaluation_format_data.py $*"
SCRIPTS_DIR="/mnt/beegfs/alia-data/alia/evaluation/encoder/scripts"
srun python "$SCRIPTS_DIR/evaluation_format_data.py" --domain "$1" --task "$2"

# Uso:
# sbatch evaluation/encoder/launchers/launcher_format_data.sh <domain> <task>