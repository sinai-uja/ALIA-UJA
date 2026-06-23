"""
Generador de Respuestas - Un modelo a la vez
Usa OpenAI API para conectar con servidor externo
Ejecutar una vez por cada modelo que quieras usar
"""

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

import openai
import yaml
from openai import AsyncOpenAI
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tqdm.asyncio import tqdm

try:
    from pydantic import BaseModel, Field, ValidationError

    _HAS_PYDANTIC = True
except Exception:
    _HAS_PYDANTIC = False

if _HAS_PYDANTIC:

    class ResponseModel(BaseModel):
        prompt: str
        full_prompt: str
        system_prompt: str | None = Field(None)
        response: str
        model: str
        prompt_id: int
        metadata: dict = Field(default_factory=dict)

from rich.console import Console
from rich.logging import RichHandler

console = Console()


def load_config(config_path: str = "config_responses.yaml") -> dict:
    """Carga la configuración desde el archivo YAML"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def setup_logging(config: dict) -> logging.Logger:
    """Configura el sistema de logging"""
    level = getattr(logging, config["logging"]["level"])
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    return logging.getLogger("generate_responses")


def load_prompts(config: dict) -> list[dict]:
    """Carga los prompts generados por Magpie"""
    input_dir = Path(config["paths"]["input_dir"])
    input_file = config["paths"]["input_file"]
    prompts_path = input_dir / input_file

    if not prompts_path.exists():
        console.print(f"[red]Error: No se encontró: {prompts_path}[/red]")
        console.print("[yellow]Ejecuta primero 'python generate_prompts.py'[/yellow]")
        exit(1)

    prompts = []
    with open(prompts_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                prompts.append(json.loads(line))
    return prompts


def load_model(config: dict) -> AsyncOpenAI:
    """Crea el cliente OpenAI asincrónico"""
    openai_config = config["openai"]
    model_name = config["model"]["name"]

    console.print(f"[yellow]Conectando con servidor OpenAI: {model_name}...[/yellow]")

    client = AsyncOpenAI(
        base_url=openai_config.get("base_url", "http://localhost:8000/v1"),
        api_key=openai_config.get("api_key", "tu-api-key-aqui"),
    )

    console.print(f"[cyan]URL:[/cyan] {openai_config.get('base_url')}")
    console.print(f"[cyan]Modelo:[/cyan] {openai_config.get('model')}")

    enable_thinking = openai_config.get("enable_thinking", True)
    if not enable_thinking:
        console.print("[cyan]Thinking:[/cyan] Deshabilitado (chat_template_kwargs)")

    console.print(f"[green]✓ Cliente OpenAI para {model_name} inicializado[/green]")
    return client


def build_chat_prompt(prompt_data: dict, config: dict) -> str:
    model_config = config["model"]

    system_prefix = model_config.get("chat_template_system_prefix", "")
    user_prefix = model_config.get("chat_template_user_prefix", "")
    assistant_prefix = model_config.get("chat_template_assistant_prefix", "")

    system_prompt = config.get("response_system_prompt", "You are a helpful assistant.")

    user_prompt = prompt_data["prompt"]

    return f"{system_prefix}{system_prompt}{user_prefix}{user_prompt}{assistant_prefix}"


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return text.strip()


async def generate_responses_batch(
    prompts: list[dict],
    client: AsyncOpenAI,
    config: dict,
    logger: logging.Logger,
    batch_size: int,
) -> list[dict]:
    """Genera respuestas para todos los prompts usando OpenAI API (asincrónico)"""

    openai_config = config["openai"]
    generation_config = config["generation"]
    model_config = config["model"]
    model_name = model_config["name"]
    enable_thinking = openai_config.get("enable_thinking", True)

    console.print(f"[cyan]Generando {len(prompts)} respuestas...[/cyan]")

    extra_body = {}
    if not enable_thinking:
        extra_body = {"chat_template_kwargs": {"enable_thinking": False}}

    stop_tokens = model_config.get("stop_tokens", [])
    stop_token_ids = model_config.get("stop_token_ids", [])

    if stop_token_ids:
        extra_body["stop_token_ids"] = stop_token_ids

    valid_results = []
    if batch_size <= 0:
        batch_size = max(1, len(prompts))

    with tqdm(total=len(prompts), desc="Generando respuestas", unit="prompt") as pbar:
        for start in range(0, len(prompts), batch_size):
            batch = prompts[start : start + batch_size]

            tasks = [
                _generate_single_response(
                    client,
                    start + i,
                    prompt_data,
                    config,
                    openai_config,
                    generation_config,
                    model_name,
                    stop_tokens,
                    extra_body,
                    logger,
                )
                for i, prompt_data in enumerate(batch)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)
            batch_results = [r for r in results if isinstance(r, dict)]
            valid_results.extend(batch_results)

            pbar.update(len(batch))

    return valid_results


async def _generate_single_response(
    client: AsyncOpenAI,
    idx: int,
    prompt_data: dict,
    config: dict,
    openai_config: dict,
    generation_config: dict,
    model_name: str,
    stop_tokens: list,
    extra_body: dict,
    logger: logging.Logger,
) -> dict | None:
    """Genera una respuesta individual de forma asincrónica manejando reintentos dinámicos"""

    max_retries = openai_config.get("max_retries", 3)

    try:
        full_prompt = build_chat_prompt(prompt_data, config)

        retryer = AsyncRetrying(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(
                (
                    openai.APIConnectionError,
                    openai.InternalServerError,
                    openai.RateLimitError,
                    openai.APITimeoutError,
                )
            ),
            reraise=True,
        )

        response = None
        async for attempt in retryer:
            with attempt:
                try:
                    response = await client.completions.create(
                        model=openai_config["model"],
                        prompt=full_prompt,
                        temperature=generation_config["temperature"],
                        max_tokens=generation_config["max_tokens"],
                        top_p=generation_config["top_p"],
                        timeout=openai_config.get("timeout", 120),
                        stop=stop_tokens if stop_tokens else None,
                        extra_body=extra_body if extra_body else None,
                    )
                except Exception as e:
                    logger.debug(
                        f"Intento fallido para prompt {idx} (reintentando...): {e}"
                    )
                    raise e

        response_text = strip_thinking(response.choices[0].text)

        metadata = dict(prompt_data.get("metadata", {}))
        if prompt_data.get("category"):
            metadata["category"] = prompt_data["category"]

        result = {
            "prompt": prompt_data["prompt"],
            "full_prompt": full_prompt,
            "system_prompt": config.get("response_system_prompt", ""),
            "response": response_text,
            "model": model_name,
            "prompt_id": prompt_data.get("id", idx),
            "metadata": metadata,
        }

        if _HAS_PYDANTIC:
            try:
                ResponseModel.model_validate(result)
            except ValidationError as ve:
                logger.debug(
                    f"Response validation failed for prompt_id={result.get('prompt_id')}: {ve}"
                )
                result["_validation_error"] = str(ve)

        return result

    except Exception as e:
        logger.error(
            f"Error definitivo generando respuesta para prompt {idx} "
            f"tras varios reintentos: {type(e).__name__} - {e}"
        )
        return None


def save_responses(responses: list[dict], output_path: Path, model_name: str):
    """Guarda las respuestas en formato JSONL"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for resp in responses:
            f.write(json.dumps(resp, ensure_ascii=False) + "\n")

    console.print(
        f"[green]✓ Guardadas {len(responses)} respuestas en: {output_path}[/green]"
    )


