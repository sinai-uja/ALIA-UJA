#!/bin/bash
#SBATCH --job-name=ALIA_train_carbon_cpt
#SBATCH --partition=genoa
#SBATCH --qos=long
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=64
#SBATCH --time=10-00:00:00
#SBATCH --mem=0
#SBATCH --output="logs/%A_ALIA_train_carbon_cpt.out"
#SBATCH --error="logs/%A_ALIA_train_carbon_cpt.err"

set -euo pipefail

MODE="raw"

if [[ "$MODE" != "raw" && "$MODE" != "inst" ]]; then
  echo "❌ Parámetro no válido. Usa uno de: raw | inst"
  exit 1
fi

echo "🔧 Modo seleccionado: $MODE"

module purge
module use /path/to/modules/
module load CUDA/12.6.0
source /path/to/conda/etc/profile.d/conda.sh
conda activate axolotl


# ---- Rutas Relativas ----
BASE_DIR="$(dirname "$(readlink -f "$0")")"
CONFIG_FILE="$BASE_DIR/axolotl_config.yml"
DEEPSPEED_CONFIG="$BASE_DIR/ds_config.json"
TRACKER_SCRIPT="$BASE_DIR/track_emissions.py"
# -------------------------

GPUS_PER_NODE=4
NNODES=${SLURM_NNODES:-1}
WORLD_SIZE=$(( NNODES * GPUS_PER_NODE ))

MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n 1)
MASTER_PORT=25002

echo "✅ BASE_DIR=$BASE_DIR"
echo "✅ CONFIG_FILE=$CONFIG_FILE"
echo "✅ DEEPSPEED=$DEEPSPEED_CONFIG"
echo "✅ TRACKER_SCRIPT=$TRACKER_SCRIPT"

export MASTER_ADDR MASTER_PORT WORLD_SIZE
export GPUS_PER_NODE NNODES
export OMP_NUM_THREADS=64
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1
export NCCL_DEBUG=INFO
export NCCL_IB_DISABLE=1
export NCCL_SOCKET_IFNAME=^lo,docker
export DISABLE_FLASH_ATTN=1
export DISABLE_FLASH_ATTN_2=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "SLURM_JOBID=$SLURM_JOBID"
echo "SLURM_JOB_NODELIST=$SLURM_JOB_NODELIST"
echo "NNODES=$NNODES  GPUS_PER_NODE=$GPUS_PER_NODE  WORLD_SIZE=$WORLD_SIZE"
echo "MASTER_ADDR=$MASTER_ADDR  MASTER_PORT=$MASTER_PORT"

# Crear directorio de logs si no existe
mkdir -p logs

# -------------------------------
# Lanzar entrenamiento con CodeCarbon
# -------------------------------
srun torchrun \
  --nproc_per_node=$GPUS_PER_NODE \
  --nnodes=$NNODES \
  --rdzv_backend=c10d \
  --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT \
  --rdzv_id=alia_run_cpt_$SLURM_JOBID \
  "$TRACKER_SCRIPT" \
  --config "$CONFIG_FILE" \
  --deepspeed "$DEEPSPEED_CONFIG" \
  --run_name "$MODE"
