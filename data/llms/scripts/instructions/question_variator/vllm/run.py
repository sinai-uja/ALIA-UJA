#!/usr/bin/env python3
"""Start a vLLM server and then run the question processor."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlunparse

import requests
import yaml


CONFIG_FILE = Path(__file__).parent / "config.yaml"


@dataclass(frozen=True)
class VllmServerConfig:
    """Server launch parameters parsed from `config.yaml`."""
    model: str
    host: str
    port: int
    scheme: str
    startup_timeout: int
    max_model_len: int | None
    gpu_memory_util: float | None
    tensor_parallel_size: int | None
    dtype: str | None
    extra_args: list[str]

    @property
    def base_url(self) -> str:
        return urlunparse((self.scheme, f"{self.host}:{self.port}", "/v1", "", "", ""))

    @property
    def local_base_url(self) -> str:
        host = "127.0.0.1" if self.host in {"0.0.0.0", "::"} else self.host
        return urlunparse((self.scheme, f"{host}:{self.port}", "/v1", "", "", ""))


def load_config() -> dict:
    """Load the shared vLLM configuration file."""
    if not CONFIG_FILE.exists():
        raise SystemExit(f"[ERROR] Missing config file: {CONFIG_FILE}")
    return yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}


def parse_server_config(cfg: dict) -> VllmServerConfig:
    # vLLM settings live in config.yaml so the launcher remains generic.
    model = cfg.get("vllm_model")
    if not model:
        raise SystemExit("[ERROR] Missing required config key: vllm_model")
    return VllmServerConfig(
        model=str(model),
        host=str(cfg.get("vllm_host", "127.0.0.1")),
        port=int(cfg.get("vllm_port", 8000)),
        scheme=str(cfg.get("vllm_scheme", "http")),
        startup_timeout=int(cfg.get("vllm_startup_timeout", 900)),
        max_model_len=cfg.get("vllm_max_model_len"),
        gpu_memory_util=cfg.get("vllm_gpu_memory_util"),
        tensor_parallel_size=cfg.get("vllm_tensor_parallel_size"),
        dtype=cfg.get("vllm_dtype"),
        extra_args=[str(arg) for arg in cfg.get("vllm_extra_args", [])],
    )


def build_vllm_command(server: VllmServerConfig) -> list[str]:
    """Translate the config object into a `vllm serve` command line."""
    # Only include optional flags when they are explicitly configured.
    cmd = [
        "vllm",
        "serve",
        server.model,
        "--host",
        server.host,
        "--port",
        str(server.port),
    ]
    if server.dtype:
        cmd += ["--dtype", str(server.dtype)]
    if server.max_model_len:
        cmd += ["--max-model-len", str(server.max_model_len)]
    if server.gpu_memory_util:
        cmd += ["--gpu-memory-utilization", str(server.gpu_memory_util)]
    if server.tensor_parallel_size:
        cmd += ["--tensor-parallel-size", str(server.tensor_parallel_size)]
    return cmd + server.extra_args


def wait_for_vllm(base_url: str, timeout: int) -> None:
    """Poll the server until the models endpoint becomes available."""
    # Poll the model endpoint until the server is ready or the timeout expires.
    models_url = f"{base_url}/models"
    print(f"Waiting for vLLM at {base_url} ...", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(models_url, timeout=3)
            if response.status_code == 200:
                print("vLLM is ready.")
                return
        except requests.RequestException:
            pass
        time.sleep(5)
        print(".", end="", flush=True)
    raise SystemExit(f"\n[ERROR] vLLM did not answer within {timeout}s")


def stream_logs(proc: subprocess.Popen[str]) -> None:
    """Mirror child process logs to the current terminal."""
    def _print() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            print(f"[vllm] {line}", end="")

    threading.Thread(target=_print, daemon=True).start()


def update_processor_base_url(cfg: dict, base_url: str) -> None:
    """Persist the reachable local base URL into the shared config file."""
    # The processor reuses the same config file, so we persist the reachable URL.
    cfg["vllm_base_url"] = base_url
    CONFIG_FILE.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False), encoding="utf-8")


def main() -> None:
    """Start vLLM, wait for readiness, then hand off to the processor."""
    cfg = load_config()
    server = parse_server_config(cfg)
    update_processor_base_url(cfg, server.local_base_url)

    # Start the server first, then hand control to the processor script.
    print(f"Starting vLLM model: {server.model}")
    proc = subprocess.Popen(
        build_vllm_command(server),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    stream_logs(proc)

    def shutdown(*_: object) -> None:
        print("\nStopping vLLM...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        wait_for_vllm(server.local_base_url, server.startup_timeout)
        import process_questions

        process_questions.main()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
