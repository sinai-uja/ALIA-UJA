"""
LLM as a Judge - OpenAI-compatible API
Compara respuestas generadas por múltiples modelos y crea dataset DPO
Reanudación, reintentos y configuración de reasoning vía YAML.
"""

import argparse
import json
import logging
import random
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

import yaml
from openai import AsyncOpenAI, APIConnectionError, APIStatusError, RateLimitError
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.prompt import Prompt

console = Console()


@dataclass
class DPOSample:
    """Estructura de un sample DPO"""
    prompt_id: Any
    prompt: str
    chosen: str
    rejected: str
    model_chosen: str
    model_rejected: str
    judge_reason: str
    confidence: int
    judge_reasoning: str = ""  # opcional: cadena de razonamiento del juez


class OpenAIClient:
    """Cliente para APIs compatibles con OpenAI (incluye compatibilidad con reasoning_content)"""

    def __init__(self, config: dict):
        self.base_url = config["openai"]["base_url"]
        self.api_key = config["openai"]["api_key"]
        self.timeout = config["openai"].get("timeout", 120)
        self.max_retries = config["openai"].get("max_retries", 5)
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )
        self.config = config

    async def get_models(self) -> list[str]:
        """Obtiene lista de modelos disponibles"""
        models_response = await self.client.models.list()
        return [model.id for model in models_response.data]

    async def chat(
        self, model: str, message: str, temperature: float, max_tokens: int
    ) -> tuple[str, str]:
        """
        Envía un mensaje al modelo.
        Devuelve tupla: (content, reasoning_content)
        """
        max_retries = self.config.get("openai", {}).get("max_retries", 5)
        retry_delay = self.config.get("openai", {}).get("retry_delay", 10)

        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": message}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if response.choices:
                    message_data = response.choices[0].message
                    content = getattr(message_data, "content", "") or ""
                    # Algunos proveedores compatibles con OpenAI exponen
                    # reasoning_content en atributos adicionales (p.ej. Kimi-K2)
                    reasoning = (
                        getattr(message_data, "reasoning_content", None)
                        or ""
                    )
                    return content, reasoning

                return "", ""

            except (APIConnectionError, APIStatusError, RateLimitError) as e:
                console.print(
                    f"\n[yellow]⚠ Error API: {e}. "
                    f"Intento {attempt + 1}/{max_retries}. Esperando {retry_delay}s...[/yellow]"
                )
                time.sleep(retry_delay)
                continue

            except Exception as e:
                console.print(
                    f"\n[red]✗ Error inesperado: {e}[/red]"
                )
                return "", ""

        console.print(
            f"\n[red]✗ Se agotaron los {max_retries} intentos. Saltando sample.[/red]"
        )
        return "", ""


