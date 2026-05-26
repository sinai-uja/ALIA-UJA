#!/usr/bin/env python3
"""Async question variation using an OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openai
import yaml
from openai import AsyncOpenAI


CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass(frozen=True)
class ApiConfig:
    """Connection details for a single OpenAI-compatible endpoint."""
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class AppConfig:
    """Top-level runtime configuration loaded from `config.yaml`."""
    input_path: Path
    output_dir: Path
    api: ApiConfig
    variation_mode: str
    max_retries: int
    retry_base_delay: float
    request_delay: float
    save_every_rows: int
    max_concurrency: int
    request_timeout: float
    temperature: float | None
    random_seed: int
    variation_prompts: dict[str, str]

    @classmethod
    def from_file(cls, path: Path) -> "AppConfig":
        # Keep the config contract strict so missing keys fail early.
        if not path.exists():
            raise SystemExit(f"[ERROR] Missing config file: {path}")

        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        api = cfg.get("api") or {}
        required = {
            "input_path": cfg.get("input_path"),
            "output_dir": cfg.get("output_dir"),
            "api.base_url": api.get("base_url"),
            "api.api_key": api.get("api_key"),
            "api.model": api.get("model"),
            "variation_prompts": cfg.get("variation_prompts"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise SystemExit(f"[ERROR] Missing required config keys: {', '.join(missing)}")

        return cls(
            input_path=Path(cfg["input_path"]),
            output_dir=Path(cfg["output_dir"]),
            api=ApiConfig(
                base_url=str(api["base_url"]).rstrip("/"),
                api_key=str(api["api_key"]),
                model=str(api["model"]),
            ),
            variation_mode=str(cfg.get("variation_mode", "all_random")),
            max_retries=int(cfg.get("max_retries", 3)),
            retry_base_delay=float(cfg.get("retry_base_delay", 1.0)),
            request_delay=float(cfg.get("request_delay", 0.0)),
            save_every_rows=int(cfg.get("save_every_rows", 50)),
            max_concurrency=int(cfg.get("max_concurrency", 5)),
            request_timeout=float(cfg.get("request_timeout", 120.0)),
            temperature=cfg.get("temperature"),
            random_seed=int(cfg.get("random_seed", 42)),
            variation_prompts=dict(cfg["variation_prompts"]),
        )


class JsonlStore:
    """Small helper for reading and writing JSONL datasets."""
    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        # JSONL is used because it is easy to append, inspect, and resume.
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


class QuestionVariator:
    """Core async pipeline that rewrites questions through an LLM API."""
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.rng = random.Random(cfg.random_seed)
        self.style_names = list(cfg.variation_prompts)

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Return a filesystem-safe label for output files."""
        return re.sub(r"[^\w\-.]", "_", name)

    def build_tasks(self, row_count: int) -> list[tuple[int, str]]:
        # The task list is expanded up front so resume logic stays deterministic.
        mode = self.cfg.variation_mode
        if mode == "all_combinations":
            return [(idx, style) for idx in range(row_count) for style in self.style_names]
        if mode == "all_random":
            return [(idx, self.rng.choice(self.style_names)) for idx in range(row_count)]
        if mode not in self.style_names:
            raise SystemExit(f"[ERROR] Unknown variation_mode: {mode}")
        return [(idx, mode) for idx in range(row_count)]

    @staticmethod
    def load_checkpoint(path: Path) -> set[tuple[int, str]]:
        """Load the set of completed (row, style) pairs from disk."""
        if not path.exists():
            return set()
        done = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row_idx, style = line.split("\t", 1)
            done.add((int(row_idx), style))
        return done

    @staticmethod
    def save_checkpoint(path: Path, done: set[tuple[int, str]]) -> None:
        """Persist checkpoint state so interrupted runs can resume exactly."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{idx}\t{style}" for idx, style in sorted(done)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def load_existing_output(path: Path) -> dict[tuple[int, str], dict[str, Any]]:
        """Index previously written output rows by their resume key."""
        if not path.exists():
            return {}
        output = {}
        for row in JsonlStore.load(path):
            key = (row.get("source_row_index"), row.get("variation_style"))
            if key[0] is not None and key[1] is not None:
                output[key] = row
        return output

    @staticmethod
    def ordered_rows(tasks: list[tuple[int, str]], rows: dict[tuple[int, str], dict[str, Any]]) -> list[dict[str, Any]]:
        """Rebuild the output file in the same logical order as the task list."""
        return [rows[key] for key in tasks if key in rows]

    async def send_message(
        self,
        client: AsyncOpenAI,
        system_prompt: str,
        user_message: str,
    ) -> str | None:
        """Call the model with retry/backoff and return the trimmed rewrite."""
        # Retry transient API errors with exponential backoff.
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.cfg.api.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                }
                if self.cfg.temperature is not None:
                    kwargs["temperature"] = self.cfg.temperature
                response = await client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content
                return content.strip() if content else None
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.RateLimitError,
                openai.InternalServerError,
                openai.APIStatusError,
            ) as exc:
                if attempt == self.cfg.max_retries:
                    print(f"\n  [!] Request failed after {attempt} attempts: {exc}")
                    return None
                await asyncio.sleep(self.cfg.retry_base_delay * (2 ** (attempt - 1)))
        return None

    async def process_one(
        self,
        semaphore: asyncio.Semaphore,
        client: AsyncOpenAI,
        rows: list[dict[str, Any]],
        row_idx: int,
        style: str,
    ) -> tuple[tuple[int, str], dict[str, Any]]:
        async with semaphore:
            # Each output row preserves the original question alongside the rewrite.
            row = rows[row_idx].copy()
            original_question = row.get("question", "")
            existing_response = row.get("response", "")
            user_message = (
                f"Respuesta a la pregunta: {existing_response}\n\n"
                f"Pregunta original: {original_question}"
            )
            varied = await self.send_message(client, self.cfg.variation_prompts[style], user_message)
            row["question"] = varied or original_question
            row["old_question"] = original_question
            row["variation_style"] = style
            row["model"] = self.cfg.api.model
            row["source_row_index"] = row_idx
            if self.cfg.request_delay > 0:
                await asyncio.sleep(self.cfg.request_delay)
            return (row_idx, style), row

    async def run(self) -> None:
        """Run the full rewrite pipeline end to end."""
        if not self.cfg.input_path.exists():
            raise SystemExit(f"[ERROR] Input file not found: {self.cfg.input_path}")

        rows = JsonlStore.load(self.cfg.input_path)
        # Resume from the checkpoint and from already-written output rows.
        tasks = self.build_tasks(len(rows))
        safe_name = self.sanitize_filename(self.cfg.api.model)
        output_path = self.cfg.output_dir / f"{safe_name}.jsonl"
        checkpoint_path = self.cfg.output_dir / f".checkpoint_{safe_name}.tsv"
        done = self.load_checkpoint(checkpoint_path)
        output_map = self.load_existing_output(output_path)
        pending = [task for task in tasks if task not in done]

        print(f"Model: {self.cfg.api.model}")
        print(f"Input rows: {len(rows)}")
        print(f"Variation mode: {self.cfg.variation_mode}")
        print(f"Pending calls: {len(pending)}")
        if not pending:
            print("Nothing to do.")
            return

        semaphore = asyncio.Semaphore(self.cfg.max_concurrency)
        async with AsyncOpenAI(
            api_key=self.cfg.api.api_key,
            base_url=self.cfg.api.base_url,
            timeout=self.cfg.request_timeout,
            max_retries=0,
        ) as client:
            futures = [
                self.process_one(semaphore, client, rows, row_idx, style)
                for row_idx, style in pending
            ]
            for processed, future in enumerate(asyncio.as_completed(futures), start=1):
                key, row = await future
                output_map[key] = row
                done.add(key)
                print(f"\rProcessed {processed}/{len(pending)} - {key[1]:<24}", end="", flush=True)
                if processed % self.cfg.save_every_rows == 0 or processed == len(pending):
                    JsonlStore.save(self.ordered_rows(tasks, output_map), output_path)
                    self.save_checkpoint(checkpoint_path, done)

        JsonlStore.save(self.ordered_rows(tasks, output_map), output_path)
        checkpoint_path.unlink(missing_ok=True)
        print(f"\nSaved: {output_path}")


def main() -> None:
    """CLI entry point."""
    cfg = AppConfig.from_file(CONFIG_FILE)
    asyncio.run(QuestionVariator(cfg).run())


if __name__ == "__main__":
    main()
