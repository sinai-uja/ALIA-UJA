#!/usr/bin/env python3
"""Interactive question variation using configurable HTTP endpoints."""

from __future__ import annotations

import json
import random
import re
import sys
import time
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
import yaml


CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass(frozen=True)
class RemoteApiConfig:
    """Request paths and payload field names for a custom HTTP API."""
    auth_url: str
    models_url: str
    chat_url: str
    username_field: str = "user"
    password_field: str = "password"
    token_field: str = "token"
    models_path: str = "data"


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings for the interactive remote-inference flow."""
    input_path: Path
    output_dir: Path
    api: RemoteApiConfig
    variation_mode: str
    max_retries: int
    request_delay: float
    checkpoint_every: int
    variation_prompts: dict[str, str]

    @classmethod
    def from_file(cls, path: Path) -> "AppConfig":
        # Fail fast when the remote API contract is incomplete.
        if not path.exists():
            raise SystemExit(f"[ERROR] Missing config file: {path}")
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        api = cfg.get("api") or {}
        required = {
            "input_path": cfg.get("input_path"),
            "output_dir": cfg.get("output_dir"),
            "api.auth_url": api.get("auth_url"),
            "api.models_url": api.get("models_url"),
            "api.chat_url": api.get("chat_url"),
            "variation_prompts": cfg.get("variation_prompts"),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise SystemExit(f"[ERROR] Missing required config keys: {', '.join(missing)}")
        return cls(
            input_path=Path(cfg["input_path"]),
            output_dir=Path(cfg["output_dir"]),
            api=RemoteApiConfig(
                auth_url=str(api["auth_url"]),
                models_url=str(api["models_url"]),
                chat_url=str(api["chat_url"]),
                username_field=str(api.get("username_field", "user")),
                password_field=str(api.get("password_field", "password")),
                token_field=str(api.get("token_field", "token")),
                models_path=str(api.get("models_path", "data")),
            ),
            variation_mode=str(cfg.get("variation_mode", "all_random")),
            max_retries=int(cfg.get("max_retries", 3)),
            request_delay=float(cfg.get("request_delay", 0.5)),
            checkpoint_every=int(cfg.get("checkpoint_every", 50)),
            variation_prompts=dict(cfg["variation_prompts"]),
        )


class RemoteApiClient:
    """Thin wrapper around the remote API lifecycle."""
    def __init__(self, cfg: RemoteApiConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.token: str | None = None

    def authenticate(self, username: str, password: str) -> None:
        """Exchange user credentials for an access token."""
        # Authentication is deliberately separate from model selection.
        payload = {
            self.cfg.username_field: username,
            self.cfg.password_field: password,
        }
        response = self.session.post(
            self.cfg.auth_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        token = response.json().get(self.cfg.token_field)
        if not token:
            raise SystemExit(f"[ERROR] Auth response does not contain '{self.cfg.token_field}'")
        self.token = token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError("Client is not authenticated")
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def list_models(self) -> list[str]:
        """Return the list of model identifiers exposed by the server."""
        # The response shape is configurable because different APIs nest models differently.
        response = self.session.get(self.cfg.models_url, headers=self._headers(), timeout=60)
        response.raise_for_status()
        data: Any = response.json()
        for part in self.cfg.models_path.split("."):
            if part:
                data = data[part]
        return [item["id"] if isinstance(item, dict) else str(item) for item in data]

    def send_message(self, model: str, system_prompt: str, user_message: str) -> str:
        """Send a chat completion request and return the assistant text."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        response = self.session.post(self.cfg.chat_url, headers=self._headers(), json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()


class JsonlStore:
    """Read/write helper for JSONL input and output files."""
    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        rows = []
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
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


class InteractiveQuestionVariator:
    """Interactive rewrite runner that prompts the user for credentials and model choice."""
    def __init__(self, cfg: AppConfig, client: RemoteApiClient):
        self.cfg = cfg
        self.client = client
        self.style_names = list(cfg.variation_prompts)

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Return a filesystem-safe label for output files."""
        return re.sub(r"[^\w\-.]", "_", name)

    def get_style(self, index: int) -> str:
        """Choose a style according to the configured variation mode."""
        # Random mode picks a style per row; fixed modes reuse the same style.
        mode = self.cfg.variation_mode
        if mode == "all_random":
            return random.choice(self.style_names)
        if mode in self.style_names:
            return mode
        return self.style_names[index % len(self.style_names)]

    @staticmethod
    def load_checkpoint(path: Path) -> int:
        """Read the next row index to process from disk."""
        return int(path.read_text(encoding="utf-8").strip()) if path.exists() else 0

    @staticmethod
    def save_checkpoint(path: Path, index: int) -> None:
        """Store the next row index so the run can resume later."""
        path.write_text(str(index), encoding="utf-8")

    def run(self, selected_model: str) -> None:
        """Process the dataset sequentially using the chosen remote model."""
        if not self.cfg.input_path.exists():
            raise SystemExit(f"[ERROR] Input file not found: {self.cfg.input_path}")

        rows = JsonlStore.load(self.cfg.input_path)
        safe_name = self.sanitize_filename(selected_model)
        output_path = self.cfg.output_dir / f"{safe_name}.jsonl"
        checkpoint_path = self.cfg.output_dir / f".checkpoint_{safe_name}.txt"
        # Keep partial results when the checkpoint exists.
        output_rows = JsonlStore.load(output_path) if output_path.exists() and checkpoint_path.exists() else []
        start_index = self.load_checkpoint(checkpoint_path)

        print(f"Input rows: {len(rows)}")
        print(f"Variation mode: {self.cfg.variation_mode}")
        print(f"Starting at row: {start_index}")

        for index in range(start_index, len(rows)):
            row = rows[index].copy()
            original_question = row.get("question", "")
            style = self.get_style(index)
            varied_question = None
            for attempt in range(1, self.cfg.max_retries + 1):
                try:
                    varied_question = self.client.send_message(
                        selected_model,
                        self.cfg.variation_prompts[style],
                        original_question,
                    )
                    break
                except Exception as exc:
                    print(f"\n  [!] Attempt {attempt}/{self.cfg.max_retries} failed at row {index}: {exc}")
                    if attempt < self.cfg.max_retries:
                        time.sleep(2 ** attempt)

            row["question"] = varied_question or original_question
            row["old_question"] = original_question
            row["variation_style"] = style
            row["model"] = selected_model
            output_rows.append(row)

            print(f"\rProcessed {index + 1}/{len(rows)} - {style:<24}", end="", flush=True)
            if (index + 1) % self.cfg.checkpoint_every == 0 or (index + 1) == len(rows):
                JsonlStore.save(output_rows, output_path)
                self.save_checkpoint(checkpoint_path, index + 1)
            if self.cfg.request_delay > 0:
                time.sleep(self.cfg.request_delay)

        JsonlStore.save(output_rows, output_path)
        checkpoint_path.unlink(missing_ok=True)
        print(f"\nSaved: {output_path}")


def choose_model(models: list[str]) -> str:
    """Ask the user to pick one model from the server response."""
    if not models:
        raise SystemExit("[ERROR] No models returned by the API")
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
    client = RemoteApiClient(cfg.api)
    username = input("Username: ").strip()
    password = getpass("Password: ")
    print("Authenticating...")
    client.authenticate(username, password)
    model = choose_model(client.list_models())
    InteractiveQuestionVariator(cfg, client).run(model)


if __name__ == "__main__":
    main()
