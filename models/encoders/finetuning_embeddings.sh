#!/bin/bash
#SBATCH --job-name=
#SBATCH --partition=
#SBATCH --nodes=
#SBATCH --ntasks-per-node=
#SBATCH --mem=
#SBATCH --gres=
#SBATCH --nodelist=
#SBATCH --output=""
#SBATCH --error=""


# Limpieza de módulos cargados
module purge

# Carga de módulos software
spack load miniconda3
spack load cuda@12.1

# Activación de entorno virtual
source activate venv

export MASTER_PORT="29503"
export NPROC_PER_NODE=2
export WANDB_MODE="offline"
export CUDA_VISIBLE_DEVICES=2,3
swift sft \
    --tuner_backend peft \
    --seed 42 \
    --train_type lora \
    --ddp_backend "nccl" \
    --lora_rank 64 \
    --model /path/to/LLM \
    --model_type llama3 \
    --split_dataset_ratio 0.05 \
    --task_type embedding  \
    --loss_type infonce \
    --dataset /path/to/dataset \
    --val_dataset /path/to/evaluation_dataset \
    --truncation_strategy right \
    --load_from_cache_file False \
    --gradient_checkpointing True \
    --streaming True \
    --per_device_train_batch_size 1 \
    --per_device_eval_batch_size 2 \
    --learning_rate 6e-6 \
    --save_strategy 'steps' \
    --eval_steps 50 \
    --save_steps 50 \
    --num_train_epochs 1 \
    --logging_steps 5 \
    --dataloader_drop_last True \
    --torch_dtype bfloat16 \
    --save_total_limit 2 \
    --dataloader_num_workers 4 \
    --deepspeed zero3 \
    --gradient_accumulation_steps 16 \
    --max_length 8192 \
    --max_new_tokens 1024 \
    --check_model False \
    --max_steps 1000 \
    --output_dir /path/to/output_dir \
    --report_to wandb \
    --run_name train-embedding-salamandra

    