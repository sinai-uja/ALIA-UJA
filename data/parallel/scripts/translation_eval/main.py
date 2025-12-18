"""Main entry point for translation evaluation."""

import argparse
import torch
from pathlib import Path
from src import (
    EvaluationConfig,
    DataLoader,
    TranslationEvaluator,
    setup_logging,
    save_results,
    print_summary
)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Evaluate machine translation quality using multiple metrics"
    )
    
    parser.add_argument(
        '--data',
        type=str,
        default=None,
        help='Path to input data file (parquet format). If not provided, value from config.py is used.'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Path to output results file. If not provided, value from config.py is used.'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=None,
        help='Batch size for neural metrics. If not provided, value from config.py is used.'
    )
    
    # allow explicit enabling/disabling of GPU; default is None so config value is used
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--use-gpu', dest='use_gpu', action='store_true', help='Enable GPU for computation')
    group.add_argument('--no-gpu', dest='use_gpu', action='store_false', help='Disable GPU for computation')
    parser.set_defaults(use_gpu=None)
    
    parser.add_argument(
        '--metrics',
        nargs='+',
        default=None,
        help='Specific metrics to compute (default: all from config)'
    )
    
    parser.add_argument(
        '--bleurt-checkpoint',
        type=str,
        default=None,
        help='Path to BLEURT checkpoint. If not provided, value from config.py is used.'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to a JSON config file (overrides config.py defaults). If not provided, looks for ./config.json next to this script.'
    )

    parser.add_argument(
        '--col-source',
        type=str,
        default=None,
        help='Column name to use for source texts (overrides config)'
    )

    parser.add_argument(
        '--col-prediction',
        type=str,
        default=None,
        help='Column name to use for model predictions (overrides config)'
    )

    parser.add_argument(
        '--col-reference',
        type=str,
        default=None,
        help='Column name to use for references (overrides config)'
    )
    
    return parser.parse_args()


def main():
    """Main execution function."""
    args = parse_args()
    
    # Setup logging
    setup_logging()
    
    # Create configuration from defaults in src/config.py
    config = EvaluationConfig()

    # Load JSON config file if provided or if a default file exists next to
    # the script. JSON values will override defaults from config.py.
    cfg_path = None
    if args.config:
        cfg_path = Path(args.config)
    else:
        default_cfg = Path(__file__).parent / 'config.json'
        if default_cfg.exists():
            cfg_path = default_cfg

    if cfg_path and cfg_path.exists():
        import json
        try:
            with open(cfg_path, 'r', encoding='utf-8') as fh:
                cfg_data = json.load(fh)

            # cfg_data may be nested (we allow some grouping in the example
            # config). Flatten common groups and apply known keys.
            # EXCEPT for column_mapping which should stay as a dict
            flat = {}
            def merge(d, parent_key=''):
                for k, v in d.items():
                    # Don't flatten column_mapping - keep it as a dict
                    if k == 'column_mapping':
                        flat[k] = v
                    elif isinstance(v, dict):
                        merge(v, k)
                    else:
                        flat[k] = v
            merge(cfg_data)

            # Apply keys that exist on EvaluationConfig
            for k, v in flat.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        except Exception as e:
            print(f"Warning: could not load config from {cfg_path}: {e}")

    # Finally, override with any CLI args the user passed explicitly.
    if args.data is not None:
        config.data_file = args.data
    if args.output is not None:
        config.output_file = args.output
    if args.batch_size is not None:
        config.batch_size = args.batch_size
    if args.use_gpu is not None:
        config.use_gpu = args.use_gpu
    if args.metrics is not None:
        config.metrics = args.metrics
    if args.bleurt_checkpoint is not None:
        config.bleurt_checkpoint = args.bleurt_checkpoint
    # If user provided column names via CLI, override the config mapping.
    cli_mapping = {}
    if args.col_source:
        cli_mapping['source'] = args.col_source
    if args.col_prediction:
        cli_mapping['prediction'] = args.col_prediction
    if args.col_reference:
        cli_mapping['reference'] = args.col_reference

    if cli_mapping:
        # start from existing config mapping and update
        mapping = dict(config.column_mapping)
        mapping.update(cli_mapping)
        config.column_mapping = mapping
    
    # Load data
    sources, predictions, references = DataLoader.prepare_data(config.data_file, column_mapping=config.column_mapping)

    
    print("CUDA available:", torch.cuda.is_available())
    print("CUDA version:", torch.version.cuda)
    print("Device count:", torch.cuda.device_count())
    
    # Initialize evaluator
    evaluator = TranslationEvaluator(config)
    
    # Run evaluation
    results = evaluator.evaluate(sources, predictions, references)
    
    # Save and display results
    save_results(results, config.output_file)
    print_summary(results)


if __name__ == "__main__":
    main()