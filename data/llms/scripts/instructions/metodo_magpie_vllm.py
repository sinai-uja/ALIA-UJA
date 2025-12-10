import os
import json
import argparse
from vllm import LLM, SamplingParams
import yaml
from pathlib import Path
import torch
import gc

def read_config():
    dict = {}
    script_dir = Path(__file__).resolve().parent

    CONFIG_FILE = script_dir / "config.yaml"
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    dict["MODEL"] = config["MODEL"]

    dict["OUTPUT_DIR"] = f"{config['OUTPUT_DIR']}{config['MODEL']}"
    dict["MODEL_PATH"] = f"{config['MODEL_PATH']}{config['MODEL']}"
    dict["CONTEXT_PATH"] = config['CONTEXT_PATH']

    dict["DOMAIN"] = config["DOMAIN"]
    dict["DOMINIO_LIMPIO"] = dict["DOMAIN"].replace(" y ", " ").replace(" ", "_")

    prompt_instruction_no_dominio = config["PROMPT_INSTRUCTION"]
    dict["PROMPT_INSTRUCTION"] = prompt_instruction_no_dominio.format(dominio=dict["DOMAIN"])
    prompt_question_no_dominio = config["PROMPT_QUESTION"]
    dict["PROMPT_QUESTION"] = prompt_question_no_dominio.format(dominio=dict["DOMAIN"])
    prompt_context_instruction_no_dominio = config["PROMPT_CONTEXT_INSTRUCTION"]
    dict["PROMPT_CONTEXT_INSTRUCTION"] = prompt_context_instruction_no_dominio.format(dominio=dict["DOMAIN"])
    prompt_context_question_no_dominio = config["PROMPT_CONTEXT_QUESTION"]
    dict["PROMPT_CONTEXT_QUESTION"] = prompt_context_question_no_dominio.format(dominio=dict["DOMAIN"])

    dict["BATCH_SIZE"] = config["BATCH_SIZE"]
    dict["NUM_DOCUMENTS"] = config["NUM_DOCUMENTS"]
    
    return dict


def initialize_model(dict):

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    n_gpus = torch.cuda.device_count()
    print(f"GPUs detectadas por torch: {n_gpus}")

    tensor_parallel_size = min(n_gpus, 4)  # usa hasta 4
    if tensor_parallel_size == 0:
        raise RuntimeError("No se detectaron GPUs disponibles.")



    config_model={}
    # Inicializar modelo con uso de ambas GPUs, depende del modelo
    if dict["MODEL"] == "microsoft/phi-4":
        llm = LLM(
            model=dict["MODEL_PATH"],
            max_model_len=2048,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=0.95
        )

        sampling_params = SamplingParams(
            temperature=0.8,
            max_tokens=1024,
            stop=["<|im_end|>"]
        )

    if dict["MODEL"] == "meta-llama/Llama-3.1-8B-Instruct":
        # Inicializar modelo con uso de ambas GPUs
        llm = LLM(
            model=dict["MODEL_PATH"],
            max_model_len=2048,
            tensor_parallel_size=2  # si tienes 2 GPUs disponibles
        )

        sampling_params = SamplingParams(
            temperature=0.8,
            max_tokens=1024,
            stop=["<|eot_id|>"]
        )

    if dict["MODEL"] == "Qwen/Qwen3-8B-No-reasoning":
        llm = LLM(
            model=dict["MODEL_PATH"],
            max_model_len=2048,
            gpu_memory_utilization=0.95
        )

        sampling_params = SamplingParams(
            temperature=0.8,
            max_tokens=1024,
            stop=["<|im_end|>"]
        )


    config_model["llm"]=llm
    config_model["sampling_params"]=sampling_params

    return config_model


