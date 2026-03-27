import os, sys
from contextlib import nullcontext
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from huggingface_hub.constants import HF_HUB_OFFLINE
print("env HF_HUB_OFFLINE=",  os.getenv("HF_HUB_OFFLINE"))
print("HF_HUB_OFFLINE const=", HF_HUB_OFFLINE)

import json
sys.path.append(os.path.realpath("./"))

from utils.utils_alia import load_config, RichArgumentParser
from utils.utils_alia import load_jsonl

import mteb, torch
from mteb.abstasks.retrieval import AbsTaskRetrieval
from mteb.abstasks.sts      import AbsTaskSTS
from mteb.abstasks.task_metadata import TaskMetadata
from mteb.cache import ResultCache
from sentence_transformers import SentenceTransformer
from typing import Dict, List, Mapping, Optional, Any, Tuple
import polars as pl
from itertools import product
from datasets import Dataset, DatasetDict

# =============================================================================================================
# Logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# =============================================================================================================
# Nuestras GPUs (RTX) solo soportan float16, NO bfloat16.
# DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"
# TORCH_DTYPE: torch.dtype = torch.float16
# logging.info(f"Runtime → device={DEVICE!r}, dtype={TORCH_DTYPE}")

# Detectar dtype óptimo según arquitectura GPU
DEVICE: str = "cuda" if torch.cuda.is_available() else "cpu"

if DEVICE == "cuda":
    gpu_name = torch.cuda.get_device_name(0).upper()
    # Ampere (A100, A6000…) y Tesla (V100…) soportan bfloat16 de forma nativa
    if any(prefix in gpu_name for prefix in ("TESLA", "A100", "A10", "A6000", "A40", "A30", "A800")):
        TORCH_DTYPE: torch.dtype = torch.float32
    else:
        # RTX (20xx, 30xx, 40xx…) y resto → float16
        TORCH_DTYPE = torch.float32
else:
    TORCH_DTYPE = torch.float32

logging.info(f"Runtime → device={DEVICE!r}, gpu={torch.cuda.get_device_name(0) if DEVICE == 'cuda' else 'N/A'!r}, dtype={TORCH_DTYPE}")
cache = ResultCache()

