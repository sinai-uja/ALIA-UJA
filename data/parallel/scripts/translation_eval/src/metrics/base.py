"""Base classes for metrics."""

from abc import ABC, abstractmethod
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class BaseMetric(ABC):
    """Abstract base class for all metrics."""
    
    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")
    
    @abstractmethod
    def compute(self, **kwargs) -> Dict[str, Any]:
        """Compute the metric."""
        pass
    
    def log_computation(self):
        """Log metric computation."""
        self.logger.info(f"Computing {self.name}...")
