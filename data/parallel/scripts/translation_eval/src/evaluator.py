"""Main evaluator class."""

from typing import Dict, List, Any
import logging
import os
import gc
import torch
from tqdm import tqdm
from .config import EvaluationConfig
from .metrics import (
    BLEUMetric, ChrFMetric, TERMetric, ROUGEMetric, METEORMetric,
    COMETMetric, BLEURTMetric, COMETKiwiMetric
)

logger = logging.getLogger(__name__)

class TranslationEvaluator:
    """Orchestrates the evaluation of translation metrics."""
    
    def __init__(self, config: EvaluationConfig):
        self.config = config
        # Do NOT initialize metrics here - we'll do it on demand
    
    def _clear_gpu_memory(self):
        """Clear GPU memory cache and force garbage collection."""
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        gc.collect()
    
    def _initialize_metric(self, metric_name: str):
        """Initialize a single metric on demand."""
        import contextlib
        import warnings
        
        # Suppress output during metric initialization
        devnull = open('/dev/null', 'w')
        try:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    
                    if metric_name == "BLEU":
                        return BLEUMetric()
                    elif metric_name == "chrF":
                        return ChrFMetric()
                    elif metric_name == "TER":
                        return TERMetric()
                    elif metric_name == "ROUGE":
                        return ROUGEMetric()
                    elif metric_name == "METEOR":
                        return METEORMetric()
                    elif metric_name == "COMET":
                        return COMETMetric(
                            model_path=self.config.comet_model,
                            batch_size=self.config.batch_size,
                            gpus=self.config.gpus
                        )
                    elif metric_name == "COMET-KIWI":
                        return COMETKiwiMetric(
                            model_path=self.config.comet_kiwi_model,
                            batch_size=self.config.batch_size,
                            gpus=self.config.gpus
                        )
                    elif metric_name == "BLEURT":
                        # Fix libdevice path issue and disable XLA JIT
                        # Find CUDA installation
                        cuda_paths = [
                            '/usr/local/cuda',
                            '/opt/cuda',
                            '/usr/lib/cuda',
                            os.environ.get('CUDA_HOME', ''),
                            os.environ.get('CUDA_PATH', '')
                        ]
                        
                        cuda_path = None
                        for path in cuda_paths:
                            if path and os.path.exists(os.path.join(path, 'nvvm', 'libdevice')):
                                cuda_path = path
                                break
                        
                        if cuda_path:
                            os.environ['XLA_FLAGS'] = f'--xla_gpu_cuda_data_dir={cuda_path}'
                        
                        # Disable XLA JIT compilation as fallback
                        os.environ['TF_XLA_FLAGS'] = '--tf_xla_auto_jit=0'
                        
                        # Force CPU mode for BLEURT to avoid GPU issues
                        os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
                        
                        return BLEURTMetric(
                            checkpoint_path=self.config.bleurt_checkpoint,
                            batch_size=self.config.batch_size
                        )
        finally:
            try:
                devnull.close()
            except Exception:
                pass
        
        return None
    
    def evaluate(
        self,
        sources: List[str],
        predictions: List[str],
        references: List[str]
    ) -> Dict[str, Any]:
        """Run all metrics sequentially and return results."""
        logger.info("Starting evaluation...")
        results = {}

        # Define which metrics use GPU (neural metrics)
        gpu_metrics = {"COMET", "COMET-KIWI", "BLEURT"}

        # Execute metrics sequentially - initialize, compute, then destroy
        for metric_name in tqdm(self.config.metrics, desc="Evaluating metrics", unit="metric"):
            print(f"\nComputing {metric_name}...")
            
            # Clear GPU before loading new model
            if metric_name in gpu_metrics:
                print(f"  Clearing GPU memory before loading...")
                self._clear_gpu_memory()
            
            metric = None
            try:
                # Initialize metric
                metric = self._initialize_metric(metric_name)
                
                if metric is None:
                    logger.error(f"Failed to initialize {metric_name}")
                    results[metric_name] = {"error": "Failed to initialize metric"}
                    continue
                
                # Call the appropriate compute method based on metric type
                if metric_name == "COMET":
                    result = metric.compute(predictions=predictions, references=references, sources=sources)
                elif metric_name == "COMET-KIWI":
                    result = metric.compute(predictions=predictions, sources=sources)
                else:
                    result = metric.compute(predictions=predictions, references=references)
                
                # Verify that result is not None
                if result is None:
                    logger.error(f"{metric_name} returned None")
                    results[metric_name] = {"error": "Metric returned None"}
                # Filter out individual scores for cleaner output
                elif isinstance(result, dict):
                    filtered = {k: v for k, v in result.items() if not isinstance(v, list)}
                    results[metric_name] = filtered
                else:
                    results[metric_name] = result
                    
                print(f"✓ {metric_name} completed")

            except Exception as e:
                logger.error(f"Error computing {metric_name}: {e}")
                import traceback
                traceback.print_exc()
                results[metric_name] = {"error": str(e)}
            
            finally:
                # CRITICAL: Delete the metric object to free memory
                if metric is not None:
                    del metric
                
                # Clear GPU memory after neural metrics
                if metric_name in gpu_metrics:
                    print(f"  Clearing GPU memory after {metric_name}...")
                    self._clear_gpu_memory()
                    print(f"  GPU memory freed")

        logger.info("Evaluation completed")
        return results