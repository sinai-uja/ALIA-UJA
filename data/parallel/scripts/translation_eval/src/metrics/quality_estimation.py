"""Quality estimation metrics (COMET-KIWI)."""

from typing import Dict, List, Any
from tqdm import tqdm
from comet import load_from_checkpoint
from .base import BaseMetric


class COMETKiwiMetric(BaseMetric):
    """COMET-KIWI metric (reference-free QE)."""
    
    def __init__(self, model_path: str = "models/wmt20-comet-qe-da", batch_size: int = 8, gpus: int = 0):
        super().__init__("COMET-KIWI")
        self.batch_size = batch_size
        self.gpus = gpus
        
        self.logger.info(f"Loading COMET-KIWI model from: {model_path}")
        self.model = load_from_checkpoint(model_path)
    
    def compute(self, predictions: List[str], sources: List[str]) -> Dict[str, Any]:
        self.log_computation()
        
        data = [
            {"src": src, "mt": pred}
            for src, pred in zip(sources, predictions)
        ]
        
        scores = []
        for i in tqdm(range(0, len(data), self.batch_size), desc=self.name, unit="batch"):
            batch = data[i:i + self.batch_size]
            output = self.model.predict(batch, batch_size=self.batch_size, gpus=self.gpus)
            scores.extend(output.scores)
        
        system_score = sum(scores) / len(scores) if scores else 0.0
        return {"score": system_score, "scores": scores}