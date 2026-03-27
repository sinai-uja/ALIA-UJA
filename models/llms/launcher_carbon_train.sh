#!/bin/bash
#SBATCH --job-name=
#SBATCH --partition=
#SBATCH --qos=
#SBATCH --nodes=
#SBATCH --ntasks-per-node=
#SBATCH --gres=
#SBATCH --cpus-per-task=
#SBATCH --time=
#SBATCH --mem=
#SBATCH --output=""
#SBATCH --error=""

set -euo pipefail
PATHS_YAML="/path/to/your/path/yaml"

# --- Leer claves del YAML ---
get_yaml_value() {
  grep "^$1:" "$PATHS_YAML" | awk '{print $2}' | tr -d '"'
}

BASE_DIR=$(get_yaml_value BASE_DIR)
DEEPSPEED_CONFIG=$(get_yaml_value DEEPSPEED)

MODE=${1:-raw}   #raw como valor por defecto

if [[ "$MODE" != "raw" && "$MODE" != "inst" && "$MODE" != "30raw70inst" && "$MODE" != "50raw50inst" && "$MODE" != "70raw30inst" ]]; then
  echo "❌ Parámetro no válido. Usa uno de: raw | inst | 30raw70inst | 50raw50inst | 70raw30inst"
  exit 1
fi

echo "🔧 Modo seleccionado: $MODE"

module purge
module use /path/to/modules # Example /EB/modules/all/ 
module load CUDA/12.6.0
source /path/to/conda
conda activate axolotl

# -------------------------------
# 2. Variables del cluster
# -------------------------------
CONFIG_FILE="$BASE_DIR/axolotl_config/axo_config_emi2b_${MODE}.yml"

GPUS_PER_NODE=4
NNODES=${SLURM_NNODES:-1}
WORLD_SIZE=$(( NNODES * GPUS_PER_NODE ))

MASTER_ADDR=$(scontrol show hostnames $SLURM_JOB_NODELIST | head -n 1)
MASTER_PORT=$((29500 + RANDOM % 500))

export MASTER_ADDR MASTER_PORT WORLD_SIZE
export GPUS_PER_NODE NNODES DEEPSPEED_CONFIG
export OMP_NUM_THREADS=64
export PYTHONFAULTHANDLER=1
export PYTHONUNBUFFERED=1
export NCCL_DEBUG=INFO
export NCCL_IB_DISABLE=1
export NCCL_SOCKET_IFNAME=^lo,docker
export DISABLE_FLASH_ATTN=1
export DISABLE_FLASH_ATTN_2=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# Normalizar las GPUs de cada nodo a 0,1,2,3
export CUDA_VISIBLE_DEVICES=$(nvidia-smi --query-gpu=index --format=csv,noheader | tr '\n' ',' | sed 's/,$//')



echo "SLURM_JOBID=$SLURM_JOBID"
echo "SLURM_JOB_NODELIST=$SLURM_JOB_NODELIST"
echo "NNODES=$NNODES  GPUS_PER_NODE=$GPUS_PER_NODE  WORLD_SIZE=$WORLD_SIZE"
echo "MASTER_ADDR=$MASTER_ADDR  MASTER_PORT=$MASTER_PORT"

# -------------------------------
# 3. Lanzar entrenamiento con CodeCarbon
# -------------------------------
srun torchrun \
  --nproc_per_node=$GPUS_PER_NODE \
  --nnodes=$NNODES \
  --rdzv_backend=c10d \
  --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT \
  --rdzv_id=alia_run_$SLURM_JOBID \
  $BASE_DIR/train.py -- \
  --config $CONFIG_FILE \
  --deepspeed $DEEPSPEED_CONFIG \
  --run_name $MODE