def parse_args():
    """Parsea argumentos de línea de comandos"""
    parser = argparse.ArgumentParser(description="Generador de Respuestas")
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="config_responses.yaml",
        help="Ruta al archivo de configuración (default: config_responses.yaml)",
    )
    return parser.parse_args()


async def main():
    """Función principal (asincrónica)"""
    args = parse_args()

    console.print(
        "[bold blue]╔══════════════════════════════════════════════════════════╗[/bold blue]"
    )
    console.print(
        "[bold blue]║        Generador de Respuestas - Un Modelo               ║[/bold blue]"
    )
    console.print(
        "[bold blue]╚══════════════════════════════════════════════════════════╝[/bold blue]\n"
    )

    console.print(f"[cyan]Config:[/cyan] {args.config}")
    config = load_config(args.config)
    logger = setup_logging(config)

    model_name = config["model"]["name"]
    console.print(f"[cyan]Modelo configurado:[/cyan] {model_name}")

    prompts = load_prompts(config)
    processing_cfg = config.get("processing", {})
    cfg_num = processing_cfg.get("num_samples", None)
    if cfg_num is None:
        num_samples = len(prompts)
    else:
        try:
            num_samples = min(len(prompts), int(cfg_num))
        except Exception:
            num_samples = len(prompts)
    prompts = prompts[:num_samples]
    console.print(f"[cyan]Prompts a procesar:[/cyan] {num_samples}\n")

    console.print("[bold cyan]═══ Conectando con Servidor ═══[/bold cyan]\n")
    client = load_model(config)

    console.print("\n[bold cyan]═══ Generando Respuestas ═══[/bold cyan]\n")
    processing_cfg = config.get("processing", {})
    batch_size = processing_cfg.get("batch_size", 64)
    try:
        batch_size = int(batch_size)
    except Exception:
        batch_size = 64

    responses = await generate_responses_batch(
        prompts, client, config, logger, batch_size
    )

    output_dir = Path(config["paths"]["output_dir"])
    configured_name = config["paths"].get(
        "output_file", f"responses_{model_name}.jsonl"
    )
    base = Path(configured_name)
    new_name = f"{base.stem}-{model_name}_{num_samples}{base.suffix}"
    output_path = output_dir / new_name

    save_responses(responses, output_path, model_name)

    console.print(
        "\n[bold green]╔══════════════════════════════════════════════════════════╗[/bold green]"
    )
    console.print(
        "[bold green]║              GENERACIÓN COMPLETADA                        ║[/bold green]"
    )
    console.print(
        "[bold green]╚══════════════════════════════════════════════════════════╝[/bold green]\n"
    )

    console.print(f"[green]✓ Modelo:[/green] {model_name}")
    console.print(f"[green]✓ Respuestas generadas:[/green] {len(responses)}")
    console.print(f"[blue]📁 Archivo:[/blue] {output_path}")
    console.print(
        "\n[dim]Ejecuta este script con otro config para generar respuestas de otro modelo.[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(main())
