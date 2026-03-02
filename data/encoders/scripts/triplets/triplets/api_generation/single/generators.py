"""
Funciones de generación usando OpenAI client (Async) contra servidor vLLM
"""
import json
import time
import re
import asyncio
from typing import List, Dict, Any, Optional
from pathlib import Path
from pydantic import ValidationError
from openai import AsyncOpenAI, OpenAIError
from tqdm import tqdm

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False

from models import QuestionTypes, Selection, QueryWithAnswer
from utils import save_failed_item, write_to_csv, write_to_jsonl


# === THINK TAG STRIPPING ===
def strip_think_tags(text: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()


def repair_and_parse_json(text: str, schema_type: str = "types") -> Optional[Dict]:
    if not text or len(text) < 2:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and schema_type == "types":
            return {"Question_Types": parsed}
        return parsed
    except json.JSONDecodeError:
        pass

    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    else:
        cleaned = text.strip()

    if HAS_JSON_REPAIR:
        try:
            repaired = repair_json(cleaned)
            parsed = json.loads(repaired)
            return parsed
        except Exception:
            pass
            
    return None


async def call_openai_async(
    client: AsyncOpenAI,
    prompt: str,
    config: Dict[str, Any],
    stage: str,
) -> Optional[str]:
    model = config["model"]
    temperature = config.get(f"{stage}_temperature", 0.7)
    top_p = config.get(f"{stage}_top_p", 0.9)
    max_tokens = config.get(f"{stage}_max_tokens", 512)
    timeout = config.get(f"{stage}_timeout", 120)
    enable_thinking = config.get("enable_thinking", False)

    extra_body = {
        "chat_template_kwargs": {"enable_thinking": enable_thinking}
    }
    
    if "gpt-oss-120" in model.lower():
        extra_body["chat_template_assistant_prefix"] = "<|end|>\n<|start|>assistant<|channel|>final<|message|>"

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_body=extra_body,
    )
    
    raw_text = response.choices[0].message.content
    if raw_text:
        raw_text = raw_text.strip()

    if not enable_thinking and raw_text:
        raw_text = strip_think_tags(raw_text)

    return raw_text


# === GENERATORS INDIVIDUALES ===

async def process_single_type_item(
    item: Dict[str, Any],
    client: AsyncOpenAI,
    template: str,
    paths: Dict[str, Path],
    headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
    domain_language: str,
    domain_type: str
):
    real_id = item.get('id', 'N/A')
    
    for attempt in range(max_retries):
        prompt = template.format(
            passage=item['passage'][:2000],
            source=item.get('source_id', 'official bulletin'),
            domain_language=domain_language,
            domain_type=domain_type
        )

        try:
            raw_text = await call_openai_async(client, prompt, config, "types")

            if raw_text is None or len(raw_text) < 2:
                if attempt == max_retries - 1:
                    save_failed_item(item, "types", "Salida vacía o error", paths, raw_text or "", id_column=config.get("id_column", "id_chunk"))
                continue

            json_data = repair_and_parse_json(raw_text, schema_type="types")

            if json_data is None:
                if attempt == max_retries - 1:
                    save_failed_item(item, "types", "No se pudo parsear JSON", paths, raw_text, id_column=config.get("id_column", "id_chunk"))
                continue

            if isinstance(json_data, list):
                json_data = {"Question_Types": json_data}

            try:
                validated = QuestionTypes(**json_data)
                question_types = validated.Question_Types
                item['question_types'] = question_types

                csv_data = {
                    headers[0]: item.get(headers[0], item.get("id_chunk", "")),
                    "id_document": item.get("id_document", ""),
                    "passage": item["passage"],
                    "character": item.get("character", ""),
                    "types": json.dumps(question_types, ensure_ascii=False),
                    "model": model,
                    "source_id": item.get("source_id", "")
                }
                if "types" in paths:
                    write_to_csv(paths["types"], headers, csv_data)
                if "types_jsonl" in paths:
                    write_to_jsonl(paths["types_jsonl"], csv_data)
                return True
                
            except ValidationError as e:
                if attempt == max_retries - 1:
                    save_failed_item(item, "types", str(e), paths, raw_text, id_column=config.get("id_column", "id_chunk"))

        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "types", str(e), paths, raw_text if 'raw_text' in locals() else None, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)
        except OpenAIError:
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "types", str(e), paths, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)
            
    item['error'] = True
    return False


async def process_single_selection_item(
    item: Dict[str, Any],
    client: AsyncOpenAI,
    template: str,
    paths: Dict[str, Path],
    headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int
):
    if 'error' in item: return False
    real_id = item.get('id', 'N/A')

    for attempt in range(max_retries):
        prompt = template.format(
            passage=item['passage'][:2000],
            character=item.get('character', ''),
            question_type='\n'.join(item.get('question_types', []))
        )

        try:
            raw_text = await call_openai_async(client, prompt, config, "selection")
            
            if not raw_text or len(raw_text) < 2:
                if attempt == max_retries - 1:
                    save_failed_item(item, "selection", "Salida vacía", paths, raw_text or "", id_column=config.get("id_column", "id_chunk"))
                continue

            json_data = repair_and_parse_json(raw_text, schema_type="selection")

            if json_data is None:
                if attempt == max_retries - 1:
                    save_failed_item(item, "selection", "No se pudo parsear JSON", paths, raw_text, id_column=config.get("id_column", "id_chunk"))
                continue

            try:
                if not isinstance(json_data, dict):
                    raise ValueError("JSON no es dict")
                    
                validated = Selection(**json_data)
                
                item.update({
                    "selected_character": validated.Character,
                    "question_type": validated.Question_Type,
                    "difficulty": validated.Difficulty,
                })

                csv_data = {
                    headers[0]: item.get(headers[0], item.get("id_chunk", "")),
                    "id_document": item.get("id_document", ""),
                    "passage": item["passage"],
                    "character": item.get("character", ""),
                    "selected_character": validated.Character,
                    "question_type": validated.Question_Type,
                    "difficulty": validated.Difficulty,
                    "selection_model": model,
                    "source_id": item.get("source_id", "")
                }
                if "selections" in paths:
                    write_to_csv(paths["selections"], headers, csv_data)
                if "selections_jsonl" in paths:
                    write_to_jsonl(paths["selections_jsonl"], csv_data)
                return True

            except (ValidationError, ValueError) as e:
                if attempt == max_retries - 1:
                    save_failed_item(item, "selection", str(e), paths, raw_text, id_column=config.get("id_column", "id_chunk"))

        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "selection", str(e), paths, raw_text if 'raw_text' in locals() else None, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)
        except OpenAIError:
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "selection", str(e), paths, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)

    item['error'] = True
    return False


