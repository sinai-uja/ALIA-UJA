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

export NPROC_PER_NODE=2
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export WANDB_MODE="offline"
export CUDA_VISIBLE_DEVICES=0,1
swift sft \
    --tuner_backend peft \
    --seed 42 \
    --train_type lora \
    --lora_rank 16 \
    --ddp_backend "nccl" \
    --model /path/to/LLM \
    --model_type llama3 \
    --split_dataset_ratio 0 \
    --task_type generative_reranker  \
    --loss_type generative_reranker \
    --dataset /path/to/dataset \
    --val_dataset /path/to/evaluation_dataset \
    --truncation_strategy right \
    --load_from_cache_file False \
    --columns '{"rejected_responses": "rejected_response"}' \
    --gradient_checkpointing True \
    --gradient_accumulation_steps 8 \
    --streaming True \
    --per_device_train_batch_size 1 \
    --per_device_eval_batch_size 1 \
    --eval_accumulation_steps 1 \
    --learning_rate 6e-6 \
    --save_strategy 'steps' \
    --eval_strategy 'steps' \
    --eval_steps 100 \
    --save_steps 100 \
    --logging_steps 10 \
    --torch_dtype bfloat16 \
    --save_total_limit 1 \
    --dataloader_num_workers 4 \
    --deepspeed zero3 \
    --max_length 4096 \
    --max_new_tokens 512 \
    --load_best_model_at_end True \
    --metric_for_best_model 'eval_loss' \
    --greater_is_better False \
    --check_model False \
    --max_steps 1000 \
    --num_train_epochs 1 \
    --dataloader_drop_last True \
    --output_dir /path/to/output_dir \
    --report_to wandb \
    --run_name train-reranker-salamandra-2