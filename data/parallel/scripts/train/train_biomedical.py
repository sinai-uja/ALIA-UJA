"""
Script de entrenamiento para modelo de traducción bidireccional (EN<->ES)
Usando Trainer estándar de Transformers
SIN DATA COLLATOR - Padding fijo a 2048
Optimizado para 4x Ampere 40GB con SHARDING DISTRIBUIDO
"""
import os
import yaml
import torch
import pandas as pd
import gc
from glob import glob
from datasets import IterableDataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainerCallback,
    Trainer,
    TrainingArguments
)
from typing import Dict, List
import evaluate
from tqdm import tqdm
import random
import pyarrow.parquet as pq

# ============================================================================
# CONFIGURACIÓN Y UTILIDADES
# ============================================================================


def load_config(path="config_biomedical.yaml"):
    """Carga configuración desde YAML"""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def create_translation_prompt(text: str, source_lang: str, target_lang: str) -> str:
    """Crea el prompt de traducción según especificaciones del modelo."""
    LONG_TEXT_THRESHOLD = 500
    is_long = len(text) > LONG_TEXT_THRESHOLD or '\n\n' in text
    
    if is_long:
        paragraphs = text.split('\n\n') if '\n\n' in text else [text]
        prompt = f"Please translate this text from {source_lang} into {target_lang}.\n"
        prompt += f"{source_lang}: "
        for para in paragraphs:
            prompt += f"{para}\n"
        prompt += f"{target_lang}:"
    else:
        prompt = f"Translate the following text from {source_lang} into {target_lang}.\n"
        prompt += f"{source_lang}: {text}\n"
        prompt += f"{target_lang}:"
    
    return prompt


def get_rank_and_world_size():
    """Obtiene el rank y world_size del proceso distribuido"""
    if torch.distributed.is_initialized():
        rank = torch.distributed.get_rank()
        world_size = torch.distributed.get_world_size()
    else:
        rank = int(os.environ.get('RANK', 0))
        world_size = int(os.environ.get('WORLD_SIZE', 1))
    
    return rank, world_size


# ============================================================================
# SHARDED STREAMING CON DISTRIBUCIÓN POR WORKER
# ============================================================================


def get_shard_files(shards_dir: str, split: str = "train") -> List[str]:
    """Obtiene la lista de archivos shard ordenados."""
    if split == "train":
        shard_pattern = os.path.join(shards_dir, "train_shards", "shard_*.parquet")
    else:
        shard_pattern = os.path.join(shards_dir, "validation.parquet")
    
    shard_files = sorted(glob(shard_pattern))
    
    if not shard_files:
        shard_pattern = os.path.join(shards_dir, f"{split}_sharded", "shard_*.parquet")
        shard_files = sorted(glob(shard_pattern))
    
    return shard_files


def distribute_shards_to_workers(shard_files: List[str], rank: int, world_size: int) -> List[str]:
    """Distribuye shards con round-robin, asegurando que todos los workers tengan datos"""
    if len(shard_files) < world_size:
        worker_shards = [shard_files[rank % len(shard_files)]]
        print(f"⚠️  Menos shards que workers. Worker {rank} procesará: {worker_shards}")
    else:
        worker_shards = [shard for i, shard in enumerate(shard_files) if i % world_size == rank]
    
    return worker_shards