def generar_prompt(model, prompt_base, entradas, config_model, modo="pregunta", contexto=""):
    """
    modo puede ser:
        - "pregunta": entradas vacías, se genera solo a partir del contexto.
        - "respuesta": entradas son preguntas.
        - "contexto": usado si modo="pregunta" y quieres incluir un contexto al usuario.
    """
    prompts = []
 
    if model == "microsoft/phi-4" or model == "Qwen/Qwen3-8B-No-reasoning":
        if modo == "pregunta":
            # Se generan prompts para hacer preguntas a partir del contexto
            for _ in entradas:
                prompts.append(
                    f"<|im_start|>system<|im_sep|>{prompt_base}<|im_end|><|im_start|>user<|im_sep|>{contexto}"
                )
        elif modo == "respuesta":
            for pregunta in entradas:
                prompts.append(
                    f"<|im_start|>system<|im_sep|>{prompt_base}<|im_end|>"
                    f"<|im_start|>user<|im_sep|>{pregunta}<|im_end|>"
                    f"<|im_start|>assistant<|im_sep|>"
                )
        else:
            raise ValueError("Modo no reconocido. Usa 'pregunta' o 'respuesta'.")
        

    elif model == "meta-llama/Llama-3.1-8B-Instruct":
        if modo == "pregunta":
            # Se generan prompts para hacer preguntas a partir del contexto
            for _ in entradas:
                prompts.append(
                    f"<|begin_of_text|>\n<|start_header_id|>system<|end_header_id|>\n{prompt_base}\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>\n{contexto}"
                )
        elif modo == "respuesta":
            for pregunta in entradas:
                prompts.append(
                    f"<|begin_of_text|>\n<|start_header_id|>system<|end_header_id|>\n{prompt_base}\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>\n{pregunta}\n<|eot_id|>\n<|start_header_id|>assistant<|end_header_id|>"
                )
        else:
            raise ValueError("Modo no reconocido. Usa 'pregunta' o 'respuesta'.")
        

    return config_model["llm"].generate(prompts, config_model["sampling_params"])



def generate_row(model ,prompt, config_model, context, batch_actual):

    diccionario_ternas = {}

    # 1. Generar preguntas
    preguntas_outputs = generar_prompt(model, prompt, range(batch_actual), config_model, modo="pregunta", contexto=context)
    preguntas = [
        output.outputs[0].text.strip() if output.outputs else ""
        for output in preguntas_outputs
    ]
    diccionario_ternas["preguntas"] = preguntas

    # 2. Generar respuestas
    respuestas_outputs = generar_prompt(model, prompt, preguntas, config_model, modo="respuesta")
    respuestas = [
        output.outputs[0].text.strip().split("<|im_end|>")[0].strip() if output.outputs else ""
        for output in respuestas_outputs
    ]
    diccionario_ternas["respuestas"] = respuestas


    return diccionario_ternas

    
def guardar_json(diccionario_config, diccionario_ternas, batch_actual, total_generados, prompt, consulta, dicc_contexto=None, añadir_contexto="", dataset_name=""):

    for idx in range(batch_actual):
        pregunta = diccionario_ternas["preguntas"][idx]
        respuesta = diccionario_ternas["respuestas"][idx]
        num = total_generados + idx + 1

        if not pregunta or not respuesta:
            print(f"[{num}] Error: pregunta o respuesta vacía")
            continue

        pregunta = f"{añadir_contexto}{pregunta}"

        #print(f"[{num}] {pregunta} → {respuesta}")

        if dicc_contexto is not None:
            data = {
                "prompt": prompt,
                "question": pregunta,
                "answer": respuesta,
                "model": diccionario_config["MODEL"],
                "source_id": dicc_contexto["source_id"],
                "id_document": dicc_contexto["id_document"],
                "id_chunk": dicc_contexto["id_chunk"],
                "header": dicc_contexto["header"],
                "chunk": dicc_contexto["chunk"],
                "context": dicc_contexto["context"],
                "classification": dicc_contexto["classification"],
                "tokens": dicc_contexto["tokens"],

            }
        else:
            data = {
                "prompt": prompt,
                "question": pregunta,
                "answer": respuesta,
                "model": diccionario_config["MODEL"],
            }

        #Para el output en el config
        output_path = os.path.join(diccionario_config["OUTPUT_DIR"], consulta, f"datos_sinteticos_{diccionario_config['DOMINIO_LIMPIO']}_{dataset_name}.jsonl")
        
        #Para el output como parametro
        #output_path = os.path.join(ruta, consulta, f"datos_sinteticos_{diccionario_config['DOMINIO_LIMPIO']}_{dataset_name}.jsonl")
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")