# =============================================================================================================
class ALIAAbsTaskRetrieval(AbsTaskRetrieval):
    
    """Task dinámica para Retrieval: Tipo QA y STS."""

    def __init__(
        self,
        config: Mapping,
        domain: str,
        model_name: str,
        eval_dataset: str,
        **kwargs,
    ):
        self.config       = config
        self.domain       = domain
        self.model_name   = model_name
        self.eval_dataset = eval_dataset
        self.metadata     = self._create_metadata()
        super().__init__(**kwargs)

    def _create_metadata(self) -> TaskMetadata:
        return TaskMetadata(
            name=self.config["TaskMetadata"]["name"].format(
                domain=self.domain, model_name=self.model_name, eval_set=self.eval_dataset
            ),
            description=self.config["TaskMetadata"]["description"].format(
                domain=self.domain, model_name=self.model_name, eval_set=self.eval_dataset
            ),
            reference=self.config["TaskMetadata"]["reference"],
            type=self.config["available-eval-sets-task-mapping"][self.eval_dataset]["task_type"],
            category=self.config["TaskMetadata"]["category"],
            eval_splits=self.config["TaskMetadata"]["eval_splits"],
            eval_langs=self.config["TaskMetadata"]["eval_langs"],
            main_score=self.config["TaskMetadata"]["main_score"],
            dataset=self.config["TaskMetadata"]["dataset"],
            task_subtypes=self.config["available-eval-sets-task-mapping"][self.eval_dataset]["task_subtypes"],
        )

    @staticmethod
    def _format_for_retrieval(
        df: pl.DataFrame,
        src_col: str,
        id_col: str,
        query_col: str,
        text_col: str,
    ) -> Tuple[Dict, Dict, Dict]:
        ids     = df[id_col].cast(pl.Utf8).to_list()
        queries = df[query_col].cast(pl.Utf8).to_list()
        texts   = df[text_col].cast(pl.Utf8).to_list()
        titles  = df[src_col].cast(pl.Utf8).to_list()

        corpus_dict:        Dict[str, Dict[str, str]]       = {}
        queries_dict:       Dict[str, str]                  = {}
        relevant_docs_dict: Dict[str, Dict[str, int]]       = {}

        for i, (doc_id, query_text, text, title) in enumerate(
            zip(ids, queries, texts, titles)
        ):
            query_id = f"q_{i}"
            if doc_id not in corpus_dict:
                corpus_dict[doc_id] = {"text": text or "", "title": title or ""}
            queries_dict[query_id]       = query_text or ""
            relevant_docs_dict[query_id] = {doc_id: 1}

        return (
            {"test": queries_dict},
            {"test": corpus_dict},
            {"test": relevant_docs_dict},
        )

    def load_data(self, **kwargs):
        """Carga los datos de evaluación usando la librería datasets (formato v2 de MTEB).
        
        Construye directamente objetos Dataset para corpus y queries, y almacena
        en self.dataset["default"]["test"] (RetrievalSplitData), evitando la
        conversión v1→v2 que realiza convert_v1_dataset_format_to_v2.
        """
        if self.data_loaded:
            return

        dest_path_eval = os.path.join(
            self.config["paths"]["path-root-data"], 
            self.config["paths"]["path-dir-data"].format(
                domain=self.domain
            ),
            f"{self.eval_dataset}.jsonl"
        )

        try:
            df = load_jsonl(dest_path_eval)
            logging.info(f"Cargando dataset para Retrieval/Reranking desde {dest_path_eval}")

            # Comprobar estructura del dataset
            expected_columns_A = ["source", "id", "query", "passage"]  # target columns
            expected_columns_B = ["source_id", "id_document", "id_chunk", "query", "passage"]
            expected_columns_C = ["source_id", "id_document", "id_passage", "query", "passage"]
            if set(expected_columns_B).issubset(set(df.columns)):
                logging.info(f"Dataset tiene estructura tipo B con columnas {expected_columns_B}.")
                df = df.rename({"source_id": "source", "id_chunk": "id"})
            elif set(expected_columns_C).issubset(set(df.columns)):
                logging.info(f"Dataset tiene estructura tipo C con columnas {expected_columns_C}.")
                df = df.rename({"source_id": "source", "id_passage": "id"})
            elif set(expected_columns_A).issubset(set(df.columns)):
                logging.info(f"Dataset tiene estructura tipo A con columnas {expected_columns_A}.")
            else:
                logging.error(f"El dataset no tiene la estructura esperada. Columnas encontradas: {df.columns}")
                raise ValueError("El dataset no tiene la estructura esperada para formatear los datos.")

            # Column names (con fallback)
            src_col = self.config.get("source_column", "source")
            id_col = self.config.get("text_id_column", "id")
            query_col = self.config.get("query_column", "query")
            text_col = self.config.get("text_column", "passage")

            logging.info(f"Formateando dataset para Retrieval. Total registros: {df.height}")

            # Construir listas para Dataset.from_dict
            corpus_ids = []
            corpus_texts = []
            corpus_titles = []
            query_ids = []
            query_texts = []
            relevant_docs = {}
            seen_corpus_ids = set()

            for i, row in enumerate(df.iter_rows(named=True)):
                try:
                    doc_id = str(row.get(id_col, i))
                    query_id = f"q_{i}"

                    if doc_id not in seen_corpus_ids:
                        corpus_ids.append(doc_id)
                        corpus_texts.append(row.get(text_col, ""))
                        corpus_titles.append(row.get(src_col, ""))
                        seen_corpus_ids.add(doc_id)

                    query_ids.append(query_id)
                    query_texts.append(row.get(query_col, ""))
                    relevant_docs[query_id] = {doc_id: 1}

                except Exception as e:
                    logging.exception(f"Error procesando fila {i} del dataset: {e}")
                    continue

            # Crear HF Datasets (formato v2 de MTEB)
            corpus_dataset = Dataset.from_dict({
                "id": corpus_ids,
                "text": corpus_texts,
                "title": corpus_titles,
            })

            queries_dataset = Dataset.from_dict({
                "id": query_ids,
                "text": query_texts,
            })

            # Almacenar directamente en formato v2 (self.dataset[subset][split])
            self.dataset["default"]["test"]["corpus"] = corpus_dataset
            self.dataset["default"]["test"]["queries"] = queries_dataset
            self.dataset["default"]["test"]["relevant_docs"] = relevant_docs

            logging.info(f"Carga completada desde {os.path.basename(dest_path_eval)}: queries={len(query_ids)}, corpus={len(corpus_ids)}")
            self.data_loaded = True

        except FileNotFoundError:
            logging.error(f"Archivo de triplets no encontrado: {dest_path_eval}")
            raise
        except Exception as e:
            logging.exception(f"Error leyendo {os.path.basename(dest_path_eval)}: {e}")
            raise