def load_config(config_path: str = "config_judge.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> logging.Logger:
    level = getattr(logging, config["logging"]["level"])
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    return logging.getLogger("llm_judge")


def read_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_two_datasets(
    config: dict,
) -> tuple[list[dict], dict[Any, dict], dict[Any, dict]]:
    model_a_file = Path(config["paths"]["model_a_file"])
    model_b_file = Path(config["paths"]["model_b_file"])

    if not model_a_file.exists():
        console.print(f"[red]Error: model_a_file no encontrado: {model_a_file}[/red]")
        exit(1)
    if not model_b_file.exists():
        console.print(f"[red]Error: model_b_file no encontrado: {model_b_file}[/red]")
        exit(1)

    console.print(f"[cyan]Modelo A:[/cyan] {model_a_file.name}")
    console.print(f"[cyan]Modelo B:[/cyan] {model_b_file.name}")

    prompts_map: dict[Any, dict] = {}
    responses_a: dict[Any, dict] = {}
    responses_b: dict[Any, dict] = {}

    def register_prompt(pid: Any, data: dict):
        if pid not in prompts_map:
            prompts_map[pid] = {
                "id": pid,
                "prompt": data.get("prompt", ""),
                "category": data.get("metadata", {}).get("category", "")
                or data.get("category", ""),
                "system_prompt": data.get("system_prompt", ""),
                "full_prompt": data.get("full_prompt", ""),
            }

    for data in read_jsonl(model_a_file):
        pid = data.get("prompt_id", hash(data.get("prompt", "")))
        data["prompt_id"] = pid
        register_prompt(pid, data)
        responses_a[pid] = data

    for data in read_jsonl(model_b_file):
        pid = data.get("prompt_id", hash(data.get("prompt", "")))
        data["prompt_id"] = pid
        register_prompt(pid, data)
        responses_b[pid] = data

    return list(prompts_map.values()), responses_a, responses_b


async def select_model(client: OpenAIClient, config: dict) -> str:
    if config["judge"].get("model"):
        return config["judge"]["model"]

    models = await client.get_models()
    if not models:
        console.print("[red]No hay modelos disponibles[/red]")
        exit(1)

    console.print("\n[cyan]Modelos disponibles:[/cyan]")
    for i, model in enumerate(models, 1):
        console.print(f"  {i}: {model}")

    while True:
        choice = Prompt.ask("\nSelecciona el modelo juez (número)")
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            selected = models[int(choice) - 1]
            console.print(f"[green]✓ Modelo seleccionado: {selected}[/green]")
            return selected
        console.print("[red]Opción inválida[/red]")


def parse_judge_response(eval_text: str, reasoning_text: str = "") -> dict:
    result = {
        "winner": None,
        "confidence": 0,
        "reason": "Could not parse",
        "reasoning_content": reasoning_text,
    }

    try:
        start = eval_text.find("{")
        end = eval_text.rfind("}") + 1
        if start != -1 and end > start:
            parsed_json = json.loads(eval_text[start:end])
            result.update(parsed_json)
            return result
    except json.JSONDecodeError:
        pass

    if '"winner": "A"' in eval_text or "Respuesta A" in eval_text:
        result.update(
            {"winner": "A", "confidence": 5, "reason": "Parsed from text fallback"}
        )
    elif '"winner": "B"' in eval_text or "Respuesta B" in eval_text:
        result.update(
            {"winner": "B", "confidence": 5, "reason": "Parsed from text fallback"}
        )

    return result


async def judge_responses(
    client: OpenAIClient,
    model: str,
    prompt_data: dict,
    response_a: dict,
    response_b: dict,
    config: dict,
) -> dict:
    template = config["templates"]["judge"]

    fmt_ctx = {
        "prompt": prompt_data.get("prompt", ""),
        "category": prompt_data.get("category", ""),
        "system_prompt": prompt_data.get("system_prompt", ""),
        "full_prompt_a": response_a.get("full_prompt", ""),
        "full_prompt_b": response_b.get("full_prompt", ""),
        "response_a": response_a.get("response", ""),
        "response_b": response_b.get("response", ""),
        "model_a": response_a.get("model", "A"),
        "model_b": response_b.get("model", "B"),
    }

    try:
        formatted = template.format_map(fmt_ctx)
    except Exception:
        formatted = template.format(**fmt_ctx)

    temp = config["judge"].get("temperature", 0.1)
    max_toks = config["judge"].get("max_tokens", 4096)

    content_text, reasoning_text = await client.chat(
        model=model,
        message=formatted,
        temperature=temp,
        max_tokens=max_toks,
    )

    enable_reasoning = config.get("processing", {}).get("enable_reasoning", True)

    if not enable_reasoning:
        eval_text = content_text
        reasoning_used = ""
    else:
        eval_text = content_text if content_text else reasoning_text
        reasoning_used = reasoning_text

    if not eval_text:
        return {
            "winner": None,
            "confidence": 0,
            "reason": "Respuesta vacía",
            "reasoning_content": reasoning_used,
        }

    return parse_judge_response(eval_text, reasoning_used)


async def generate_dpo_sample_direct(
    prompt_data: dict,
    response_a: dict,
    response_b: dict,
    client: OpenAIClient,
    judge_model: str,
    config: dict,
    logger: logging.Logger,
) -> Optional[DPOSample]:
    try:
        if random.random() > 0.5:
            response_a, response_b = response_b, response_a

        judgment = await judge_responses(
            client, judge_model, prompt_data, response_a, response_b, config
        )

        min_conf = config.get("quality_control", {}).get("min_confidence_score", 0)

        try:
            conf = float(judgment.get("confidence", 0))
        except (ValueError, TypeError):
            conf = 0.0

        if conf < float(min_conf):
            logger.debug(f"Descartado por baja confianza: {conf}")
            return None

        if (
            config.get("quality_control", {}).get("filter_ties", False)
            and judgment.get("winner") is None
        ):
            logger.debug("Descartado por empate o error")
            return None

        winner = judgment.get("winner")
        if winner == "A":
            chosen_resp, rejected_resp = response_a, response_b
        elif winner == "B":
            chosen_resp, rejected_resp = response_b, response_a
        else:
            return None

        return DPOSample(
            prompt_id=prompt_data.get("id"),
            prompt=prompt_data.get("prompt", ""),
            chosen=chosen_resp.get("response", ""),
            rejected=rejected_resp.get("response", ""),
            model_chosen=chosen_resp.get("model", ""),
            model_rejected=rejected_resp.get("model", ""),
            judge_reason=judgment.get("reason", ""),
            confidence=int(conf),
            judge_reasoning=judgment.get("reasoning_content", ""),
        )

    except Exception as e:
        logger.error(f"Error generando sample: {e}")
        return None


def save_sample(sample: DPOSample, output_path: Path, config: dict):
    data = {
        "prompt_id": sample.prompt_id,
        "prompt": sample.prompt,
        "chosen": sample.chosen,
        "rejected": sample.rejected,
        "metadata": {
            "model_chosen": sample.model_chosen,
            "model_rejected": sample.model_rejected,
            "judge_reason": sample.judge_reason,
            "confidence": sample.confidence,
        },
    }

    if config.get("processing", {}).get("save_reasoning", False):
        data["metadata"]["judge_reasoning"] = sample.judge_reasoning

    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def load_existing_progress(output_path: Path) -> tuple[int, dict[str, int], set[Any]]:
    successful = 0
    model_wins: dict[str, int] = {}
    processed_prompts: set[Any] = set()

    if not output_path.exists():
        return successful, model_wins, processed_prompts

    console.print(
        f"[yellow]⚠ Archivo encontrado: {output_path}. Recuperando progreso...[/yellow]"
    )

    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            p_id = data.get("prompt_id")
            p_text = data.get("prompt", "")
            if p_id is not None:
                processed_prompts.add(p_id)
            elif p_text:
                processed_prompts.add(p_text)

            successful += 1
            model_chosen = data.get("metadata", {}).get("model_chosen")
            if model_chosen:
                model_wins[model_chosen] = model_wins.get(model_chosen, 0) + 1

    console.print(
        f"[green]✓ {len(processed_prompts)} samples ya generados recuperados.[/green]"
    )
    return successful, model_wins, processed_prompts


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str, default="config_judge.yaml")
    return parser.parse_args()


