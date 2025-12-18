"""Neural metrics (COMET, BLEURT)."""

from typing import Dict, List, Any
from tqdm import tqdm
from comet import load_from_checkpoint
import os
from .base import BaseMetric
import numpy as np

# ---------------------------------------------------------------------
# Local model paths
# ---------------------------------------------------------------------
LOCAL_ROBERTA_PATH = "models/xlm-roberta-large"
LOCAL_INFOXLM_PATH = "models/infoxlm-large"

# ---------------------------------------------------------------------
# Comprehensive monkeypatch for offline loading
# ---------------------------------------------------------------------
def apply_offline_patches():
    """Apply all necessary patches to force offline model loading."""
    
    # Patch 1: requests.Session.request
    try:
        import requests
        _orig_session_request = requests.Session.request

        def _session_request_local(self, method, url, *args, **kwargs):
            try:
                if isinstance(url, str) and "huggingface.co" in url:
                    if "/infoxlm-large/" in url or "infoxlm" in url:
                        base_path = LOCAL_INFOXLM_PATH
                    elif "/xlm-roberta-large/" in url:
                        base_path = LOCAL_ROBERTA_PATH
                    else:
                        return _orig_session_request(self, method, url, *args, **kwargs)
                    
                    parts = url.split("/resolve/main/")
                    if len(parts) == 2:
                        filename = parts[1].split("?")[0]
                        candidate = os.path.join(base_path, filename)
                        
                        resp = requests.Response()
                        resp.url = url
                        resp.request = type('obj', (object,), {'url': url})()
                        
                        if os.path.exists(candidate):
                            resp.status_code = 200
                            if method.upper() == "HEAD":
                                resp._content = b""
                            else:
                                with open(candidate, "rb") as fh:
                                    resp._content = fh.read()
                            resp.headers["Content-Type"] = "application/octet-stream"
                            resp.headers["Content-Length"] = str(len(resp._content))
                            return resp
                        else:
                            resp.status_code = 404
                            resp._content = b""
                            return resp
            except Exception as e:
                print(f"Request patch error: {e}")
                pass
            
            return _orig_session_request(self, method, url, *args, **kwargs)

        requests.Session.request = _session_request_local
    except Exception as e:
        print(f"Failed to patch requests: {e}")

    # Patch 2: huggingface_hub.hf_hub_download
    try:
        import huggingface_hub
        _orig_hf_hub_download = huggingface_hub.hf_hub_download

        def _hf_hub_download_local(repo_id=None, filename=None, **kwargs):
            if repo_id and filename:
                if "infoxlm" in repo_id.lower():
                    candidate = os.path.join(LOCAL_INFOXLM_PATH, filename)
                elif "xlm-roberta-large" in repo_id.lower():
                    candidate = os.path.join(LOCAL_ROBERTA_PATH, filename)
                else:
                    return _orig_hf_hub_download(repo_id=repo_id, filename=filename, **kwargs)
                
                if os.path.exists(candidate):
                    return candidate
            
            return _orig_hf_hub_download(repo_id=repo_id, filename=filename, **kwargs)

        huggingface_hub.hf_hub_download = _hf_hub_download_local
    except Exception as e:
        print(f"Failed to patch hf_hub_download: {e}")

    # Patch 3: transformers AutoConfig
    try:
        from transformers import AutoConfig
        _orig_autoconfig_fp = AutoConfig.from_pretrained

        def _autoconfig_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_autoconfig_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_autoconfig_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_autoconfig_fp(pretrained_model_name_or_path, **kwargs)

        AutoConfig.from_pretrained = _autoconfig_local
    except Exception as e:
        print(f"Failed to patch AutoConfig: {e}")

    # Patch 4: transformers AutoTokenizer
    try:
        from transformers import AutoTokenizer
        _orig_autotokenizer_fp = AutoTokenizer.from_pretrained

        def _autotokenizer_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_autotokenizer_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_autotokenizer_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_autotokenizer_fp(pretrained_model_name_or_path, **kwargs)

        AutoTokenizer.from_pretrained = _autotokenizer_local
    except Exception as e:
        print(f"Failed to patch AutoTokenizer: {e}")

    # Patch 5: transformers AutoModel
    try:
        from transformers import AutoModel
        _orig_automodel_fp = AutoModel.from_pretrained

        def _automodel_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_automodel_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_automodel_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_automodel_fp(pretrained_model_name_or_path, **kwargs)

        AutoModel.from_pretrained = _automodel_local
    except Exception as e:
        print(f"Failed to patch AutoModel: {e}")

    # Patch 6: XLMRobertaConfig specifically
    try:
        from transformers import XLMRobertaConfig
        _orig_xlmr_config_fp = XLMRobertaConfig.from_pretrained

        def _xlmr_config_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_config_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_config_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_xlmr_config_fp(pretrained_model_name_or_path, **kwargs)

        XLMRobertaConfig.from_pretrained = _xlmr_config_local
    except Exception as e:
        print(f"Failed to patch XLMRobertaConfig: {e}")

    # Patch 7: XLMRobertaTokenizer
    try:
        from transformers import XLMRobertaTokenizer
        _orig_xlmr_tok_fp = XLMRobertaTokenizer.from_pretrained

        def _xlmr_tok_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_tok_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_tok_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_xlmr_tok_fp(pretrained_model_name_or_path, **kwargs)

        XLMRobertaTokenizer.from_pretrained = _xlmr_tok_local
    except Exception as e:
        print(f"Failed to patch XLMRobertaTokenizer: {e}")

    # Patch 8: XLMRobertaTokenizerFast
    try:
        from transformers import XLMRobertaTokenizerFast
        _orig_xlmr_tokfast_fp = XLMRobertaTokenizerFast.from_pretrained

        def _xlmr_tokfast_local(pretrained_model_name_or_path, **kwargs):
            if isinstance(pretrained_model_name_or_path, str):
                model_name = pretrained_model_name_or_path.lower()
                if "infoxlm" in model_name or "microsoft/infoxlm" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_tokfast_fp(LOCAL_INFOXLM_PATH, **kwargs)
                elif "xlm-roberta-large" in model_name:
                    kwargs['local_files_only'] = True
                    return _orig_xlmr_tokfast_fp(LOCAL_ROBERTA_PATH, **kwargs)
            return _orig_xlmr_tokfast_fp(pretrained_model_name_or_path, **kwargs)

        XLMRobertaTokenizerFast.from_pretrained = _xlmr_tokfast_local
    except Exception as e:
        print(f"Failed to patch XLMRobertaTokenizerFast: {e}")

