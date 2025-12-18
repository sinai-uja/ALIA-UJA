#!/bin/bash
#SBATCH --job-name=salamandra-translation
#SBATCH --partition=normal
#SBATCH --nodes=1
#SBATCH --output=logs/slurm/%A.out
#SBATCH --error=logs/slurm/%A.err
#SBATCH --ntasks=4
#SBATCH --mem=200G
#SBATCH --gres=gpu:ampere:4

# Información del job
echo "============================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "Starting time: $(date)"
echo "============================================"

# (Opcional) Limpieza de módulos cargados previamente
module purge

# (Opcional) Carga de módulos software,usualmente cuda y cudnn
spack load miniconda3 cuda@12.1

# Activar entorno (ajustar según tu configuración)
source activate parallel

# Variables de entorno para optimización
export OMP_NUM_THREADS=8
export TOKENIZERS_PARALLELISM=false
export CUDA_VISIBLE_DEVICES=0,1,2,3

# Información de las GPUs
nvidia-smi

echo ""
echo "Iniciando entrenamiento..."
echo ""

# DeepSpeed
deepspeed --num_gpus=4 train.py



echo ""
echo "============================================"
echo "Entrenamiento finalizado"
echo "End time: $(date)"
echo "============================================"

# Mostrar resumen de checkpoints guardados
echo ""
echo "Checkpoints guardados:"
ls -lh models/checkpoint-*

echo ""
echo "Para visualizar métricas en TensorBoard:"
echo "tensorboard --logdir models/salamandra-translation-biomedical/logs --port 6006"