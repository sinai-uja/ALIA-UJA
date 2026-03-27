"""Reference-based metrics (BLEU, chrF, TER, ROUGE, METEOR)."""

import evaluate
from typing import Dict, List, Any
from .base import BaseMetric


class BLEUMetric(BaseMetric):
    """BLEU metric."""
    
    def __init__(self):
        super().__init__("BLEU")
        self.metric = evaluate.load("bleu")
    
    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()
        return self.metric.compute(predictions=predictions, references=references)


class ChrFMetric(BaseMetric):
    """chrF metric."""
    
    def __init__(self):
        super().__init__("chrF")
        self.metric = evaluate.load("chrf")
    
    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()
        return self.metric.compute(predictions=predictions, references=references)


class TERMetric(BaseMetric):
    """TER metric."""
    
    def __init__(self):
        super().__init__("TER")
        self.metric = evaluate.load("ter")
    
    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()
        return self.metric.compute(predictions=predictions, references=references)


class ROUGEMetric(BaseMetric):
    """ROUGE metric."""
    
    def __init__(self):
        super().__init__("ROUGE")
        self.metric = evaluate.load("rouge")
    
    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()
        return self.metric.compute(predictions=predictions, references=references)


class METEORMetric(BaseMetric):
    """METEOR metric."""
    
    def __init__(self):
        super().__init__("METEOR")
        self.metric = evaluate.load("meteor")
    
    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()
        return self.metric.compute(predictions=predictions, references=references)