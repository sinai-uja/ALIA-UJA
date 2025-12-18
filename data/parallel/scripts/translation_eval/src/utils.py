"""Utility functions."""

import json
import logging
from pathlib import Path
from typing import Dict, Any


def setup_logging(level: int = logging.WARNING):
    """Configure logging for the application.

    By default this sets the root logger to WARNING so that only warnings
    and errors appear on the console. This keeps the console clean so only
    prints and tqdm progress bars are visible. It also silences known noisy
    libraries by setting them to WARNING.
    """
    # Basic config for the root logger
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Environment variables to reduce C/C++-level logs (TensorFlow, HF hub,
    # Lightning tips and HF progress). Set before heavy libraries are loaded.
    import os
    os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')  # show warnings/errors only
    os.environ.setdefault('TF_ENABLE_ONEDNN_OPTS', '0')
    os.environ.setdefault('HF_HUB_DISABLE_PROGRESS', '1')
    os.environ.setdefault('WANDB_DISABLED', 'true')

    # Reduce verbosity of known noisy Python loggers so that tqdm and prints
    # remain the main console outputs.
    noisy_loggers = [
        'comet',
        'bleurt',
        'transformers',
        'evaluate',
        'tensorflow',
        'torch',
        'urllib3',
        'matplotlib',
        'lightning',
        'lightning_fabric',
        'pytorch_lightning',
    ]

    for name in noisy_loggers:
        try:
            logging.getLogger(name).setLevel(logging.WARNING)
            # Prevent message propagation to root handlers to avoid duplicate prints
            logging.getLogger(name).propagate = False
        except Exception:
            pass

    # Filter some common noisy warnings (pkg_resources deprecation and others).
    import warnings
    warnings.filterwarnings('ignore', message='pkg_resources is deprecated')
    warnings.filterwarnings('ignore', message='The `srun` command is available')


def save_results(results: Dict[str, Any], output_file: str):
    """Save results to JSON file."""
    output_path = Path(output_file)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
    
    logging.info(f"Results saved to {output_file}")


def print_summary(results: Dict[str, Any]):
    """Print a summary of results."""
    print("\n" + "=" * 50)
    print("EVALUATION SUMMARY")
    print("=" * 50)
    
    for metric, values in results.items():
        if isinstance(values, dict):
            if "error" in values:
                print(f"{metric:15s}: ERROR - {values['error']}")
            else:
                # Try to get main score
                main_score = values.get('score', values.get('bleu', values.get('chrf', 'N/A')))
                print(f"{metric:15s}: {main_score}")
        else:
            print(f"{metric:15s}: {values}")
    
    print("=" * 50 + "\n")