# =============================================================================================================
class ALIAAbsTaskSTS(AbsTaskSTS):
    
    """Task dinámica para Semantic Textual Similarity (STS)."""

    min_score: float = 0
    max_score: float = 1

    def __init__(
        self,
        config: Mapping,
        domain: str,
        model_name: str,
        eval_dataset: str,
        **kwargs,
    ):
        self.config       = config
        self.domain       = domain
        self.model_name   = model_name
        self.eval_dataset = eval_dataset
        self.min_score    = config.get("sts_min_score", 0)
        self.max_score    = config.get("sts_max_score", 1)
        self.metadata     = self._create_metadata()
        super().__init__(**kwargs)

    def _create_metadata(self) -> TaskMetadata:
        return TaskMetadata(
            name=self.config["TaskMetadata"]["name"].format(
                domain=self.domain, model_name=self.model_name, eval_set=self.eval_dataset
            ),
            description=self.config["TaskMetadata"]["description"].format(
                domain=self.domain, model_name=self.model_name, eval_set=self.eval_dataset
            ),
            reference=self.config["TaskMetadata"]["reference"],
            type="STS",
            category=self.config["TaskMetadata"]["category"],
            eval_splits=self.config["TaskMetadata"]["eval_splits"],
            eval_langs=self.config["TaskMetadata"]["eval_langs"],
            main_score="cosine_spearman",
            dataset=self.config["TaskMetadata"]["dataset"],
            task_subtypes=self.config["available-eval-sets-task-mapping"][self.eval_dataset].get(
                "task_subtypes", []
            ),
        )

    def load_data(self, **kwargs) -> None:
        if self.data_loaded:
            return

        dest_path_eval = os.path.join(
            self.config["paths"]["path-root-data"],
            self.config["paths"]["path-dir-data"].format(domain=self.domain),
            f"{self.eval_dataset}.jsonl",
        )

        try:
            df = load_jsonl(dest_path_eval)
            logging.info(f"Cargando dataset STS desde {dest_path_eval}")

            sent1_col = self.config.get("sentence1_column", "sentence1")
            sent2_col = self.config.get("sentence2_column", "sentence2")
            score_col = self.config.get("score_column",     "score")

            expected = {sent1_col, sent2_col, score_col}
            if not expected.issubset(set(df.columns)):
                raise ValueError(
                    f"Columnas STS esperadas: {expected}. Encontradas: {df.columns}"
                )

            self.dataset = DatasetDict({  # type: ignore[assignment]
                "test": Dataset.from_dict({
                    "sentence1": df[sent1_col].to_list(),
                    "sentence2": df[sent2_col].to_list(),
                    "score":     [float(s) for s in df[score_col].to_list()],
                })
            })
            logging.info(
                f"STS cargado: {len(self.dataset['test'])} pares "  # type: ignore[index]
                f"desde {os.path.basename(dest_path_eval)}"
            )
            self.data_loaded = True

        except FileNotFoundError:
            logging.error(f"Archivo no encontrado: {dest_path_eval}")
            raise
        except Exception:
            logging.exception(f"Error leyendo {os.path.basename(dest_path_eval)}")
            raise