def main():
    #Leemos el fichero config y lo guardamos en un diccinario
    dict = read_config()

    #Leemos ahora la configuracion del modelo
    config_model = initialize_model(dict)

    total_generados = 0
    os.makedirs(dict["OUTPUT_DIR"], exist_ok=True)

    parser = argparse.ArgumentParser()
    parser.add_argument("--I", action="store_true", help="Usar prompt_instruction")
    parser.add_argument("--Q", action="store_true", help="Usar prompt_question")
    parser.add_argument("--CI", action="store_true", help="Usar prompt_context_instruction")
    parser.add_argument("--CQ", action="store_true", help="Usar prompt_context_question")
    
    #parser.add_argument("--ruta", type=str, required=True, help="Ruta destino/personalizada")
    parser.add_argument("--ruta", type=str, required=False, default=None, help="Ruta destino/personalizada")
    args = parser.parse_args()
    ruta_usuario = args.ruta

    

    if args.I and args.Q:
        raise ValueError("No puedes usar --I y --Q al mismo tiempo.")
    elif args.I:
        print("Se ha optado por la opcion de instrucciones")
        prompt_base = dict["PROMPT_INSTRUCTION"]
        consulta = "instrucciones"

        while total_generados < dict["NUM_DOCUMENTS"]:
            batch_actual = min(dict["BATCH_SIZE"], dict["NUM_DOCUMENTS"] - total_generados)
            context = ""

            lineas_generadas = generate_row(dict["MODEL"], prompt_base, config_model, context, batch_actual)
            guardar_json(dict, lineas_generadas, batch_actual, total_generados, prompt_base, consulta)
            
            total_generados += batch_actual


    elif args.Q:
        print("Se ha optado por la opcion de preguntas")
        prompt_base = dict["PROMPT_QUESTION"]
        consulta = "preguntas"

        while total_generados < dict["NUM_DOCUMENTS"]:
            batch_actual = min(dict["BATCH_SIZE"], dict["NUM_DOCUMENTS"] - total_generados)
            context = ""

            lineas_generadas = generate_row(dict["MODEL"], prompt_base, config_model, context, batch_actual)
            guardar_json(dict, lineas_generadas, batch_actual, total_generados, prompt_base, consulta)
            
            total_generados += batch_actual


    elif args.CI:
        print(f"Se ha optado por la opcion de contextos: {dict["CONTEXT_PATH"]}")
        prompt_base = dict["PROMPT_CONTEXT_INSTRUCTION"]
        consulta = "contextos_INS"

        contexts = []

        #dict["CONTEXT_PATH"]
        #ruta_usuario
        with open(dict["CONTEXT_PATH"], "r", encoding="utf-8") as f:
            for linea in f:
                contexto = json.loads(linea)
                contexts.append(contexto)
        
        for dicc in contexts:
            batch_actual = min(dict["BATCH_SIZE"], dict["NUM_DOCUMENTS"] - total_generados)

            context = dicc["context"]
            context = f"Dado el siguiente contexto: '{context}'\n"

            dataset_name = dicc["source_id"]

            lineas_generadas = generate_row(dict["MODEL"], prompt_base, config_model, context, batch_actual)
            guardar_json(dict, lineas_generadas, batch_actual, total_generados, prompt_base, consulta, dicc, f"Dado el siguiente contexto: {dicc['context']}\n ", dataset_name)
            
            total_generados += batch_actual


    elif args.CQ:
        print(f"Se ha optado por la opcion de contextos: {dict["CONTEXT_PATH"]}")

        prompt_base = dict["PROMPT_CONTEXT_QUESTION"]
        consulta = "contextos_QUE"

        contexts = []
        #dict["CONTEXT_PATH"]
        #ruta_usuario
        with open(dict["CONTEXT_PATH"], "r", encoding="utf-8") as f:
            for linea in f:
                contexto = json.loads(linea)
                contexts.append(contexto)
        
        for dicc in contexts:
            batch_actual = min(dict["BATCH_SIZE"], dict["NUM_DOCUMENTS"] - total_generados)

            context = dicc["context"]
            context = f"Dado el siguiente contexto: '{context}'\n"

            dataset_name = dicc["source_id"]

            lineas_generadas = generate_row(dict["MODEL"], prompt_base, config_model, context, batch_actual)
            guardar_json(dict, lineas_generadas, batch_actual, total_generados, prompt_base, consulta, dicc, f"Dado el siguiente contexto: {dicc['context']}\n ", dataset_name,)
            
            total_generados += batch_actual


    else:
        raise ValueError("Debes usar --I o --Q --ruta ejemplo/de/ruta")

if __name__ == "__main__":
    main()