def print_summary(successful: int, failed: int, output_path: Path, model_wins: dict):
    console.print(
        "\n[bold green]╔══════════════════════════════════════════════════════════╗[/bold green]"
    )
    console.print(
        "[bold green]║              GENERACIÓN COMPLETADA                        ║[/bold green]"
    )
    console.print(
        "[bold green]╚══════════════════════════════════════════════════════════╝[/bold green]\n"
    )

    console.print(f"[green]✓ Samples exitosos (totales):[/green] {successful}")
    console.print(f"[red]✗ Samples fallidos (sesión actual):[/red] {failed}")
    console.print(f"[blue]📁 Dataset guardado en:[/blue] {output_path}\n")

    if model_wins:
        table = Table(title="Victorias por Modelo (chosen)")
        table.add_column("Modelo", style="cyan")
        table.add_column("Victorias", justify="right", style="green")
        table.add_column("Porcentaje", justify="right", style="yellow")

        for model, wins in sorted(model_wins.items(), key=lambda x: -x[1]):
            pct = (wins / successful * 100) if successful > 0 else 0
            table.add_row(model, str(wins), f"{pct:.1f}%")

        console.print(table)


async def main():
    args = parse_args()

    console.print(
        "[bold blue]╔══════════════════════════════════════════════════════════╗[/bold blue]"
    )
    console.print(
        "[bold blue]║     LLM as a Judge - OpenAI-compatible API              ║[/bold blue]"
    )
    console.print(
        "[bold blue]╚══════════════════════════════════════════════════════════╝[/bold blue]\n"
    )

    console.print(
        "[yellow]⚠ Recuerda ejecutar: unset https_proxy (si aplica)[/yellow]\n"
    )

    config = load_config(args.config)
    logger = setup_logging(config)

    console.print("[bold cyan]═══ Inicializando cliente OpenAI ═══[/bold cyan]\n")
    client = OpenAIClient(config)
    judge_model = await select_model(client, config)

    console.print("\n[bold cyan]═══ Cargando Datos ═══[/bold cyan]\n")
    prompts, responses_a, responses_b = load_two_datasets(config)

    valid_prompts = [
        p for p in prompts if p["id"] in responses_a and p["id"] in responses_b
    ]

    output_dir = Path(config["paths"]["output_dir"])
    output_file = config["paths"]["output_file"]
    output_path = output_dir / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)

    failed = 0
    successful, model_wins, processed_prompts = load_existing_progress(output_path)

    remaining_prompts = [
        p
        for p in valid_prompts
        if p["id"] not in processed_prompts and p["prompt"] not in processed_prompts
    ]

    target_num_samples = config["processing"]["num_samples"]
    samples_to_generate = min(len(remaining_prompts), target_num_samples - successful)

    console.print(f"[cyan]Prompts válidos (en ambos):[/cyan] {len(valid_prompts)}")
    console.print(
        f"[cyan]Nuevos samples a evaluar hoy:[/cyan] {samples_to_generate}\n"
    )

    if samples_to_generate <= 0:
        console.print(
            "[green]El objetivo de samples ya se ha alcanzado con el archivo actual.[/green]"
        )
        print_summary(successful, failed, output_path, model_wins)
        return

    delay = config["processing"].get("delay_between_requests", 0.5)

    console.print("[bold cyan]═══ Generando Pares DPO ═══[/bold cyan]\n")

    with tqdm(total=samples_to_generate, desc="Evaluando respuestas") as pbar:
        for prompt_data in remaining_prompts[:samples_to_generate]:
            prompt_id = prompt_data["id"]
            response_a = responses_a[prompt_id]
            response_b = responses_b[prompt_id]

            sample = await generate_dpo_sample_direct(
                prompt_data,
                response_a,
                response_b,
                client,
                judge_model,
                config,
                logger,
            )

            if sample:
                save_sample(sample, output_path, config)
                successful += 1
                model_wins[sample.model_chosen] = (
                    model_wins.get(sample.model_chosen, 0) + 1
                )
            else:
                failed += 1

            pbar.update(1)
            pbar.set_postfix({"✓": successful, "✗": failed})
            time.sleep(delay)

    print_summary(successful, failed, output_path, model_wins)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())