# =============================================================================================================
class EvaluationBiEncoder:
    
    """Evaluador reutilizable: un único objeto gestiona múltiples runs."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        clear_mteb_cache: bool = False,
    ):
        config_file = config_path or os.path.join(os.path.dirname(__file__), "config.yaml")
        try:
            self.config = load_config(config_file)
            logging.info("Configuración cargada correctamente.")
        except Exception:
            raise

        self._model_cache: Dict[str, SentenceTransformer] = {}

        if clear_mteb_cache:
            cache.clear_cache()
            logging.info("Caché de MTEB limpiada (clear_mteb_cache=True).")

        logging.info("EvaluationBiEncoder inicializado.")

    # -------- helpers de paths --------

    def build_model_paths(self, model_name: str, model_path: str = "") -> Tuple[str, str]:
        if model_path:
            return model_path, model_path

        save_model_path  = os.path.join(
            self.config["paths"]["path-dir-models-sentence-transformers"], model_name
        )
        input_model_path = os.path.join(
            self.config["paths"]["path-dir-models-biencoders"], model_name
        )
        if not os.path.exists(input_model_path):
            logging.warning(f"Modelo no encontrado en path principal: {input_model_path}")
            del input_model_path  # Liberar memoria
            input_model_path = os.path.join(
                self.config["paths"]["path-dir-models-biencoders-alternative"], model_name
            )

        if os.path.exists(save_model_path):
            logging.info(f"Reutilizando ST existente: {save_model_path}")
            return save_model_path, save_model_path

        if "sentence-transformers" in input_model_path:
            logging.info(f"Reutilizando ST alternativo: {input_model_path}")
            return input_model_path, input_model_path

        if not os.path.exists(input_model_path):
            raise FileNotFoundError(f"Modelo no encontrado: {model_name}")

        logging.info(f"Biencoder → ST: {input_model_path} → {save_model_path}")
        return input_model_path, save_model_path

    def build_prediction_dir(self, 
                             domain: str, 
                             prediction_dir: str = "",
                             model_name: str = ""
                            ) -> str:
        if prediction_dir:
            return prediction_dir
        prediction_dir = os.path.join(
            self.config["paths"]["path-root-evaluation"],
            self.config["paths"]["path-dir-predictions"].format(
                task_type="retrieval",
                domain=domain, 
                model_name=model_name.replace("/", "_")
            )
        )
        try:
            os.makedirs(prediction_dir, exist_ok=True)
            Path(prediction_dir).parent.mkdir(parents=True, exist_ok=True)
            Path(prediction_dir).mkdir(parents=True, exist_ok=True)
            logging.info(f"Directorio de predicciones listo: {prediction_dir}")
        except Exception:
            logging.exception(f"Error creando directorio de predicciones {prediction_dir}")
            raise
        return prediction_dir

    def build_result_jsonl_path(
        self,
        model_name: str,
        domain: str,
        eval_dataset: str,
        result_path: str = "",
    ) -> str:
        if result_path:
            return result_path
        result_dir = os.path.join(
            self.config["paths"]["path-root-evaluation"],
            self.config["paths"]["path-dir-results"].format(
                task_type="retrieval",
                domain=domain, 
                model_name=model_name.replace("/", "_")
            )
        )
        try:
            os.makedirs(result_dir, exist_ok=True)
        except Exception:
            logging.exception(f"Error creando directorio de resultados {result_dir}")
            raise
        return os.path.join(
            result_dir,
            self.config["paths"]["path-file-result"].format(
                domain=domain,
                model_name=model_name.replace("/", "_"),
                eval_set=eval_dataset,
            ),
        )

    # -------- construcción de task/model --------

    def build_task(self, domain: str, model_name: str, eval_dataset: str):
        task_type = (
            self.config["available-eval-sets-task-mapping"]
            .get(eval_dataset, {})
            .get("task_type", "Retrieval")
        )
        logging.info(f"Tipo de tarea para '{eval_dataset}': {task_type}")
        if task_type == "STS":
            return ALIAAbsTaskSTS(
                config=self.config,
                domain=domain,
                model_name=model_name,
                eval_dataset=eval_dataset,
            )
        return ALIAAbsTaskRetrieval(
            config=self.config,
            domain=domain,
            model_name=model_name,
            eval_dataset=eval_dataset,
        )

    @staticmethod
    def _is_mrbert_model(model_name: str) -> bool:
        return "mrbert" in model_name.lower()

    def _resolve_original_model_path(self, model_name: str) -> str:
        primary_path = os.path.join(
            self.config["paths"]["path-dir-models-biencoders"], model_name
        )
        if os.path.exists(primary_path):
            return primary_path

        alternative_path = os.path.join(
            self.config["paths"]["path-dir-models-biencoders-alternative"], model_name
        )
        if os.path.exists(alternative_path):
            return alternative_path

        return ""

    def _load_mrbert_sentence_transformer(
        self,
        input_model_path: str,
        max_seq_length: int = 2048,
    ) -> SentenceTransformer:
        
        from sentence_transformers import models as st_models

        word_embedding_model = st_models.Transformer(
            input_model_path,
            max_seq_length=max_seq_length,
            model_args={
                "local_files_only": True
            },
            tokenizer_args={
                "local_files_only": True,
                "model_max_length": max_seq_length,
            },
        )

        pooling_model = st_models.Pooling(
            word_embedding_model.get_word_embedding_dimension()
        )
        model = SentenceTransformer(
            modules=[word_embedding_model, pooling_model],
            device=DEVICE,
        )
        
        if DEVICE == "cuda":
            model.to(dtype=TORCH_DTYPE)
        
        return model

    def _get_model_configuration(self, model_name: str) -> Dict[str, Any]:
        model_cfgs = self.config.get("model-configurations", {})
        return (
            model_cfgs.get(model_name)
            or model_cfgs.get(model_name.replace("/", "_"))
            or {}
        )

    def load_model(
        self,
        model_name: str,
        model_path: str = "",
        reuse_if_cached: bool = True,
        force_rebuild_sentence_transformer: bool = True,
    ) -> SentenceTransformer:
        input_model_path, save_model_path = self.build_model_paths(
            model_name=model_name, model_path=model_path
        )

        is_mrbert = self._is_mrbert_model(model_name)
        same_model_path = os.path.abspath(input_model_path) == os.path.abspath(save_model_path)

        if force_rebuild_sentence_transformer:
            logging.info(
                "force_rebuild_sentence_transformer=True detectado -> "
                "borrando el modelo cacheado para forzar reconstrucción desde el biencoder original."
            )
            if save_model_path in self._model_cache:
                del self._model_cache[save_model_path]
                logging.info(f"Modelo cacheado eliminado: {save_model_path}")

        max_seq_length = self.config["Evaluator"].get("max_seq_length", 512)
        logging.info(f"[DEBUG] -> max_seq_length={max_seq_length}")

        cache_key = save_model_path if same_model_path else input_model_path
        if (
            reuse_if_cached
            and cache_key in self._model_cache
            and not force_rebuild_sentence_transformer
        ):
            logging.info(f"Reutilizando modelo cacheado: {os.path.basename(input_model_path)}")
            return self._model_cache[cache_key]

        logging.info(f"Cargando modelo desde: {input_model_path}")

        model_config = self._get_model_configuration(model_name)
        model_prompts = model_config.get("prompts", {})
        if not model_config:
            logging.warning(
                f"No se encontraron configuraciones específicas para el modelo '{model_name}' en "
                "'model-configurations'. Asegúrate de que el modelo esté definido allí para usar "
                "prompts personalizados."
            )

        st_kwargs = dict(
            local_files_only=True,
            device=DEVICE,
            model_kwargs={"torch_dtype": TORCH_DTYPE},
            tokenizer_kwargs={"model_max_length": max_seq_length},
            prompts=model_prompts,
        )

        force_sentence_transformer = bool(
            self.config["Evaluator"].get("force_sentence_transformer", True)
        )

        if not same_model_path:
            # No existe ST transformado todavía: construir y guardar en save_model_path
            try:
                logging.info(
                    "No existe versión sentence-transformers transformada. "
                    f"Construyendo desde: {input_model_path}"
                )
                if is_mrbert:
                    model = self._load_mrbert_sentence_transformer(
                        input_model_path=input_model_path,
                        # max_seq_length=max_seq_length,
                    )
                else:
                    model = SentenceTransformer(input_model_path, **st_kwargs)  # type: ignore
            except Exception:
                logging.exception(
                    f"Error construyendo SentenceTransformer desde {input_model_path}"
                )
                raise

            try:
                logging.info(f"Guardando modelo transformado en: {save_model_path}")
                model.save(save_model_path)
                del model
                torch.cuda.empty_cache()
            except Exception:
                logging.exception(f"Error guardando modelo en {save_model_path}")
                # No es fatal: el modelo en RAM sigue siendo válido.

        if is_mrbert:
            model = self._load_mrbert_sentence_transformer(
                input_model_path=input_model_path,
                # max_seq_length=max_seq_length,
            )
        else:
            model = SentenceTransformer(input_model_path, **st_kwargs)  # type: ignore
            model.max_seq_length = max_seq_length
        logging.info(
            f"Modelo listo | dtype={TORCH_DTYPE} | device={DEVICE} | "
            f"max_seq_length={model.max_seq_length}"
        )

        if model.prompts and not model_prompts:
            logging.info(f"El modelo trae prompts propios: {model.prompts}")
        elif not model.prompts and not model_prompts:
            logging.warning(
                f"El modelo '{model_name}' no tiene prompts configurados. "
                "Para modelos como BGE-M3 o E5, esto puede reducir significativamente "
                "el rendimiento en Retrieval. Considera añadir 'model_prompts' en config.yaml."
            )

        self._model_cache[cache_key] = model
        return model

    # -------- evaluación + persistencia --------

    def evaluate(
        self,
        model: SentenceTransformer,
        task,
        prediction_dir: str,
        encode_kwargs: Optional[Dict[str, Any]] = None
    ):
        encode_kwargs = encode_kwargs or {}
        logging.info(
            f"Ejecutando mteb.evaluate | encode_kwargs={encode_kwargs} | "
            f"prediction_dir={prediction_dir}"
        )
        model.eval()
        try:
            with torch.no_grad():
                # torch.autocast garantiza fp16/bf16 en GPU
                autocast_ctx = (
                    torch.autocast(device_type="cuda", dtype=TORCH_DTYPE)
                    if DEVICE == "cuda"
                    else nullcontext()
                )
                with autocast_ctx:
                    results = mteb.evaluate(
                        model=model,
                        tasks=[task],
                        encode_kwargs=encode_kwargs,  # type: ignore
                        prediction_folder=prediction_dir,
                        overwrite_strategy="always",
                        cache=cache,
                    )
            logging.info("Evaluación completada correctamente.")
            return results
        except Exception:
            logging.exception(f"Error durante mteb.evaluate en {prediction_dir}")
            raise

    def _extract_metrics_from_scores(
        self, scores_obj: Dict[str, Any], ks: List[int]
    ) -> Dict[str, Dict[int, Optional[float]]]:
        out: Dict[str, Dict[int, Optional[float]]] = {
            "NDCG": {}, "MAP": {}, "MRR": {}, "Recall": {}, "Precision": {},
        }
        if not scores_obj:
            return out
        try:
            test_entries = scores_obj.get("test", [])
            if not test_entries:
                return out
            metrics = test_entries[0]
        except Exception:
            return out

        for k in ks:
            s = f"_at_{k}"
            # [OPT] Eliminada la tercera cláusula `or` duplicada del NDCG original.
            out["NDCG"][k]      = metrics.get(f"ndcg{s}")      or metrics.get(f"ndcg_at_{k}")
            out["MAP"][k]       = metrics.get(f"map{s}")        or metrics.get(f"map_at_{k}")
            out["MRR"][k]       = metrics.get(f"mrr{s}")        or metrics.get(f"mrr_at_{k}")
            out["Recall"][k]    = metrics.get(f"recall{s}")     or metrics.get(f"recall_at_{k}")
            out["Precision"][k] = metrics.get(f"precision{s}")  or metrics.get(f"precision_at_{k}")

        return out

    def _extract_metrics_from_scores_sts(
        self, scores_obj: Dict[str, Any]
    ) -> Dict[str, Optional[float]]:
        sts_metric_keys = [
            "cosine_spearman", "cosine_pearson",
            "euclidean_spearman", "euclidean_pearson",
            "manhattan_spearman", "manhattan_pearson",
            "spearman", "pearson",
        ]
        sts_metrics: Dict[str, Optional[float]] = {k: None for k in sts_metric_keys}
        if not scores_obj:
            return sts_metrics
        try:
            test_entries = scores_obj.get("test", [])
            if not test_entries:
                return sts_metrics
            metrics = test_entries[0]
        except Exception:
            return sts_metrics
        for key in sts_metric_keys:
            sts_metrics[key] = metrics.get(key)
        return sts_metrics

    def save_results_csv(
        self,
        jsonl_path: str,
        csv_path: str,
        task_type: str = "Retrieval",
        ks: Optional[List[int]] = None,  # [OPT] mutable default corregido
    ) -> None:
        ks = ks or [1, 3, 5, 10, 20]
        logging.info(f"Procesando resultados: {jsonl_path}")
        try:
            rows: List[Dict] = []
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        logging.exception(f"JSON inválido en {jsonl_path} línea {i}")
                        continue

                    scores_obj = obj.get("scores")
                    if task_type == "STS":
                        for metric_name, value in self._extract_metrics_from_scores_sts(
                            scores_obj
                        ).items():
                            rows.append({
                                "metric": metric_name,
                                "value":  round(value, 4) if value is not None else "",
                            })
                    else:
                        for metric_name, kdict in self._extract_metrics_from_scores(
                            scores_obj, ks
                        ).items():
                            row: Dict[str, Any] = {"metric": metric_name}
                            for k in ks:
                                v = kdict.get(k)
                                row[f"k{k}"] = round(v, 4) if v is not None else ""
                            rows.append(row)

            if not rows:
                logging.warning(f"Sin métricas válidas en {jsonl_path}")
                return

            df   = pl.DataFrame(rows)
            cols = ["metric", "value"] if task_type == "STS" else ["metric"] + [f"k{k}" for k in ks]
            try:
                df = df.select(cols)
            except Exception:
                pass

            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            df.write_csv(csv_path)
            logging.info(f"CSV escrito: {csv_path} ({df.height} filas)")

        except FileNotFoundError:
            logging.error(f"Archivo no encontrado: {jsonl_path}")
            raise
        except Exception:
            logging.exception(f"Error procesando {jsonl_path}")
            raise

    def save_results_jsonl(self, results, result_jsonl: str) -> str:
        out_dir = os.path.dirname(result_jsonl)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            logging.exception(f"Error creando directorio {out_dir}")
            raise

        logging.info(f"Guardando resultados en: {result_jsonl}")
        try:
            written = 0
            with open(result_jsonl, "w", encoding="utf-8") as f:
                for r in results:
                    f.write(
                        json.dumps(
                            {
                                "task_name":       getattr(r, "task_name", None),
                                "main_score":      r.get_score() if hasattr(r, "get_score") else None,
                                "scores":          getattr(r, "scores", None),
                                "evaluation_time": getattr(r, "evaluation_time", None),
                            },
                            ensure_ascii=False,
                            default=str,
                        ) + "\n"
                    )
                    written += 1
            logging.info(f"Guardados {written} resultados en: {result_jsonl}")
            return result_jsonl
        except Exception:
            logging.exception(f"Error escribiendo en {result_jsonl}")
            raise

    def print_results(self, results) -> None:
        if not results:
            logging.warning("No hay resultados para mostrar.")
            return
        for r in results:
            score = r.get_score() if hasattr(r, "get_score") else None
            score_str = f"{score:.4f}" if score is not None else "N/A"
            logging.info(f"🏅 {r.task_name}: main_score={score_str}")

    # -------- pipeline --------

    def run(
        self,
        *,
        domain: str,
        model_name: str,
        eval_dataset: str = "",
        model_path: str = "",
        prediction_dir: str = "",
        result_jsonl: str = "",
        reuse_model: bool = True,
        force_rebuild_sentence_transformer: bool = False,
        force_run: bool = False,
    ) -> None:
        sanitized_name = model_name.replace("/", "_")
        try:
            result_path = self.build_result_jsonl_path(
                model_name=sanitized_name,
                domain=domain,
                eval_dataset=eval_dataset,
                result_path=result_jsonl,
            )
            if os.path.exists(result_path) and not force_run:
                logging.info(
                    f"Resultados ya existen: domain={domain}, "
                    f"model={sanitized_name}, eval_dataset={eval_dataset} → {result_path}"
                )
                return
            elif force_run:
                logging.info(
                    f"force_run=True → se sobrescribirán resultados existentes "
                    f"para domain={domain}, model={sanitized_name}, eval_dataset={eval_dataset}"
                )
                try: os.remove(result_path)
                except Exception: pass

            task = self.build_task(
                domain=domain,
                model_name=sanitized_name,
                eval_dataset=eval_dataset,
            )
            logging.info(f"Task construida para domain={domain}, model={model_name}")

            model = self.load_model(
                model_name=model_name,
                model_path=model_path,
                reuse_if_cached=reuse_model,
                force_rebuild_sentence_transformer=force_rebuild_sentence_transformer,
            )

            prediction_dir = self.build_prediction_dir(
                domain=domain
            )

            # Limpiar predicciones anteriores (podrían estar corruptas por ejecuciones interrumpidas)
            task_name = task.metadata.name
            if os.path.isdir(prediction_dir):
                for fname in os.listdir(prediction_dir):
                    if task_name in fname and fname.endswith(".json"):
                        pred_file = os.path.join(prediction_dir, fname)
                        try:
                            os.remove(pred_file)
                            logging.info(f"🗑️ Predicción anterior eliminada: {pred_file}")
                        except Exception:
                            logging.warning(f"No se pudo eliminar predicción anterior: {pred_file}")

            try:
                encode_kwargs = self.config["model-configurations"][model_name].get("encode_kwargs", {})
            except KeyError:
                encode_kwargs = self.config["model-configurations"]["DEFAULT"].get("encode_kwargs", {})
                
            results = self.evaluate(
                model=model,
                task=task,
                prediction_dir=prediction_dir,
                encode_kwargs=encode_kwargs,
            )

            self.print_results(results)
            self.save_results_jsonl(results, result_path)

            task_type = (
                self.config["available-eval-sets-task-mapping"]
                .get(eval_dataset, {})
                .get("task_type", "Retrieval")
            )
            self.save_results_csv(
                result_path,
                result_path.replace(".jsonl", ".csv"),
                task_type=task_type,
                ks=[1, 3, 5, 10, 20],
            )
            logging.info("Run completado.")

        except Exception:
            logging.exception(
                f"Error durante run(domain={domain}, "
                f"model_name={sanitized_name}, eval_dataset={eval_dataset})"
            )
            raise


# =============================================================================================================
class ALIAEvaluatorManager:

    def __init__(self, config_path: str = ""):
        self.config = load_config(config_path)

    def get_args(self) -> Tuple[List[str], List[str], Dict[str, List[str]], bool]:
        parser = RichArgumentParser(
            description="Evaluación BiEncoder: Retrieval, STS y Reranking"
        )
        parser.add_argument("--model_name", required=True, type=str, default="all")
        parser.add_argument("--dataset",    required=True, type=str, default="all")
        parser.add_argument("--domain",     required=True, type=str, default="all")
        parser.add_argument("--force_run",  required=False, type=bool, default=False)
        parser.add_argument("--env",  required=False, type=str, default="")
        args = parser.parse_args()

        logging.info(
            f"Argumentos: model_name={args.model_name}, "
            f"dataset={args.dataset}, domain={args.domain}, force_run={args.force_run}"
        )

        if args.model_name == "all":
            model_list_path = os.path.join(os.path.dirname(__file__), "biencoder_model_list.txt")
            logging.info(f"Leyendo lista de modelos desde: {model_list_path}")
            try:
                with open(model_list_path, "r", encoding="utf-8") as f:
                    model_names = [line.strip() for line in f if line.strip()]
                logging.info(f"Leídos {len(model_names)} modelos.")
            except FileNotFoundError:
                logging.error(f"No se encontró {model_list_path}")
                raise
            except Exception:
                logging.exception(f"Error leyendo {model_list_path}")
                raise
        else:
            model_names = [args.model_name]

        domains: List[str] = (
            self.config["available-domains"]
            if args.domain == "all"
            else [args.domain]
        )

        available_datasets: Dict[str, List[str]] = self.config["available-eval-sets"]["Retrieval"]
        if args.dataset == "all":
            datasets: Dict[str, List[str]] = {
                d: available_datasets.get(d, []) for d in domains
            }
            for d in domains:
                if not datasets.get(d):
                    logging.warning(f"Sin datasets disponibles para el dominio '{d}'")
        else:
            datasets = {d: [args.dataset] for d in domains}

        logging.info(f"Modelos: {model_names}")
        for d in domains:
            logging.info(f"  Dominio '{d}': {datasets.get(d, [])}")
            
        return domains, model_names, datasets, args.force_run


# =============================================================================================================
# MAIN
if __name__ == "__main__":

    manager = ALIAEvaluatorManager(
        config_path=os.path.join(os.path.dirname(__file__), "config.yaml")
    )
    domains, model_names, datasets, force_run = manager.get_args()

    mteb_evaluator = EvaluationBiEncoder(clear_mteb_cache=False)

    logging.info("Iniciando evaluación de modelos...")
    for domain, model_name in product(domains, model_names):
        for dataset in datasets.get(domain, []):
            logging.info("=" * 80)
            logging.info(
                f"Evaluando dataset='{dataset}' | domain='{domain}' | model='{model_name}'"
            )
            try:
                mteb_evaluator.run(
                    domain=domain,
                    model_name=model_name,
                    eval_dataset=dataset,
                    force_run=force_run
                )
            except Exception:
                logging.exception(
                    f"Error evaluando dataset='{dataset}', "
                    f"domain='{domain}', model='{model_name}'"
                )
                continue
            finally:
                # [OPT] Liberar VRAM después de CADA evaluación individual,
                # no solo al finalizar todos los datasets de un modelo.
                if DEVICE == "cuda":
                    torch.cuda.empty_cache()

    logging.info("=" * 80)
    logging.info("Evaluación completada.")
