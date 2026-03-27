import pandas as pd
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm
import os
from datetime import datetime

# Configuración
model_id = "salamandra-translation-legal-7B/checkpoint-600"

input_path = "test.parquet"
output_path = "test_baseline_trained_7B.parquet"

# Configuración de procesamiento
LONG_TEXT_THRESHOLD = 500
BATCH_SIZE = 16  # Ajusta según tu GPU
# DATASET_FRACTION = 0.01  # 1% del dataset

print("Cargando modelo y tokenizador...")
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    device_map="auto",
    dtype=torch.bfloat16
)
model.eval()
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = 'left'  # Importante para generación

print("Cargando dataset...")
df_full = pd.read_parquet(input_path)
df=df_full
# Tomar solo el 1% del dataset
# df = df_full.sample(frac=DATASET_FRACTION, random_state=42).reset_index(drop=True)
# print(f"Dataset reducido a {len(df)} filas ({DATASET_FRACTION*100}% del total)")

def is_long_text(text):
    """Determina si un texto es largo basándose en su longitud."""
    return len(text) > LONG_TEXT_THRESHOLD or '\n' in text

def create_prompt(text, source_lang, target_lang):
    """Crea el prompt apropiado según la longitud del texto."""
    
    if is_long_text(text):
        paragraphs = text.split('\n') if '\n' in text else [text]
        prompt = f"Please translate this text from {source_lang} into {target_lang}.\n"
        prompt += f"{source_lang}: "
        for para in paragraphs:
            prompt += f"{para}\n"
        prompt += f"{target_lang}:"
    else:
        prompt = f"Translate the following text from {source_lang} into {target_lang}.\n"
        prompt += f"{source_lang}: {text}\n"
        prompt += f"{target_lang}:"
    
    message = [ { "role": "user", "content": prompt } ]

    date_string = datetime.today().strftime('%Y-%m-%d')

    prompt = tokenizer.apply_chat_template(
        message,
        tokenize=False,
        add_generation_prompt=True,
        date_string=date_string
    )
    
    return prompt

'''def create_prompt(text, source_lang, target_lang):
    """Crea el prompt apropiado según la longitud del texto."""
    

    prompt = f"Translate the following text from {source_lang} into {target_lang}.\n"
    prompt += f"{source_lang}: {text}\n"
    prompt += f"{target_lang}:"
    
    message = [ { "role": "user", "content": prompt } ]

    date_string = datetime.today().strftime('%Y-%m-%d')

    prompt = tokenizer.apply_chat_template(
        message,
        tokenize=False,
        add_generation_prompt=True,
        date_string=date_string
    )
    
    return prompt'''


def translate_batch(texts, source_lang, target_lang):
    """Traduce un lote de textos."""
    # Filtrar textos vacíos y crear prompts
    valid_indices = []
    prompts = []
    
    for idx, text in enumerate(texts):
        if pd.notna(text) and text != "":
            prompts.append(create_prompt(text, source_lang, target_lang))
            valid_indices.append(idx)
    
    if not prompts:
        return [""] * len(texts)
    
    # print(prompts)
    
    # Tokenizar el lote
    inputs = tokenizer(
        prompts, 
        return_tensors="pt", 
        padding=True, 
        truncation=True,
        max_length=2048
    ).to(model.device)
    
    # print(inputs)
    
    # Generar traducciones
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=1024,
            pad_token_id=tokenizer.eos_token_id
        )
    
    # Decodificar resultados
    translations = [""] * len(texts)
    for idx, valid_idx in enumerate(valid_indices):
        generated_text = tokenizer.decode(outputs[idx], skip_special_tokens=True)
        translation = generated_text.split(f"assistant")[-1].strip()
        translations[valid_idx] = translation
    
    return translations

# Inicializar columnas de predicción
df['text_en_predicted'] = ""
df['text_es_predicted'] = ""

print("\nIniciando traducción por lotes...")

# Traducir de español a inglés
print("\nTraduciendo de español a inglés...")
for i in tqdm(range(0, len(df), BATCH_SIZE), desc="ES -> EN"):
    batch = df.iloc[i:i+BATCH_SIZE]
    try:
        translations = translate_batch(
            batch['text_es'].tolist(),
            "Spanish",
            "English"
        )
        df.loc[i:i+BATCH_SIZE-1, 'text_en_predicted'] = translations
    except Exception as e:
        print(f"\nError en lote {i//BATCH_SIZE}: {e}")
        # Procesar individualmente en caso de error
        for j, row in batch.iterrows():
            try:
                if pd.notna(row['text_es']) and row['text_es'] != "":
                    df.at[j, 'text_en_predicted'] = translate_batch(
                        [row['text_es']], "Spanish", "English"
                    )[0]
            except:
                df.at[j, 'text_en_predicted'] = ""

# Traducir de inglés a español
print("\nTraduciendo de inglés a español...")
for i in tqdm(range(0, len(df), BATCH_SIZE), desc="EN -> ES"):
    batch = df.iloc[i:i+BATCH_SIZE]
    try:
        translations = translate_batch(
            batch['text_en'].tolist(),
            "English",
            "Spanish"
        )
        df.loc[i:i+BATCH_SIZE-1, 'text_es_predicted'] = translations
    except Exception as e:
        print(f"\nError en lote {i//BATCH_SIZE}: {e}")
        # Procesar individualmente en caso de error
        for j, row in batch.iterrows():
            try:
                if pd.notna(row['text_en']) and row['text_en'] != "":
                    df.at[j, 'text_es_predicted'] = translate_batch(
                        [row['text_en']], "English", "Spanish"
                    )[0]
            except:
                df.at[j, 'text_es_predicted'] = ""

# Guardar el resultado
print("\nGuardando resultados...")
df.to_parquet(output_path, index=False)

print(f"\n¡Proceso completado! Archivo guardado en: {output_path}")
print(f"Total de filas procesadas: {len(df)}")
print(f"\nPrimeras filas del resultado:")
print(df[['text_en', 'text_es', 'text_en_predicted', 'text_es_predicted']].head())