def streaming_sharded_iterator(shard_files: List[str], chunk_size: int = 500,
                                shuffle_shards: bool = True, shuffle_seed: int = 42):
    """Itera sobre múltiples shards en streaming, procesando uno a la vez."""
    if shuffle_shards:
        shard_files = shard_files.copy()
        random.Random(shuffle_seed).shuffle(shard_files)
    
    print(f"  📊 Procesando {len(shard_files)} shards en este worker")
    
    for shard_idx, shard_file in enumerate(shard_files):
        print(f"  📂 Shard {shard_idx + 1}/{len(shard_files)}: {os.path.basename(shard_file)}")
        
        try:
            parquet_file = pq.ParquetFile(shard_file)
            total_rows = parquet_file.metadata.num_rows
            
            indices = list(range(total_rows))
            if shuffle_shards:
                random.Random(shuffle_seed + shard_idx).shuffle(indices)
            
            for chunk_start in range(0, total_rows, chunk_size):
                chunk_end = min(chunk_start + chunk_size, total_rows)
                chunk_indices = sorted(indices[chunk_start:chunk_end])
                
                table = parquet_file.read(columns=['text_en', 'text_es'])
                df_chunk = table.to_pandas().iloc[chunk_indices]
                
                df_chunk = df_chunk.dropna(subset=['text_en', 'text_es'])
                df_chunk = df_chunk[(df_chunk['text_en'].str.strip() != '') &
                                    (df_chunk['text_es'].str.strip() != '')]
                
                yield df_chunk
                
                del df_chunk, table
                gc.collect()
            
            del parquet_file
            
        except Exception as e:
            print(f"  ⚠️  Error procesando {shard_file}: {e}")
            continue
        
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def create_bidirectional_examples_generator(shard_files: List[str], tokenizer,
                                             max_length: int = 2048, chunk_size: int = 500,
                                             shuffle: bool = True, seed: int = 42):
    """
    Generador que devuelve ejemplos tokenizados con PADDING FIJO a 2048
    
    Formato esperado: {"input_ids": tensor, "attention_mask": tensor, "labels": tensor}
    Todos los tensors tienen longitud exacta = max_length (2048)
    """
    
    first_example_printed = False
        
    def process_example(source_text, target_text, source_lang, target_lang):
        nonlocal first_example_printed
        try:
            source_text = source_text.strip()
            target_text = target_text.strip()
            
            if not source_text or not target_text:
                return None
            
            # Crear el prompt
            prompt = create_translation_prompt(source_text, source_lang, target_lang)
            
            # Formato conversacional para aplicar chat template
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": target_text},
            ]
            
            # Aplicar chat template
            formatted_text = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False
            )
            
            # Tokenizar CON PADDING FIJO a max_length
            tokenized = tokenizer(
                formatted_text,
                truncation=True,
                max_length=max_length,
                padding='max_length',  # 🔥 PADDING FIJO
                return_tensors=None  # Listas, no tensors
            )
            
            # 🔥 CRÍTICO: Crear labels (copia de input_ids para causal LM)
            tokenized["labels"] = tokenized["input_ids"].copy()
            
            # 🔥 Enmascarar el prompt Y el padding
            # 1. Encontrar longitud del prompt
            prompt_only = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False,
                add_generation_prompt=True
            )
            prompt_tokens = tokenizer(prompt_only, add_special_tokens=False)["input_ids"]
            prompt_length = len(prompt_tokens)
            
            # 2. Enmascarar prompt con -100
            tokenized["labels"][:prompt_length] = [-100] * prompt_length
            
            # 3. Enmascarar tokens de padding (pad_token_id) con -100
            pad_token_id = tokenizer.pad_token_id
            for i in range(len(tokenized["labels"])):
                if tokenized["input_ids"][i] == pad_token_id:
                    tokenized["labels"][i] = -100
            
            if not first_example_printed:
                print("\n" + "="*80)
                print("🔍 DEBUG: PRIMER EJEMPLO (PADDING FIJO A 2048)")
                print("="*80)
                print(f"\n📝 Idioma fuente: {source_lang}")
                print(f"📝 Idioma objetivo: {target_lang}")
                print(f"\n🔤 Texto formateado:")
                print(formatted_text[:300] + "..." if len(formatted_text) > 300 else formatted_text)
                print(f"\n📊 Estadísticas:")
                print(f"  • Longitud FIJA: {len(tokenized['input_ids'])} tokens (padding a {max_length})")
                print(f"  • Longitud prompt: {prompt_length} tokens (enmascarado con -100)")
                print(f"  • Tokens NO padding: {sum(1 for x in tokenized['input_ids'] if x != pad_token_id)}")
                print(f"  • Tokens para calcular loss: {sum(1 for x in tokenized['labels'] if x != -100)}")
                print(f"  • Pad token ID: {pad_token_id}")
                print("\n✅ Loss se calculará solo en la respuesta del asistente (sin prompt ni padding)")
                print("="*80 + "\n")
                first_example_printed = True
            
            return tokenized
        
        except Exception as e:
            print(f"Error procesando ejemplo: {e}")
            return None
    
    for df_chunk in streaming_sharded_iterator(shard_files, chunk_size, shuffle, seed):
        examples = []
        for _, row in df_chunk.iterrows():
            # EN -> ES
            ex1 = process_example(row['text_en'], row['text_es'], 'English', 'Spanish')
            if ex1 is not None:
                examples.append(ex1)
            
            # ES -> EN
            ex2 = process_example(row['text_es'], row['text_en'], 'Spanish', 'English')
            if ex2 is not None:
                examples.append(ex2)
        
        if shuffle:
            random.Random(seed).shuffle(examples)
        
        for example in examples:
            yield example
        
        del examples, df_chunk
        gc.collect()


