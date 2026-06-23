"""
Magpie - Generación de Prompts usando OpenAI API

La técnica Magpie genera prompts sintéticos dando al modelo SOLO
el prefijo del template de chat (ej: "<|user|>") y dejando que
complete lo que un usuario diría naturalmente.

Con system_prompt habilitado, se guía al modelo para generar
prompts adversariales (sesgos, insultos, jailbreaks, etc.)
"""

import argparse
import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from openai import AsyncOpenAI

try:
    from pydantic import BaseModel, Field, ValidationError

    _HAS_PYDANTIC = True
except Exception:
    _HAS_PYDANTIC = False

if _HAS_PYDANTIC:

    class PromptModel(BaseModel):
        id: int
        prompt: str
        source: str
        timestamp: str
        category: str | None = Field(None)
        system_prompt: str | None = Field(None)


from tqdm import tqdm
from rich.console import Console
from rich.logging import RichHandler

console = Console()


def load_config(config_path: str = "config_magpie.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> logging.Logger:
    level = getattr(logging, config["logging"]["level"])
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )
    return logging.getLogger("magpie")


def get_categories(config: dict) -> list[dict]:
    system_config = config.get("system_prompt", {})
    if not system_config.get("enabled", False):
        return []
    return system_config.get("categories", [])


def build_magpie_prefix(
    config: dict,
    category: dict = None,
) -> str:
    system_config = config.get("system_prompt", {})
    use_system = system_config.get("enabled", False)

    system_prefix = config["model"].get("chat_template_system_prefix", "")
    user_prefix = config["model"]["chat_template_user_prefix"]

    if not use_system or not category:
        return user_prefix

    base = system_config.get("base", "").strip()
    instruction = category.get("instruction", "").strip()
    full_system = f"{base}\n\n{instruction}"
    return f"{system_prefix}{full_system}{user_prefix}"


def build_system_prompt_text(
    config: dict,
    category: dict = None,
) -> str | None:
    system_config = config.get("system_prompt", {})
    if not system_config.get("enabled", False):
        return None

    base = system_config.get("base", "").strip()

    if category:
        instruction = category.get("instruction", "").strip()
        return f"{base}\n\n{instruction}"

    return base


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)
    return text.strip()


def clean_generated_prompt(text: str, config: dict) -> str | None:
    """Limpia y valida el prompt generado."""
    text = strip_thinking(text)

    min_len = config["magpie"]["min_length"]
    max_len = config["magpie"]["max_length"]

    if len(text) < min_len or len(text) > max_len:
        return None

    if not any(c.isalnum() for c in text):
        return None

    return text


async def _generate_single_prompt(
    client: AsyncOpenAI,
    openai_config: dict,
    magpie_config: dict,
    model_config: dict,
    prefix: str,
    extra_body: dict,
) -> str | None:
    stop_tokens = model_config.get("stop_tokens", ["<|end|>", "<|endoftext|>"])
    try:
        response = await client.completions.create(
            model=openai_config["model"],
            prompt=prefix,
            temperature=magpie_config["temperature"],
            top_p=magpie_config["top_p"],
            max_tokens=magpie_config["max_tokens"],
            timeout=openai_config.get("timeout", 120),
            stop=stop_tokens,
            extra_body=extra_body if extra_body else None,
        )
        return response.choices[0].text
    except Exception as e:
        console.print(f"[yellow]Error generando prompt: {e}[/yellow]")
        return None