# Apply patches immediately
apply_offline_patches()

# Set environment variables for offline mode
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# ---------------------------------------------------------------------
# METRICS IMPLEMENTATION
# ---------------------------------------------------------------------
class COMETMetric(BaseMetric):
    """COMET metric (reference-based)."""
    
    def __init__(self, model_path: str = "models/wmt22-comet-da", batch_size: int = 8, gpus: int = 1):
        super().__init__("COMET")
        self.batch_size = batch_size
        self.gpus = gpus

        
        self.logger.info(f"Loading COMET model from: {model_path}")
        self.model = load_from_checkpoint(model_path)
        self.model.eval()
    
    def compute(self, predictions: List[str], references: List[str], sources: List[str]) -> Dict[str, Any]:
        self.log_computation()
        
        data = [{"src": src, "mt": pred, "ref": ref} for src, pred, ref in zip(sources, predictions, references)]
        scores = []

        for i in tqdm(range(0, len(data), self.batch_size), desc=self.name, unit="batch"):
            batch = data[i:i + self.batch_size]
            try:
                output = self.model.predict(batch, batch_size=self.batch_size,accelerator = "gpu", gpus=self.gpus)
            except Exception as e:
                self.logger.error(f"COMET predict error on batch {i}: {e}")
                continue

            batch_scores = None
            try:
                if hasattr(output, "scores"):
                    batch_scores = output.scores
                elif isinstance(output, dict) and "scores" in output:
                    batch_scores = output["scores"]
                elif isinstance(output, (list, tuple)):
                    batch_scores = list(output)
                elif isinstance(output, np.ndarray):
                    batch_scores = output.tolist()
            except Exception:
                batch_scores = None

            if not batch_scores:
                self.logger.warning(f"COMET returned no scores for batch {i}")
                continue

            try:
                scores.extend(list(batch_scores))
            except Exception as e:
                self.logger.error(f"Failed to extend scores from batch {i}: {e}")
                continue
        
        system_score = sum(scores) / len(scores) if scores else 0.0
        return {"score": system_score, "scores": scores}