async def process_single_query_item(
    item: Dict[str, Any],
    client: AsyncOpenAI,
    template: str,
    paths: Dict[str, Path],
    headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
    domain_language: str,
    domain_type: str,
    generate_answer: bool
):
    if 'error' in item: return False
    real_id = item.get('id', 'N/A')
    
    from models import QueryOnly, QueryWithAnswer

    for attempt in range(max_retries):
        prompt = template.format(
            passage=item['passage'][:2000],
            character=item.get('selected_character', ''),
            type=item.get('question_type', ''),
            difficulty=item.get('difficulty', ''),
            domain_language=domain_language,
            domain_type=domain_type
        )

        try:
            raw_text = await call_openai_async(client, prompt, config, "query")

            if not raw_text or len(raw_text) < 2:
                if attempt == max_retries - 1:
                    save_failed_item(item, "query", "Salida vacía", paths, raw_text or "", id_column=config.get("id_column", "id_chunk"))
                continue

            json_data = repair_and_parse_json(raw_text, schema_type="query_with_answer")

            if json_data is None:
                if attempt == max_retries - 1:
                    save_failed_item(item, "query", "No se pudo parsear JSON", paths, raw_text, id_column=config.get("id_column", "id_chunk"))
                continue

            try:
                if not isinstance(json_data, dict):
                    raise ValueError("JSON no es dict")

                if generate_answer:
                    validated = QueryWithAnswer(**json_data)
                    item['query'] = validated.query
                    item['answer'] = validated.answer
                    answer_value = validated.answer
                else:
                    validated = QueryOnly(**json_data)
                    item['query'] = validated.query
                    item['answer'] = ""
                    answer_value = ""

                csv_data = {
                    headers[0]: item.get(headers[0], item.get("id_chunk", "")),
                    "id_document": item.get("id_document", ""),
                    "passage": item["passage"],
                    "character": item.get("selected_character", ""),
                    "type": item.get("question_type", ""),
                    "difficulty": item.get("difficulty", ""),
                    "query": validated.query,
                    "answer": answer_value,
                    "query_model": model,
                    "source_id": item.get("source_id", "")
                }
                if "queries" in paths:
                    write_to_csv(paths["queries"], headers, csv_data)
                if "queries_jsonl" in paths:
                    write_to_jsonl(paths["queries_jsonl"], csv_data)
                return True

            except (ValidationError, ValueError) as e:
                if attempt == max_retries - 1:
                    save_failed_item(item, "query", str(e), paths, raw_text, id_column=config.get("id_column", "id_chunk"))

        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "query", str(e), paths, raw_text if 'raw_text' in locals() else None, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)
        except OpenAIError:
            raise
        except Exception as e:
            if attempt == max_retries - 1:
                save_failed_item(item, "query", str(e), paths, id_column=config.get("id_column", "id_chunk"))
            await asyncio.sleep(1)

    item['error'] = True
    return False


# === BACTH ORCHESTRATORS CON TQDM ===

async def generate_types(
    batch: List[Dict[str, Any]],
    client: AsyncOpenAI,
    types_template: str,
    paths: Dict[str, Path],
    types_headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
) -> List[Dict[str, Any]]:
    
    domain_language = config.get("domain_language", "Spanish")
    domain_type = config.get("domain_type", "legal-administrative")

    tasks = [
        process_single_type_item(
            item, client, types_template, paths, types_headers, 
            model, config, max_retries, domain_language, domain_type
        )
        for item in batch
    ]
    
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="  Generando Types", leave=False):
        await f
        
    return batch


async def generate_selections(
    batch: List[Dict[str, Any]],
    client: AsyncOpenAI,
    selection_template: str,
    paths: Dict[str, Path],
    selection_headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
) -> List[Dict[str, Any]]:

    tasks = [
        process_single_selection_item(
            item, client, selection_template, paths, selection_headers,
            model, config, max_retries
        )
        for item in batch if 'error' not in item
    ]
    
    if tasks:
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="  Seleccionando", leave=False):
            await f
    
    return batch


async def generate_queries_with_answers(
    batch: List[Dict[str, Any]],
    client: AsyncOpenAI,
    query_template: str,
    paths: Dict[str, Path],
    query_headers: List[str],
    model: str,
    config: Dict[str, Any],
    max_retries: int,
) -> List[Dict[str, Any]]:

    domain_language = config.get("domain_language", "Spanish")
    domain_type = config.get("domain_type", "legal-administrative")
    generate_answer = config.get("generate_answer", True)

    tasks = [
        process_single_query_item(
            item, client, query_template, paths, query_headers,
            model, config, max_retries, domain_language, domain_type, generate_answer
        )
        for item in batch if 'error' not in item
    ]
    
    if tasks:
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="  Generando Queries", leave=False):
            await f
    
    return batch
