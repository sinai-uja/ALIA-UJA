"""Configuration settings for the translation evaluation project."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class EvaluationConfig:
    """Configuration for translation evaluation."""
    
    # Paths
    # Define project root relative to this file (src/config.py -> src -> translation_eval)
    _project_root = Path(__file__).resolve().parent.parent
    
    bleurt_checkpoint: str = str(_project_root / "src/metrics/bleurt/bleurt/test_checkpoint")
    data_file: str = str(_project_root / "data/datos.parquet")
    output_file: str = str(_project_root / "data/metric_results.json")
    
    # COMET models
    comet_model: str = "Unbabel/wmt22-comet-da"
    comet_kiwi_model: str = "Unbabel/wmt20-comet-qe-da"
    
    # Processing
    batch_size: int = 8
    use_gpu: bool = True
    # Column mapping for input data. Keys: source, prediction, reference
    column_mapping: dict = None
    
    # Metrics to compute
    metrics: list = None
    
    def __post_init__(self):
        if self.metrics is None:
            self.metrics = [
                "BLEU", "chrF", "TER", "COMET", 
                "COMET-KIWI", "ROUGE", "METEOR", "BLEURT"
            ]
        if self.column_mapping is None:
            self.column_mapping = {
                'source': 'source',
                'prediction': 'prediction',
                'reference': 'reference'
            }
    
    @property
    def gpus(self) -> int:
        """Return number of GPUs to use."""
        return 1 if self.use_gpu else 0