class COMETKiwiMetric(BaseMetric):
    """COMET-KIWI metric (quality estimation, reference-free)"""

    def __init__(self, 
                 model_path: str = "models/wmt22-cometkiwi-da/checkpoints/model.ckpt",
                 batch_size: int = 8,
                 gpus: int = 1):
        super().__init__("COMET-KIWI")
        self.batch_size = batch_size
        self.gpus = gpus

        self.logger.info(f"Loading COMET-KIWI model from: {model_path}")
        
        # Load model with offline mode
        self.model = load_from_checkpoint(model_path)
        self.model.eval()

    def compute(self, predictions: List[str], sources: List[str]) -> Dict[str, Any]:
        self.log_computation()
        data = [{"src": src, "mt": pred} for src, pred in zip(sources, predictions)]
        scores = []
        
        for i in tqdm(range(0, len(data), self.batch_size), desc=self.name, unit="batch"):
            batch = data[i:i+self.batch_size]
            try:
               
                output = self.model.predict(batch, batch_size=self.batch_size,accelerator = "gpu", gpus=self.gpus)
            except Exception as e:
                self.logger.error(f"COMET-KIWI predict error batch {i}: {e}")
                continue

            batch_scores = None
            if output is None:
                continue
            elif hasattr(output, "scores") and output.scores is not None:
                batch_scores = output.scores
            elif isinstance(output, dict):
                if "seg_scores" in output:
                    batch_scores = output["seg_scores"]
                elif "scores" in output:
                    batch_scores = output["scores"]
                elif "system_score" in output:
                    batch_scores = [output["system_score"]] * len(batch)
            elif isinstance(output, (list, tuple, np.ndarray)):
                batch_scores = list(output)

            if batch_scores:
                scores.extend(batch_scores)

        system_score = float(sum(scores)) / float(len(scores)) if scores else 0.0
        return {"score": system_score, "scores": scores}


class BLEURTMetric(BaseMetric):
    """BLEURT metric."""

    def __init__(self, checkpoint_path: str, batch_size: int = 0, use_gpu: bool = False):
        super().__init__("BLEURT")
        self.batch_size = batch_size

     

        self.logger.info(f"Loading BLEURT from: {checkpoint_path}")
        from bleurt import score as bleurt_score
        self.scorer = bleurt_score.BleurtScorer(checkpoint_path)

    def compute(self, predictions: List[str], references: List[str]) -> Dict[str, Any]:
        self.log_computation()

        if self.batch_size and self.batch_size > 0:
            scores = []
            for i in tqdm(range(0, len(predictions), self.batch_size), desc=self.name, unit="batch"):
                batch_preds = predictions[i:i + self.batch_size]
                batch_refs = references[i:i + self.batch_size]
                batch_scores = self.scorer.score(references=batch_refs, candidates=batch_preds)
                for j, sc in enumerate(batch_scores):
                    global_idx = i + j
                    self.logger.info(f"BLEURT line {global_idx}: {sc}")
                scores.extend(batch_scores)
        else:
            scores = self.scorer.score(references=references, candidates=predictions)
            for idx, sc in enumerate(scores):
                self.logger.info(f"BLEURT line {idx}: {sc}")

        system_score = sum(scores) / len(scores) if scores else 0.0
        return {"score": system_score, "scores": scores}