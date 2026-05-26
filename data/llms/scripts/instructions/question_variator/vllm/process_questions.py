#!/usr/bin/env python3
"""Async question variation against a running vLLM OpenAI-compatible server."""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncOpenAI


CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings for the local vLLM rewrite flow."""
    input_path: Path
    output_dir: Path
    base_url: str
    api_key: str
    concurrency: int
    variation_mode: str
    max_retries: int
    checkpoint_every: int
    variation_prompts: dict[str, str]

    @classmethod
    def from_file(cls, path: Path) -> "AppConfig":
        # The local vLLM flow only needs the OpenAI-compatible base URL and prompt set.
        if not path.exists():
            raise SystemExit(f"[ERROR] Missing config file: {path}")
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        required = {
            "input_path": cfg.get("input_path"),
            "output_dir": cfg.get("output_dir"),
            "vllm_base_url": cfg.get("vllm_base_url"),
            "variation_prompts": cfg.get("variation_prompts"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise SystemExit(f"[ERROR] Missing required config keys: {', '.join(missing)}")
        return cls(
            input_path=Path(cfg["input_path"]),
            output_dir=Path(cfg["output_dir"]),
            base_url=str(cfg["vllm_base_url"]).rstrip("/"),
            api_key=str(cfg.get("vllm_api_key", "")),
            concurrency=int(cfg.get("concurrency", 16)),
            variation_mode=str(cfg.get("variation_mode", "all_random")),
            max_retries=int(cfg.get("max_retries", 3)),
            checkpoint_every=int(cfg.get("checkpoint_every", 100)),
            variation_prompts=dict(cfg["variation_prompts"]),
        )


class JsonlStore:
    """Read/write helper for JSONL datasets."""
    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        # JSONL keeps the output human-readable and append-friendly.
        rows = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"[ERROR] Invalid JSON at line {line_number}: {exc}") from exc
        return rows

    @staticmethod
    def save(rows: list[dict[str, Any]], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


class VllmQuestionVariator:
    """Async rewrite runner for a local OpenAI-compatible vLLM server."""
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.style_names = list(cfg.variation_prompts)

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Return a filesystem-safe label for output files."""
        return re.sub(r"[^\w\-.]", "_", name)

    @staticmethod
    def checkpoint_path(output_dir: Path, safe_model: str, mode: str) -> Path:
        """Derive the checkpoint file path from the model and mode."""
        return output_dir / f".checkpoint_{safe_model}_{re.sub(r'[^\w]', '_', mode)}.txt"

    def build_tasks(self, row_count: int, done: set[int | tuple[int, str]]) -> list[tuple[int, str]]:
        """Expand the row/style matrix while skipping already completed work."""
        # Build the full task list first so checkpoint recovery is exact.
        mode = self.cfg.variation_mode
        tasks = []
        if mode == "all_combinations":
            for index in range(row_count):
                for style in self.style_names:
                    if (index, style) not in done:
                        tasks.append((index, style))
            return tasks
        if mode == "all_random":
            for index in range(row_count):
                if index not in done:
                    tasks.append((index, random.choice(self.style_names)))
            return tasks
        if mode not in self.style_names:
            raise SystemExit(f"[ERROR] Unknown variation_mode: {mode}")
        return [(index, mode) for index in range(row_count) if index not in done]

    def load_checkpoint(self, path: Path) -> set[int | tuple[int, str]]:
        """Load completed items from a checkpoint file."""
        if not path.exists():
            return set()
        done: set[int | tuple[int, str]] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if self.cfg.variation_mode == "all_combinations":
                row_idx, style = line.split("\t", 1)
                done.add((int(row_idx), style))
            else:
                done.add(int(line))
        return done

    def save_checkpoint(self, path: Path, done: set[int | tuple[int, str]]) -> None:
        """Write checkpoint state to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if self.cfg.variation_mode == "all_combinations":
            lines = [f"{row_idx}\t{style}" for row_idx, style in sorted(done)]
        else:
            lines = [str(index) for index in sorted(done)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def make_client(self) -> AsyncOpenAI:
        """Create a minimal OpenAI client targeting the local vLLM server."""
        # vLLM already exposes an OpenAI-compatible API, so the client is minimal.
        return AsyncOpenAI(
            base_url=self.cfg.base_url,
            api_key=self.cfg.api_key or "EMPTY",
        )

    async def list_models(self, client: AsyncOpenAI) -> list[str]:
        """Ask vLLM which models are currently served."""
        try:
            models = await client.models.list()
            return [model.id for model in models.data]
        except Exception as exc:
            raise SystemExit(f"[ERROR] Could not query vLLM models: {exc}") from exc

    async def send_message(
        self,
        client: AsyncOpenAI,
        semaphore: asyncio.Semaphore,
        model: str,
        system_prompt: str,
        user_message: str,
    ) -> str:
        """Send one chat-completion request with retries."""
        async with semaphore:
            for attempt in range(1, self.cfg.max_retries + 1):
                try:
                    response = await client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                    )
                    return response.choices[0].message.content.strip()
                except Exception:
                    if attempt == self.cfg.max_retries:
                        raise
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError("unreachable")

    async def process_all(
        self,
        tasks: list[tuple[int, str]],
        rows: list[dict[str, Any]],
        selected_model: str,
        client: AsyncOpenAI,
        output_rows: list[dict[str, Any]],
        done: set[int | tuple[int, str]],
        output_path: Path,
        checkpoint_path: Path,
    ) -> None:
        """Run all pending tasks concurrently and persist progress as we go."""
        semaphore = asyncio.Semaphore(self.cfg.concurrency)
        lock = asyncio.Lock()
        started = time.time()

        async def handle(row_idx: int, style: str) -> None:
            # Keep row updates isolated so concurrency does not leak state.
            row = rows[row_idx].copy()
            original_question = row.get("question", "")
            existing_response = row.get("response", "")
            user_message = (
                f"Respuesta a la pregunta: {existing_response}\n\n"
                f"Pregunta original: {original_question}"
            )
            try:
                varied = await self.send_message(
                    client,
                    semaphore,
                    selected_model,
                    self.cfg.variation_prompts[style],
                    user_message,
                )
            except Exception as exc:
                print(f"\n  [SKIP] row {row_idx}/{style}: {exc}")
                varied = original_question

            row["question"] = varied
            row["old_question"] = original_question
            row["variation_style"] = style
            row["model"] = selected_model

            async with lock:
                # The lock protects shared output/checkpoint writes.
                output_rows.append(row)
                done.add((row_idx, style) if self.cfg.variation_mode == "all_combinations" else row_idx)
                processed = len(done)
                print(f"\rProcessed {processed} items - {style:<24}", end="", flush=True)
                if processed % self.cfg.checkpoint_every == 0:
                    JsonlStore.save(output_rows, output_path)
                    self.save_checkpoint(checkpoint_path, done)

        await asyncio.gather(*(handle(row_idx, style) for row_idx, style in tasks))
        elapsed = max(time.time() - started, 0.001)
        print(f"\nThroughput: {len(tasks) / elapsed:.2f} calls/s")

    async def run(self) -> None:
        """Execute the full local-vLLM workflow."""
        if not self.cfg.input_path.exists():
            raise SystemExit(f"[ERROR] Input file not found: {self.cfg.input_path}")

        rows = JsonlStore.load(self.cfg.input_path)
        client = self.make_client()
        # Auto-select when only one model is available or stdin is not interactive.
        models = await self.list_models(client)
        selected_model = models[0] if len(models) == 1 or not sys.stdin.isatty() else self.choose_model(models)

        safe_name = self.sanitize_filename(selected_model)
        output_path = self.cfg.output_dir / f"{safe_name}.jsonl"
        checkpoint_path = self.checkpoint_path(self.cfg.output_dir, safe_name, self.cfg.variation_mode)
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        done = self.load_checkpoint(checkpoint_path)
        tasks = self.build_tasks(len(rows), done)
        output_rows = JsonlStore.load(output_path) if output_path.exists() and done else []

        print(f"vLLM endpoint: {self.cfg.base_url}")
        print(f"Model: {selected_model}")
        print(f"Input rows: {len(rows)}")
        print(f"Pending calls: {len(tasks)}")
        if not tasks:
            print("Nothing to do.")
            return

        await self.process_all(tasks, rows, selected_model, client, output_rows, done, output_path, checkpoint_path)
        JsonlStore.save(output_rows, output_path)
        checkpoint_path.unlink(missing_ok=True)
        print(f"Saved: {output_path}")

    @staticmethod
    def choose_model(models: list[str]) -> str:
        """Ask the user to select one model from the server list."""
        print("\nAvailable models:")
        for index, model in enumerate(models, start=1):
            print(f"  {index}. {model}")
        choice = input("\nChoose model number: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(models)):
            raise SystemExit("[ERROR] Invalid model selection")
        return models[int(choice) - 1]


def main() -> None:
    """CLI entry point."""
    cfg = AppConfig.from_file(CONFIG_FILE)
    asyncio.run(VllmQuestionVariator(cfg).run())


if __name__ == "__main__":
    main()
