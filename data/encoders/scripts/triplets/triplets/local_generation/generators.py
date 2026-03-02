"""
Funciones de generación con VLLM
"""
import json
import time
import signal
import re
from typing import List, Dict, Any, Optional
from pathlib import Path
from pydantic import ValidationError
from vllm import LLM, SamplingParams

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    print("⚠️ json-repair no instalado. Instala con: pip install json-repair")

from models import QuestionTypes, Selection, QueryWithAnswer
from utils import save_failed_item, write_to_csv

# === TIMEOUT HANDLER ===
class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Generación excedió el timeout")

def extract_json_with_regex(text: str, schema_type: str) -> Optional[Dict]:
    """
    Extrae campos usando regex como fallback
    """
    try:
        if schema_type == "types":
            patterns = [
                r'"Question_Types"\s*:\s*\[(.*?)\]',
                r'Question_Types.*?\[(.*?)\]',
                r'\[(["\']\s*.*?["\'],?\s*)+\]'
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
                if match:
                    types_str = match.group(1)
                    types = re.findall(r'["\']([^"\']+)["\']', types_str)
                    if types:
                        return {"Question_Types": types}
        
        elif schema_type == "selection":
            character = re.search(r'"Character"\s*:\s*"([^"]*)"', text, re.IGNORECASE)
            question_type = re.search(r'"Question_Type"\s*:\s*"([^"]*)"', text, re.IGNORECASE)
            difficulty = re.search(r'"Difficulty"\s*:\s*"([^"]*)"', text, re.IGNORECASE)
            
            if character and question_type and difficulty:
                return {
                    "Character": character.group(1),
                    "Question_Type": question_type.group(1),
                    "Difficulty": difficulty.group(1)
                }
        
        elif schema_type == "query_with_answer":
            query = re.search(r'"query"\s*:\s*"([^"]*)"', text, re.IGNORECASE)
            answer = re.search(r'"answer"\s*:\s*"([^"]*)"', text, re.IGNORECASE)
            
            if query and answer:
                return {
                    "query": query.group(1),
                    "answer": answer.group(1)
                }
    
    except Exception as e:
        print(f"  [REGEX FALLBACK ERROR] {e}")
    
    return None

def repair_and_parse_json(text: str, schema_type: str = "types") -> Optional[Dict]:
    """
    Intenta reparar y parsear JSON con múltiples estrategias
    """
    if not text or len(text) < 2:
        return None
    
    # === ESTRATEGIA 1: Parseo directo ===
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and schema_type == "types":
            return {"Question_Types": parsed}
        return parsed
    except json.JSONDecodeError:
        pass
    
    # === ESTRATEGIA 2: Limpieza básica ===
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    else:
        cleaned = text.strip()
    
    # === ESTRATEGIA 3: json-repair library ===
    if HAS_JSON_REPAIR:
        try:
            repaired = repair_json(cleaned)
            parsed = json.loads(repaired)
            print(f"  ✅ JSON reparado con json-repair")
            return parsed
        except Exception:
            pass
    
    # === ESTRATEGIA 4: Regex fallback ===
    regex_result = extract_json_with_regex(text, schema_type)
    if regex_result:
        print(f"  ✅ Datos extraídos con regex")
        return regex_result
    
    return None

def generate_with_timeout(
    llm: LLM,
    prompts: List[str],
    sampling_params: SamplingParams,
    timeout_seconds: int = 180
) -> Optional[List]:
    """
    Genera con timeout usando SamplingParams
    """
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        start_time = time.time()
        outputs = llm.generate(prompts, sampling_params=sampling_params)
        elapsed = time.time() - start_time
        signal.alarm(0)
        print(f"⏱️ Generación completada en {elapsed:.2f}s ({len(prompts)} prompts)")
        return outputs
    
    except TimeoutException:
        signal.alarm(0)
        print(f"⚠️ TIMEOUT después de {timeout_seconds}s para {len(prompts)} prompts")
        return None
    
    except Exception as e:
        signal.alarm(0)
        print(f"❌ Error durante generación: {e}")
        raise e

def generate_types(
    batch: List[Dict[str, Any]],
    llm: LLM,
    sampling_params: SamplingParams,
    types_template: str,
    paths: Dict[str, Path],
    types_headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
    timeout_seconds: int = 180
) -> List[Dict[str, Any]]:
    """
    Genera tipos con auto-reparación de JSON
    """
    type_items = [item for item in batch if 'error' not in item]
    success_flags = [False] * len(type_items)
    
    # Obtener parámetros del dominio desde config
    domain_language = config.get("domain_language", "Spanish")
    domain_type = config.get("domain_type", "legal-administrative")
    
    for attempt in range(max_retries):
        to_generate_indices = [i for i, s in enumerate(success_flags) if not s]
        if not to_generate_indices:
            break
        
        prompts = [
            types_template.format(
                passage=type_items[i]['passage'][:2000],
                source=type_items[i].get('source_id', 'official bulletin'),
                domain_language=domain_language,
                domain_type=domain_type
            )
            for i in to_generate_indices
        ]
        
        try:
            print(f"[TYPES] Generando {len(prompts)} items | Intento {attempt + 1}/{max_retries}")
            outputs = generate_with_timeout(llm, prompts, sampling_params, timeout_seconds)
            
            if outputs is None:
                for idx_item in to_generate_indices:
                    save_failed_item(type_items[idx_item], "types", "Timeout", paths)
                time.sleep(5)
                continue
            
            for out_idx, idx_item in enumerate(to_generate_indices):
                real_id = type_items[idx_item].get('id', 'N/A')
                raw_text = outputs[out_idx].outputs[0].text.strip()
                
                if not raw_text or len(raw_text) < 2:
                    save_failed_item(type_items[idx_item], "types", "Salida vacía", paths, raw_text)
                    continue
                
                json_data = repair_and_parse_json(raw_text, schema_type="types")
                
                if json_data is None:
                    save_failed_item(type_items[idx_item], "types", "No se pudo parsear JSON", paths, raw_text)
                    continue
                
                try:
                    if isinstance(json_data, list):
                        json_data = {"Question_Types": json_data}
                    
                    validated = QuestionTypes(**json_data)
                    question_types = validated.Question_Types
                    type_items[idx_item]['question_types'] = question_types
                    
                    write_to_csv(
                        paths["types"],
                        types_headers,
                        {
                            "id_chunk": type_items[idx_item].get("id_chunk", ""),
                            "id_document": type_items[idx_item].get("id_document", ""),
                            "passage": type_items[idx_item]["passage"],
                            "character": type_items[idx_item].get("character", ""),
                            "types": json.dumps(question_types, ensure_ascii=False),
                            "model": model,
                            "source_id": type_items[idx_item].get("source_id", "")
                        }
                    )
                    
                    success_flags[idx_item] = True
                    print(f"[TYPES SUCCESS] ID {real_id} | {len(question_types)} tipos")
                
                except ValidationError as e:
                    save_failed_item(type_items[idx_item], "types", str(e), paths, raw_text)
        
        except Exception as e_outer:
            print(f"[TYPES ERROR GLOBAL] {e_outer}")
            time.sleep(3)
        
        if all(success_flags):
            break
        
        if attempt < max_retries - 1 and not all(success_flags):
            time.sleep(2)
    
    for i, success in enumerate(success_flags):
        if not success:
            type_items[i]['error'] = True
            save_failed_item(type_items[i], "types", "Agotados intentos", paths)
    
    return batch

def generate_selections(
    batch: List[Dict[str, Any]],
    llm: LLM,
    sampling_params: SamplingParams,
    selection_template: str,
    paths: Dict[str, Path],
    selection_headers: List[str],
    model: str,
    max_retries: int,
    timeout_seconds: int = 180
) -> List[Dict[str, Any]]:
    """
    Genera selecciones con auto-reparación y validación robusta
    """
    selection_items = [item for item in batch if 'error' not in item]
    success_flags = [False] * len(selection_items)
    
    for attempt in range(max_retries):
        to_generate_indices = [i for i, s in enumerate(success_flags) if not s]
        if not to_generate_indices:
            break
        
        prompts = [
            selection_template.format(
                passage=selection_items[i]['passage'][:2000],
                character=selection_items[i].get('character', ''),
                question_type='\n'.join(selection_items[i].get('question_types', []))
            )
            for i in to_generate_indices
        ]
        
        try:
            print(f"[SELECTION] Generando {len(prompts)} items | Intento {attempt + 1}/{max_retries}")
            outputs = generate_with_timeout(llm, prompts, sampling_params, timeout_seconds)
            
            if outputs is None:
                for idx_item in to_generate_indices:
                    save_failed_item(selection_items[idx_item], "selection", "Timeout", paths)
                time.sleep(5)
                continue
            
            for out_idx, sel_idx in enumerate(to_generate_indices):
                real_id = selection_items[sel_idx].get('id', 'N/A')
                raw_text = outputs[out_idx].outputs[0].text.strip()
                print(f"\n[SELECTION] ID {real_id} | Len: {len(raw_text)}")
                
                if not raw_text or len(raw_text) < 2:
                    error_msg = "Salida vacía"
                    print(f"  ❌ {error_msg}")
                    save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                    continue
                
                json_data = repair_and_parse_json(raw_text, schema_type="selection")
                
                if json_data is None:
                    error_msg = "No se pudo reparar JSON"
                    print(f"  ❌ {error_msg}")
                    print(f"  Raw (primeros 300 chars): {raw_text[:300]}")
                    save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                    continue
                
                print(f"  📋 Tipo de json_data: {type(json_data)}")
                print(f"  📋 Contenido: {json_data}")
                
                try:
                    if isinstance(json_data, list):
                        error_msg = "Selection devolvió lista en lugar de diccionario"
                        print(f"  ❌ {error_msg}")
                        save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                        continue
                    
                    if not isinstance(json_data, dict):
                        error_msg = f"Selection no es diccionario: {type(json_data).__name__}"
                        print(f"  ❌ {error_msg}")
                        save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                        continue
                    
                    required_fields = ["Character", "Question_Type", "Difficulty"]
                    missing_fields = [f for f in required_fields if f not in json_data or not json_data[f]]
                    
                    if missing_fields:
                        error_msg = f"Faltan campos requeridos: {', '.join(missing_fields)}"
                        print(f"  ❌ {error_msg}")
                        print(f"  Campos presentes: {list(json_data.keys())}")
                        save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                        continue
                    
                    validated = Selection(**json_data)
                    
                    selection_items[sel_idx].update({
                        "selected_character": validated.Character,
                        "question_type": validated.Question_Type,
                        "difficulty": validated.Difficulty,
                    })
                    
                    write_to_csv(
                        paths["selections"],
                        selection_headers,
                        {
                            "id_chunk": selection_items[sel_idx].get("id_chunk", ""),
                            "id_document": selection_items[sel_idx].get("id_document", ""),
                            "passage": selection_items[sel_idx]["passage"],
                            "character": selection_items[sel_idx].get("character", ""),
                            "selected_character": validated.Character,
                            "question_type": validated.Question_Type,
                            "difficulty": validated.Difficulty,
                            "selection_model": model,
                            "source_id": selection_items[sel_idx].get("source_id", "")
                        }
                    )
                    
                    success_flags[sel_idx] = True
                    print(f"  ✅ SUCCESS")
                
                except ValidationError as e:
                    error_msg = f"ValidationError: {str(e)}"
                    print(f"  ❌ {error_msg}")
                    print(f"  JSON data: {json_data}")
                    save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
                
                except Exception as e:
                    error_msg = f"Error inesperado: {type(e).__name__}: {str(e)}"
                    print(f"  ❌ {error_msg}")
                    save_failed_item(selection_items[sel_idx], "selection", error_msg, paths, raw_text)
        
        except Exception as e_outer:
            print(f"[SELECTION ERROR GLOBAL] {e_outer}")
            import traceback
            traceback.print_exc()
            time.sleep(3)
        
        if all(success_flags):
            break
        
        if attempt < max_retries - 1:
            time.sleep(2)
    
    for i, success in enumerate(success_flags):
        if not success:
            selection_items[i]['error'] = True
            save_failed_item(selection_items[i], "selection", "Agotados intentos", paths)
    
    return batch

def generate_queries_with_answers(
    batch: List[Dict[str, Any]],
    llm: LLM,
    sampling_params: SamplingParams,
    query_template: str,
    paths: Dict[str, Path],
    query_headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
    timeout_seconds: int = 180
) -> List[Dict[str, Any]]:
    """
    Genera queries con o sin respuestas según configuración
    """
    from models import QueryOnly, QueryWithAnswer
    
    query_items = [item for item in batch if 'error' not in item]
    success_flags = [False] * len(query_items)
    
    # Determinar si se genera answer
    generate_answer = config.get("generate_answer", True)
    
    # Obtener parámetros del dominio
    domain_language = config.get("domain_language", "Spanish")
    domain_type = config.get("domain_type", "legal-administrative")
    
    for attempt in range(max_retries):
        to_generate_indices = [i for i, s in enumerate(success_flags) if not s]
        if not to_generate_indices:
            break
        
        prompts = [
            query_template.format(
                passage=query_items[i]['passage'][:2000],
                character=query_items[i].get('selected_character', ''),
                type=query_items[i].get('question_type', ''),
                difficulty=query_items[i].get('difficulty', ''),
                domain_language=domain_language,
                domain_type=domain_type
            )
            for i in to_generate_indices
        ]
        
        try:
            mode_str = "QUERY+ANSWER" if generate_answer else "QUERY"
            print(f"[{mode_str}] Generando {len(prompts)} items | Intento {attempt + 1}/{max_retries}")
            
            outputs = generate_with_timeout(llm, prompts, sampling_params, timeout_seconds)
            
            if outputs is None:
                for idx_item in to_generate_indices:
                    save_failed_item(query_items[idx_item], "query", "Timeout", paths)
                time.sleep(5)
                continue
            
            for out_idx, q_idx in enumerate(to_generate_indices):
                real_id = query_items[q_idx].get('id', 'N/A')
                raw_text = outputs[out_idx].outputs[0].text.strip()
                
                if not raw_text or len(raw_text) < 2:
                    save_failed_item(query_items[q_idx], "query", "Salida vacía", paths, raw_text)
                    continue
                
                json_data = repair_and_parse_json(raw_text, schema_type="query_with_answer")
                
                if json_data is None:
                    save_failed_item(query_items[q_idx], "query", "No se pudo reparar JSON", paths, raw_text)
                    continue
                
                try:
                    if isinstance(json_data, list):
                        save_failed_item(query_items[q_idx], "query", "Query devolvió lista", paths, raw_text)
                        continue
                    
                    if not isinstance(json_data, dict):
                        save_failed_item(query_items[q_idx], "query", f"Tipo inválido: {type(json_data)}", paths, raw_text)
                        continue
                    
                    # Verificar campo query (siempre requerido)
                    if "query" not in json_data or not json_data["query"]:
                        save_failed_item(query_items[q_idx], "query", "Falta campo 'query'", paths, raw_text)
                        continue
                    
                    # Validar según modo
                    if generate_answer:
                        if "answer" not in json_data or not json_data["answer"]:
                            save_failed_item(query_items[q_idx], "query", "Falta campo 'answer'", paths, raw_text)
                            continue
                        validated = QueryWithAnswer(**json_data)
                        query_items[q_idx]['query'] = validated.query
                        query_items[q_idx]['answer'] = validated.answer
                        answer_value = validated.answer
                    else:
                        validated = QueryOnly(**json_data)
                        query_items[q_idx]['query'] = validated.query
                        query_items[q_idx]['answer'] = ""  # Campo vacío
                        answer_value = ""
                    
                    # Escribir CSV
                    write_to_csv(
                        paths["queries"],
                        query_headers,
                        {
                            "id_chunk": query_items[q_idx].get("id_chunk", ""),
                            "id_document": query_items[q_idx].get("id_document", ""),
                            "passage": query_items[q_idx]["passage"],
                            "character": query_items[q_idx].get("selected_character", ""),
                            "type": query_items[q_idx].get("question_type", ""),
                            "difficulty": query_items[q_idx].get("difficulty", ""),
                            "query": validated.query,
                            "answer": answer_value,
                            "query_model": model,
                            "source_id": query_items[q_idx].get("source_id", "")
                        }
                    )
                    
                    success_flags[q_idx] = True
                    print(f"[{mode_str} SUCCESS] ID {real_id}")
                    
                except ValidationError as e:
                    save_failed_item(query_items[q_idx], "query", str(e), paths, raw_text)
                    
        except Exception as e_outer:
            print(f"[{mode_str} ERROR GLOBAL] {e_outer}")
            time.sleep(3)
        
        if all(success_flags):
            break
        
        if attempt < max_retries - 1:
            time.sleep(2)
    
    for i, success in enumerate(success_flags):
        if not success:
            query_items[i]['error'] = True
            save_failed_item(query_items[i], "query", "Agotados intentos", paths)
    
    return batch