async def generate_prompts_batch(
    client: AsyncOpenAI,
    config: dict,
    batch_size: int,
    category: dict = None,
) -> list[str]:
    openai_config = config["openai"]
    magpie_config = config["magpie"]
    enable_thinking = openai_config.get("enable_thinking", True)

    extra_body = {}
    if not enable_thinking:
        extra_body = {"chat_template_kwargs": {"enable_thinking": False}}

    tasks = [
        _generate_single_prompt(
            client,
            openai_config,
            magpie_config,
            config["model"],
            build_magpie_prefix(config, category),
            extra_body,
        )
        for _ in range(batch_size)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    return [
        cleaned
        for result in results
        if isinstance(result, str) and result
        for cleaned in [clean_generated_prompt(result, config)]
        if cleaned
    ]


def save_prompts(prompts: list[dict], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for p in prompts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Red Teaming - Generación de Prompts Adversariales"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        default="config_red_teaming.yaml",
        help="Ruta al archivo de configuración (default: config_red_teaming.yaml)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    console.print(
        "[bold magenta]╔══════════════════════════════════════════════════════════╗[/bold magenta]"
    )
    console.print(
        "[bold magenta]║           Magpie - Generación de Prompts                 ║[/bold magenta]"
    )
    console.print(
        "[bold magenta]╚══════════════════════════════════════════════════════════╝[/bold magenta]\n"
    )

    console.print(f"[cyan]Config:[/cyan] {args.config}")
    config = load_config(args.config)
    logger = setup_logging(config)

    use_system = config.get("system_prompt", {}).get("enabled", False)
    categories = get_categories(config) if use_system else []

    console.print(f"[cyan]Modelo:[/cyan] {config['model']['name']}")
    console.print(
        f"[cyan]System prompt:[/cyan] {'Habilitado' if use_system else 'Deshabilitado'}"
    )

    if categories:
        console.print(f"[cyan]Categorías:[/cyan] {len(categories)}")
        for cat in categories:
            console.print(f"  - {cat['name']}: {cat['description'][:50]}...")

    num_prompts = config["magpie"]["num_prompts"]
    batch_size = max(1, int(config["magpie"].get("batch_size", 1)))
    console.print(f"[cyan]Prompts a generar:[/cyan] {num_prompts}\n")

    if use_system:
        console.print(
            "[yellow]Modo:[/yellow] Safety Alignment (prompts adversariales con rotación de categorías)\n"
        )

    console.print("[yellow]Conectando con servidor OpenAI...[/yellow]")
    openai_config = config.get("openai", {})

    client = AsyncOpenAI(
        base_url=openai_config.get("base_url", "http://localhost:8000/v1"),
        api_key=openai_config.get("api_key", "tu-api-key-aqui"),
    )

    console.print(f"[cyan]URL:[/cyan] {openai_config.get('base_url')}")
    console.print(f"[cyan]Modelo:[/cyan] {openai_config.get('model')}")

    enable_thinking = openai_config.get("enable_thinking", True)
    if not enable_thinking:
        console.print("[cyan]Thinking:[/cyan] Deshabilitado (chat_template_kwargs)")

    console.print("[green]✓ Cliente OpenAI inicializado[/green]\n")

    all_prompts = []
    if categories:
        prompts_per_category = num_prompts // len(categories)
        extra = num_prompts % len(categories)
        category_remaining = {
            cat["name"]: prompts_per_category + (1 if i < extra else 0)
            for i, cat in enumerate(categories)
        }
        category_map = {cat["name"]: cat for cat in categories}
        console.print(f"[cyan]Prompts por categoría:[/cyan] ~{prompts_per_category}")
    else:
        category_remaining = {"__none__": num_prompts}
        category_map = {"__none__": None}

    system_prompt_text_cache = {
        cat["name"]: build_system_prompt_text(config, cat) for cat in categories
    }

    with tqdm(total=num_prompts, desc="Generando prompts") as pbar:
        while any(v > 0 for v in category_remaining.values()):
            for cat_name, remaining in list(category_remaining.items()):
                if remaining <= 0:
                    continue

                current_category = category_map.get(cat_name)
                current_batch = min(batch_size, remaining)

                valid_prompts = await generate_prompts_batch(
                    client, config, current_batch, current_category
                )

                added = 0
                for prompt_text in valid_prompts:
                    if category_remaining[cat_name] <= 0:
                        break

                    prompt_data = {
                        "id": len(all_prompts),
                        "prompt": prompt_text,
                        "source": "magpie",
                        "timestamp": datetime.now().isoformat(),
                    }

                    if cat_name != "__none__":
                        prompt_data["category"] = cat_name
                    if system_prompt_text_cache.get(cat_name):
                        prompt_data["system_prompt"] = system_prompt_text_cache[
                            cat_name
                        ]

                    if _HAS_PYDANTIC:
                        try:
                            PromptModel.model_validate(prompt_data)
                        except ValidationError as ve:
                            logger.debug(
                                f"Validation failed id={prompt_data.get('id')}: {ve}"
                            )
                            prompt_data["_validation_error"] = str(ve)

                    all_prompts.append(prompt_data)
                    category_remaining[cat_name] -= 1
                    added += 1
                    pbar.update(1)

                if added == 0:
                    console.print(
                        f"[yellow]⚠ Ningún prompt válido para '{cat_name}' en este batch, reintentando...[/yellow]"
                    )

    output_dir = Path(config["paths"]["output_dir"])
    configured_name = config["paths"].get("output_file", "magpie_prompts.jsonl")
    model_name_safe = config["model"].get("name", "model")
    base = Path(configured_name)
    new_name = f"{base.stem}_{model_name_safe}_{num_prompts}{base.suffix}"
    output_file = output_dir / new_name
    save_prompts(all_prompts, output_file)

    console.print(
        "\n[bold green]╔══════════════════════════════════════════════════════════╗[/bold green]"
    )
    console.print(
        "[bold green]║              GENERACIÓN COMPLETADA                        ║[/bold green]"
    )
    console.print(
        "[bold green]╚══════════════════════════════════════════════════════════╝[/bold green]\n"
    )

    console.print(f"[green]✓ Prompts generados:[/green] {len(all_prompts)}")
    console.print(f"[blue]📁 Guardado en:[/blue] {output_file}")

    if categories:
        console.print("\n[cyan]Distribución por categoría:[/cyan]")
        cat_counts = Counter(p.get("category", "sin_categoria") for p in all_prompts)
        for cat, count in sorted(cat_counts.items()):
            console.print(f"  - {cat}: {count}")

    console.print("\n[cyan]Ejemplos de prompts generados:[/cyan]")
    for i, p in enumerate(all_prompts[:5]):
        cat_label = f"[{p.get('category', 'general')}] " if p.get("category") else ""
        console.print(
            f"  {i + 1}. {cat_label}{p['prompt'][:80]}{'...' if len(p['prompt']) > 80 else ''}"
        )

    console.print(
        "\n[dim]Ejecuta 'python generate_responses.py' para generar respuestas.[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(main())