# ============================================================================
# CALLBACKS
# ============================================================================

class MemoryMonitorCallback(TrainerCallback):
    """Monitorea y libera memoria durante el entrenamiento"""
    
    def on_step_end(self, args, state, control, **kwargs):
        if state.global_step % 100 == 0:
            torch.cuda.empty_cache()
            gc.collect()


class EarlyStoppingCallback(TrainerCallback):
    """Early stopping basado en evaluaciones"""
    
    def __init__(self, early_stopping_patience: int = 5, early_stopping_threshold: float = 0.0):
        self.early_stopping_patience = early_stopping_patience
        self.early_stopping_threshold = early_stopping_threshold
        self.best_metric = None
        self.patience_counter = 0
        
    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if metrics is None:
            return control
        
        current_metric = metrics.get("eval_loss")
        if current_metric is None:
            return control
        
        if self.best_metric is None:
            self.best_metric = current_metric
            print(f"\n🎯 Early Stopping: Métrica inicial = {current_metric:.4f}")
            return control
        
        if self.best_metric - current_metric > self.early_stopping_threshold:
            improvement = self.best_metric - current_metric
            self.best_metric = current_metric
            self.patience_counter = 0
            print(f"\n✅ Métrica mejoró en {improvement:.4f} → {current_metric:.4f}")
        else:
            self.patience_counter += 1
            print(f"\n⚠️  Sin mejora ({self.patience_counter}/{self.early_stopping_patience})")
            
            if self.patience_counter >= self.early_stopping_patience:
                print(f"\n🛑 EARLY STOPPING: {self.early_stopping_patience} evaluaciones sin mejora")
                control.should_training_stop = True
        
        return control


class TranslationMetricsCallback(TrainerCallback):
    """Calcula métricas BLEU y chrF en evaluación"""
    
    def __init__(self, tokenizer, eval_shard_files: List[str], cfg):
        self.tokenizer = tokenizer
        self.eval_shard_files = eval_shard_files
        self.cfg = cfg
        self.bleu = evaluate.load("bleu")
        self.chrf = evaluate.load("chrf")
        
    def on_evaluate(self, args, state, control, model, metrics=None, **kwargs):
        print(f"\n📊 Métricas de traducción (paso {state.global_step})...")
        
        eval_size = 200
        first_shard = self.eval_shard_files[0] if self.eval_shard_files else None
        
        if not first_shard or not os.path.exists(first_shard):
            print("  ⚠️  No se encontró shard de evaluación")
            return control
        
        try:
            parquet_file = pq.ParquetFile(first_shard)
            table = parquet_file.read(columns=['text_en', 'text_es'])
            df_eval = table.to_pandas().head(eval_size).dropna()
        except Exception as e:
            print(f"  ⚠️  Error leyendo shard: {e}")
            return control
        
        predictions = []
        references = []
        
        model.eval()
        with torch.no_grad():
            for _, row in tqdm(df_eval.iterrows(), total=len(df_eval), desc="Evaluando", leave=False):
                if random.random() < 0.5:
                    source_text, target_text = row['text_en'], row['text_es']
                    source_lang, target_lang = 'English', 'Spanish'
                else:
                    source_text, target_text = row['text_es'], row['text_en']
                    source_lang, target_lang = 'Spanish', 'English'
                
                prompt = create_translation_prompt(source_text, source_lang, target_lang)
                inputs = self.tokenizer(prompt, return_tensors="pt", truncation=True,
                                        max_length=1024).to(model.device)
                
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=1024,
                    do_sample=False,
                    pad_token_id=self.tokenizer.eos_token_id,
                    num_beams=1
                )
                
                generated = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
                translation = generated.split(f"{target_lang}:")[-1].strip()
                
                predictions.append(translation)
                references.append(target_text)
                
                if len(predictions) % 50 == 0:
                    torch.cuda.empty_cache()
        
        bleu_score = self.bleu.compute(predictions=predictions, references=[[r] for r in references])
        chrf_score = self.chrf.compute(predictions=predictions, references=references)
        
        if metrics is not None:
            metrics['eval_bleu'] = bleu_score['bleu']
            metrics['eval_chrf'] = chrf_score['score']
        
        print(f"  • BLEU: {bleu_score['bleu']:.2f} | chrF: {chrf_score['score']:.2f} | Loss: {metrics.get('eval_loss', 0):.4f}")
        
        del df_eval, table, predictions, references
        torch.cuda.empty_cache()
        gc.collect()
        
        return control


# ============================================================================
# MAIN - CONFIGURACIÓN SIN DATA COLLATOR
# ============================================================================

def main():
    cfg = load_config("config_biomedical.yaml")
    
    print("=" * 80)
    print("🚀 ENTRENAMIENTO SIN DATA COLLATOR")
    print("✨ Padding fijo a 2048 tokens")
    print("✨ Loss solo en respuestas (labels enmascarados con -100)")
    print("=" * 80)
    
    # 🔍 BUSCAR CHECKPOINT MÁS RECIENTE
    out_dir = cfg["training"]["output_dir"]
    checkpoints = sorted(glob(os.path.join(out_dir, "checkpoint-*")))
    resume_from_checkpoint = checkpoints[-1] if checkpoints else None
    
    if resume_from_checkpoint:
        print(f"\n🔄 REANUDANDO desde: {resume_from_checkpoint}")
    else:
        print("\n🆕 Empezando entrenamiento desde cero")
        resume_from_checkpoint = None
        
    rank, world_size = get_rank_and_world_size()
    print(f"\n🔧 Worker {rank + 1}/{world_size}")
    
    model_path = cfg["model"]["name_or_path"]
    max_length = 2048  # 🔥 FIJO A 2048
    out_dir = cfg["training"]["output_dir"]
    data_dir = cfg["dataset"]["data_dir"]
    chunk_size = cfg["dataset"].get("chunk_size", 500)
    
    os.makedirs(out_dir, exist_ok=True)
    
    # 1️⃣ Obtener y distribuir shards
    print(f"\n📂 Buscando shards en: {data_dir}")
    
    all_train_shards = get_shard_files(data_dir, "train")
    all_val_shards = get_shard_files(data_dir, "validation")
    
    print(f"  • Total train shards: {len(all_train_shards)}")
    print(f"  • Total validation shards: {len(all_val_shards)}")
    
    train_shards = distribute_shards_to_workers(all_train_shards, rank, world_size)
    val_shards = distribute_shards_to_workers(all_val_shards, rank, world_size)
    
    print(f"\n📊 Worker {rank + 1} procesará:")
    print(f"  • {len(train_shards)} train shards")
    print(f"  • {len(val_shards)} validation shards")
    
    if not train_shards:
        raise ValueError(f"Worker {rank} no tiene shards asignados. Verifica la distribución.")
    
    # 2️⃣ Tokenizador
    print("\n📥 Cargando tokenizador...")
    tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)
    
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    tokenizer.padding_side = 'right'
    tokenizer.truncation_side = 'left'
    
    print(f"  ✓ Padding token: {tokenizer.pad_token}")
    print(f"  ✓ EOS token: {tokenizer.eos_token}")
    print(f"  ✓ Padding side: {tokenizer.padding_side}")
    print(f"  ✓ Max length FIJO: {max_length}")
    
    # 3️⃣ Crear datasets con formato tokenizado y padding fijo
    print(f"\n🌊 Creando datasets con padding fijo a {max_length}...")
    
    def debug_generator(gen):
        """Wrapper para debugging del primer ejemplo"""
        first = True
        for item in gen:
            if first:
                print(f"\n🔍 DEBUG: Primer item del generador:")
                print(f"  Tipo: {type(item)}")
                print(f"  Keys: {item.keys() if isinstance(item, dict) else 'No es dict'}")
                if isinstance(item, dict):
                    print(f"  Formato: TOKENIZADO CON PADDING FIJO ✓")
                    print(f"  input_ids length: {len(item.get('input_ids', []))}")
                    print(f"  attention_mask length: {len(item.get('attention_mask', []))}")
                    print(f"  labels length: {len(item.get('labels', []))}")
                first = False
            yield item
    
    train_gen = lambda: debug_generator(
        create_bidirectional_examples_generator(
            train_shards, tokenizer, max_length, chunk_size, True, 42
        )
    )
    
    val_gen = lambda: debug_generator(
        create_bidirectional_examples_generator(
            val_shards, tokenizer, max_length, chunk_size, False, 42
        )
    )
    
    train_dataset = IterableDataset.from_generator(train_gen)
    val_dataset = IterableDataset.from_generator(val_gen)
    
    print(f"  ✓ Datasets creados con padding fijo")
    
    # 4️⃣ Cargar modelo
    print(f"\n🤖 Cargando modelo: {model_path}")
    
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16 if cfg["precision"].get("bf16", True) else torch.float16,
        low_cpu_mem_usage=True,
        device_map=None  # DeepSpeed manejará la distribución
    )
    
    # Habilitar gradient checkpointing
    model.gradient_checkpointing_enable()
    
    print(f"  ✓ Modelo cargado: {sum(p.numel() for p in model.parameters()) / 1e9:.2f}B parámetros")
    print(f"  ✓ Gradient checkpointing: Activado")
    
    # 5️⃣ TrainingArguments
    print(f"\n⚙️  Configurando TrainingArguments...")
    
    training_args = TrainingArguments(
        # Directorio de salida
        output_dir=out_dir,
        
        # Configuración de batch y gradientes
        per_device_train_batch_size=cfg["training"]["per_device_train_batch_size"],
        per_device_eval_batch_size=cfg["training"].get("per_device_eval_batch_size", 8),
        gradient_accumulation_steps=cfg["training"]["gradient_accumulation_steps"],
        
        # Pasos de entrenamiento
        max_steps=cfg["training"]["max_steps"],
        
        # Evaluación
        eval_strategy="steps",
        eval_steps=cfg["training"]["eval_steps"],
        
        # Logging
        logging_dir=os.path.join(out_dir, "logs"),
        logging_steps=cfg["training"]["logging_steps"],
        report_to="tensorboard",
        
        # Guardado de checkpoints
        save_steps=cfg["training"]["save_steps"],
        save_total_limit=cfg["training"].get("save_total_limit", 5),
        save_safetensors=True,
        
        # Optimización
        learning_rate=cfg["training"]["learning_rate"],
        weight_decay=cfg["training"].get("weight_decay", 0.01),
        warmup_steps=cfg["training"].get("warmup_steps", 500),
        lr_scheduler_type=cfg["training"].get("lr_scheduler_type", "cosine"),
        max_grad_norm=1.0,
        optim="adamw_torch",
        
        # Precisión
        bf16=cfg["precision"].get("bf16", True),
        fp16=cfg["precision"].get("fp16", False),
        
        # Gradient checkpointing
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        
        # Configuración de datos
        dataloader_drop_last=True,
        dataloader_num_workers=0,
        dataloader_pin_memory=False,
        
        # Mejor modelo
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        
        # DeepSpeed
        deepspeed=cfg["deepspeed"].get("config_file") if cfg.get("deepspeed") else None,
        
        # Remover métricas no usadas en CausalLM
        disable_tqdm=False,
        prediction_loss_only=True
    )
    
    print(f"  ✓ TrainingArguments configurado")
    
    # 6️⃣ Callbacks
    callbacks = [
        MemoryMonitorCallback(),
        EarlyStoppingCallback(
            early_stopping_patience=cfg["training"].get("early_stopping_patience", 5),
            early_stopping_threshold=cfg["training"].get("early_stopping_threshold", 0.0)
        ),
        TranslationMetricsCallback(tokenizer, all_val_shards, cfg)
    ]
    
    # 7️⃣ Trainer SIN DATA COLLATOR
    print(f"\n🏗️  Inicializando Trainer SIN DATA COLLATOR...")
    
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=None,  # 🔥 SIN DATA COLLATOR
        processing_class=tokenizer,
        callbacks=callbacks
    )
    
    print(f"  ✓ Trainer inicializado")
    print(f"  ✓ Modelo: {sum(p.numel() for p in trainer.model.parameters()) / 1e9:.2f}B parámetros")
    print(f"  ✓ Data Collator: NINGUNO (padding fijo en generador)")
    
    # 8️⃣ Entrenar
    print("\n" + "=" * 80)
    print("🏋️  INICIANDO ENTRENAMIENTO SIN DATA COLLATOR")
    print("=" * 80)
    print(f"  • Max steps: {cfg['training']['max_steps']:,}")
    print(f"  • Padding: FIJO a {max_length} tokens")
    print(f"  • Loss enmascarado: Solo en respuestas (labels=-100 en prompt y padding)")
    print(f"  • Formato: Tokenizado con chat template")
    print("=" * 80 + "\n")
    
    trainer.train(resume_from_checkpoint=resume_from_checkpoint)
    
    # 9️⃣ Guardar modelo
    if rank == 0:
        print("\n💾 Guardando modelo final...")
        trainer.save_model(os.path.join(out_dir, "final_model"))
        tokenizer.save_pretrained(os.path.join(out_dir, "final_model"))
        
        print("\n✅ Entrenamiento completado!")
        print(f"  • Modelo: {out_dir}/final_model")
        print(f"  • TensorBoard: tensorboard --logdir {os.path.join(out_dir, 'logs')}")
    
    torch.cuda.empty_cache()
    gc.collect()


if __name__ == "__main__":
    main()