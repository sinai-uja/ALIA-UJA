import os, sys
from contextlib import nullcontext

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from huggingface_hub.constants import HF_HUB_OFFLINE
print("env HF_HUB_OFFLINE=",  os.getenv("HF_HUB_OFFLINE"))
print("HF_HUB_OFFLINE const=", HF_HUB_OFFLINE)

import json
import gc
import math
sys.path.append(os.path.realpath("./"))
from sentence_transformers.model_card import SentenceTransformerModelCardData
from utils.utils_alia import load_config, RichArgumentParser
from utils.utils_alia import load_jsonl

import mteb, torch
from mteb.abstasks.retrieval import AbsTaskRetrieval
from mteb.abstasks.task_metadata import TaskMetadata
from mteb.cache import ResultCache
from sentence_transformers import CrossEncoder
from typing import Dict, List, Mapping, Optional, Any, Tuple
import polars as pl
from itertools import product
from datasets import Dataset, DatasetDict
from transformers import AutoTokenizer, AutoModelForCausalLM, AutoModelForSequenceClassification, AutoModel, is_torch_npu_available
from vllm import LLM, SamplingParams
from vllm.distributed.parallel_state import destroy_model_parallel
from vllm.inputs.data import TokensPrompt


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
DEVICE: str        = "cuda" if torch.cuda.is_available() else "cpu"
TORCH_DTYPE: torch.dtype = torch.float16
logging.info(f"Runtime → device={DEVICE!r}, dtype={TORCH_DTYPE}")

cache = ResultCache()

QWEN_RERANKER_MODEL_NAME = "Qwen/Qwen3-Reranker-0.6B"

class _ModelStub:
    def __init__(self, name_or_path: str):
        self.name_or_path = name_or_path

        class _CfgStub:
            def __init__(self, name_or_path):
                self.name_or_path = name_or_path
                self._commit_hash = None
            def __getattr__(self, item):
                return None   # silently return None for any unexpected attribute

        self.config = _CfgStub(name_or_path)

    def eval(self):
        return self
    def parameters(self):
        return iter([])

class Qwen3RerankerInferenceModel(CrossEncoder):
    """Implementación oficial de QwenLM para reranking vía vLLM.
    
    Fuente: https://github.com/QwenLM/Qwen3-Embedding/blob/main/evaluation/qwen3_reranker_model.py
    Adaptación: local_files_only=True en AutoTokenizer para modo offline.
    """

    def __init__(self, model_name, instruction="Given the user query, retrieval the relevant passages", **kwargs):
        # self.lm = AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True, torch_dtype=torch.float32)
        number_of_gpu = torch.cuda.device_count()
        self.instruction = instruction
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
        self.tokenizer.padding_side = "left"
        self.tokenizer.pad_token = self.tokenizer.eos_token
        self.suffix = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self.max_length = 8192 # kwargs.get('max_length', 8192)

        object.__setattr__(self, "model", _ModelStub(model_name))  
        self.model_card_data = SentenceTransformerModelCardData(
                    model_name=model_name,
                )

        self.suffix_tokens = self.tokenizer.encode(self.suffix, add_special_tokens=False)
        # Cache commonly used token IDs
        self.true_token = self.tokenizer("yes", add_special_tokens=False).input_ids[0]
        self.false_token = self.tokenizer("no", add_special_tokens=False).input_ids[0]
        self.sampling_params = SamplingParams(
            temperature=0,
            top_p=0.95,
            max_tokens=1,
            logprobs=20,
            allowed_token_ids=[self.true_token, self.false_token],
        )
        self.lm = LLM(
            model=model_name,
            tensor_parallel_size=number_of_gpu,
            max_model_len=8192,
            enable_prefix_caching=True,
            enforce_eager=True,                 # Deshabilita compilación de CUDA graphs (evita cuelgue en V100)
            distributed_executor_backend='mp',  # 'mp' (multiprocessing) es el backend correcto para 1 GPU
            gpu_memory_utilization=0.8,
        )

    def eval(self):
        """No-op: vLLM manages its own inference mode."""
        return self
    def format_instruction(self, instruction, query, doc):
        if isinstance(query, tuple):
            instruction = query[0]
            query = query[1]
        text = [
            {"role": "system", "content": "Judge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\"."},
            {"role": "user", "content": f"<Instruct>: {instruction}\n\n<Query>: {query}\n\n<Document>: {doc}"}
        ]
        return text

    def process_batch(self, pairs, **kwargs):
        messages = [self.format_instruction(self.instruction, query, doc) for query, doc in pairs]
        messages = self.tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False, enable_thinking=False
        )
        messages = [ele[:self.max_length] + self.suffix_tokens for ele in messages] # type: ignore
        messages = [TokensPrompt(prompt_token_ids=ele) for ele in messages]
        outputs = self.lm.generate(messages, self.sampling_params, use_tqdm=False)
        scores = []
        for i in range(len(outputs)):
            final_logits = outputs[i].outputs[0].logprobs[-1] # type: ignore
            token_count = len(outputs[i].outputs[0].token_ids)
            if self.true_token not in final_logits:
                true_logit = -10
            else:
                true_logit = final_logits[self.true_token].logprob
            if self.false_token not in final_logits:
                false_logit = -10
            else:
                false_logit = final_logits[self.false_token].logprob
            true_score = math.exp(true_logit)
            false_score = math.exp(false_logit)
            score = true_score / (true_score + false_score)
            scores.append(score)
        return scores

    def start(self):
        pass

    def predict(
        self,
        sentences: list[tuple[str, str]] | list[list[str]],
        batch_size: int = 0,
        show_progress_bar: bool | None = False,
        num_workers: int = 1,
        activation_fct=None,
        apply_softmax: bool | None = False,
        convert_to_numpy: bool = True,
        convert_to_tensor: bool = False,
        **kwargs
    ) -> list[torch.Tensor]:
        scores = self.process_batch(sentences)
        return scores

    def stop(self):
        destroy_model_parallel()

# =============================================================================================================
class ALIAAbsTaskReranking(AbsTaskRetrieval):
    
    """Task dinámica para Reranking con cross-encoder.

    Hereda de AbsTaskRetrieval (la API unificada de MTEB v2) con
    metadata.type="Reranking". La diferencia clave respecto a Retrieval
    es el campo ``top_ranked``: un dict[query_id, list[doc_id]] que indica
    qué documentos candidatos debe re-ordenar el cross-encoder para cada
    query. Sin este campo, ``SearchCrossEncoderWrapper`` falla.

    """

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
                domain=self.domain, 
                model_name=self.model_name, 
                eval_set=self.eval_dataset
            ),
            description=self.config["TaskMetadata"]["description"].format(
                domain=self.domain, 
                model_name=self.model_name, 
                eval_set=self.eval_dataset
            ),
            reference=self.config["TaskMetadata"]["reference"],
            type="Reranking",
            category=self.config["TaskMetadata"]["category"],
            eval_splits=self.config["TaskMetadata"]["eval_splits"],
            eval_langs=self.config["TaskMetadata"]["eval_langs"],
            main_score=self.config["TaskMetadata"]["main_score"],
            dataset=self.config["TaskMetadata"]["dataset"],
            task_subtypes=self.config["available-eval-sets-task-mapping"][self.eval_dataset].get(
                "task_subtypes", []
            ),
        )

    def load_data(self, **kwargs):
        """Carga los datos de evaluación en formato MTEB v2 para Reranking.

        Construye objetos ``Dataset`` para corpus y queries, un dict de
        ``relevant_docs`` y un dict ``top_ranked`` que lista los documentos candidatos por query.

        El resultado se almacena en::

            self.dataset["default"]["test"] = {
                "corpus":        Dataset(id, text, title),
                "queries":       Dataset(id, text),
                "relevant_docs": {query_id: {doc_id: 1, ...}},
                "top_ranked":    {query_id: [doc_id, ...]},
            }
        """
        
        if self.data_loaded:
            return

        # ===================================================================
        # Modo 1: Dataset "general" → archivos pre-construidos (parquet/json)
        # ===================================================================
        
        dest_dir_eval = os.path.join(
            self.config["paths"]["path-root-data"],
            self.config["paths"]["path-dir-data"].format(domain=self.domain),
        )
        if os.path.exists(dest_dir_eval):
                                        
            dataset_dir = os.path.join(dest_dir_eval, self.eval_dataset)
            logging.info(f"Cargando dataset general para Reranking desde {dataset_dir}")

            try:
                self.dataset["default"]["test"]["corpus"] = Dataset.from_parquet(f"{dataset_dir}/corpus.parquet") # type: ignore
                self.dataset["default"]["test"]["queries"] = Dataset.from_parquet(f"{dataset_dir}/queries.parquet") # type: ignore

                with open(f"{dataset_dir}/relevant_docs.json", "r", encoding="utf-8") as f:
                    self.dataset["default"]["test"]["relevant_docs"] = json.load(f)
                with open(f"{dataset_dir}/top_ranked.json", "r", encoding="utf-8") as f:
                    self.dataset["default"]["test"]["top_ranked"]    = json.load(f)

                n_queries = len(self.dataset["default"]["test"]["queries"]) # type: ignore
                n_corpus  = len(self.dataset["default"]["test"]["corpus"]) # type: ignore
                n_top     = len(self.dataset["default"]["test"]["top_ranked"]) # type: ignore
                logging.info(
                    f"Carga completada desde {dataset_dir}: "
                    f"queries={n_queries}, corpus={n_corpus}, top_ranked={n_top}"
                )
                self.data_loaded = True
                return

            except FileNotFoundError as e:
                logging.error(f"Archivo no encontrado en {dataset_dir}: {e}")
                raise
            except Exception as e:
                logging.exception(f"Error cargando dataset general desde {dataset_dir}: {e}")
                raise
        
               
        # ==================================================================
        # Modo 2: Dataset con fichero único → JSONL + top_ranked artificial
        # ==================================================================
        import random
        
        dest_path_eval = os.path.join(
            self.config["paths"]["path-root-data"],
            self.config["paths"]["path-dir-data"].format(domain=self.domain),
            f"{self.eval_dataset}.jsonl",
        )
        
        df = load_jsonl(dest_path_eval)

        try:
            logging.info(f"Cargando dataset de dominio para Reranking desde {dest_path_eval} - se va a construir un top_ranked artificial")

            # ------------------------------------------------------------------
            # Comprobar estructura del dataset (igual que biencoder)
            # ------------------------------------------------------------------
            expected_columns_A = ["source", "id", "query", "passage"]
            expected_columns_B = ["source_id", "id_document", "id_chunk", "query", "passage"]
            if set(expected_columns_B).issubset(set(df.columns)):
                logging.info(f"Dataset tiene estructura tipo B con columnas {expected_columns_B}.")
                df = df.rename({"source_id": "source", "id_chunk": "id"})
            elif set(expected_columns_A).issubset(set(df.columns)):
                logging.info(f"Dataset tiene estructura tipo A con columnas {expected_columns_A}.")
            else:
                logging.error(
                    f"El dataset no tiene la estructura esperada. "
                    f"Columnas encontradas: {df.columns}"
                )
                raise ValueError(
                    "El dataset no tiene la estructura esperada para formatear los datos."
                )

            # Column names (con fallback desde config)
            src_col   = self.config.get("source_column", "source")
            id_col    = self.config.get("text_id_column", "id")
            query_col = self.config.get("query_column", "query")
            text_col  = self.config.get("text_column", "passage")

            logging.info(f"Formateando dataset para Reranking. Total registros: {df.height}")

            # ------------------------------------------------------------------
            # Construir listas para Dataset.from_dict
            # ------------------------------------------------------------------
            corpus_ids:    List[str] = []
            corpus_texts:  List[str] = []
            corpus_titles: List[str] = []
            query_ids:     List[str] = []
            query_texts:   List[str] = []
            relevant_docs: Dict[str, Dict[str, int]] = {}
            query_to_relevant_doc: Dict[str, str] = {}
            seen_corpus_ids: set = set()

            for i, row in enumerate(df.iter_rows(named=True)):
                try:
                    doc_id   = str(row.get(id_col, i))
                    query_id = f"q_{i}"

                    # Corpus: cada doc_id único se añade una sola vez
                    if doc_id not in seen_corpus_ids:
                        corpus_ids.append(doc_id)
                        corpus_texts.append(row.get(text_col, ""))
                        corpus_titles.append(row.get(src_col, ""))
                        seen_corpus_ids.add(doc_id)

                    # Queries
                    query_ids.append(query_id)
                    query_texts.append(row.get(query_col, ""))

                    # Relevancia: cada query tiene un único doc relevante
                    relevant_docs[query_id] = {doc_id: 1}
                    query_to_relevant_doc[query_id] = doc_id

                except Exception as e:
                    logging.exception(f"Error procesando fila {i} del dataset: {e}")
                    continue

            # ------------------------------------------------------------------
            # top_ranked: doc relevante + hasta 100 distractores aleatorios.
            # El doc relevante siempre va primero para garantizar que está en
            # la lista de candidatos; el cross-encoder re-ordena por score.
            # ------------------------------------------------------------------
            TOP_K_DISTRACTORS = 100
            all_corpus_ids = list(seen_corpus_ids)
            top_ranked: Dict[str, List[str]] = {}

            rng = random.Random(self.config.get("Evaluator", {}).get("seed", 42))

            for qid in query_ids:
                relevant_id = query_to_relevant_doc[qid]
                # Distractores: todos los docs del corpus excepto el relevante
                distractor_pool = [cid for cid in all_corpus_ids if cid != relevant_id]
                n_distractors = min(TOP_K_DISTRACTORS, len(distractor_pool))
                distractors = rng.sample(distractor_pool, n_distractors)
                # Primer elemento = relevante, resto = distractores (aleatorios)
                candidates = [relevant_id] + distractors
                # Mezclar para que la posición del relevante no sea predecible
                rng.shuffle(candidates)
                top_ranked[qid] = candidates

            # ------------------------------------------------------------------
            # Crear HF Datasets (formato v2 de MTEB)
            # ------------------------------------------------------------------
            corpus_dataset = Dataset.from_dict({
                "id":    corpus_ids,
                "text":  corpus_texts,
                "title": corpus_titles,
            })

            queries_dataset = Dataset.from_dict({
                "id":   query_ids,
                "text": query_texts,
            })

            # ------------------------------------------------------------------
            # Almacenar directamente en formato v2 (self.dataset[subset][split])
            # ------------------------------------------------------------------
            self.dataset["default"]["test"]["corpus"] = corpus_dataset
            self.dataset["default"]["test"]["queries"] = queries_dataset
            self.dataset["default"]["test"]["relevant_docs"] = relevant_docs
            self.dataset["default"]["test"]["top_ranked"] = top_ranked

            avg_candidates = sum(len(v) for v in top_ranked.values()) / max(len(top_ranked), 1)
            logging.info(
                f"Carga completada desde {os.path.basename(dest_path_eval)}: "
                f"queries={len(query_ids)}, corpus={len(corpus_ids)}, "
                f"top_ranked={len(top_ranked)} (media candidatos/query={avg_candidates:.0f})"
            )
            self.data_loaded = True

        except FileNotFoundError:
            logging.error(f"Archivo de evaluación no encontrado: {dest_path_eval}")
            raise
        except Exception as e:
            logging.exception(f"Error leyendo {os.path.basename(dest_path_eval)}: {e}")
            raise


# =============================================================================================================
class EvaluationCrossEncoder:
    """Evaluador reutilizable con cross-encoder: un único objeto gestiona múltiples runs."""

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

        self._model_cache: Dict[str, CrossEncoder] = {}

        if clear_mteb_cache:
            cache.clear_cache()
            logging.info("Caché de MTEB limpiada (clear_mteb_cache=True).")

        logging.info("EvaluationCrossEncoder inicializado.")

    # -------- helpers de paths --------

    def build_model_path(self, model_name: str, model_path: str = "") -> str:
        if model_path:
            return model_path

        input_model_path = os.path.join(
            self.config["paths"]["path-dir-models-crossencoder"],
            model_name
        )
        
        if not os.path.exists(input_model_path):
            logging.warning(f"Modelo no encontrado en path principal: {input_model_path}")
            input_model_path = os.path.join(
                self.config["paths"]["path-dir-models-crossencoder-alternative"], model_name  # [CE]
            )

        if not os.path.exists(input_model_path):
            raise FileNotFoundError(f"Modelo no encontrado: {model_name}")

        return input_model_path

    def build_prediction_dir(self, domain: str, prediction_dir: str = "") -> str:
        if prediction_dir:
            return prediction_dir
        prediction_dir = os.path.join(
            self.config["paths"]["path-root-evaluation"],
            self.config["paths"]["path-dir-predictions"].format(domain=domain),
        )
        try:
            os.makedirs(prediction_dir, exist_ok=True)
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
                task_type="reranking",
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
                eval_set=eval_dataset
            )
        )

    # -------- construcción de task/model --------

    def build_task(self, domain: str, model_name: str, eval_dataset: str):
        
        logging.info(f"🎯 Tipo de tarea para '{eval_dataset}': Reranking (cross-encoder)")
        return ALIAAbsTaskReranking(
            config=self.config,
            domain=domain,
            model_name=model_name,
            eval_dataset=eval_dataset,
        )

    def load_model(
        self,
        model_name: str,
        model_path: str = "",
        reuse_if_cached: bool = True,
        force_rebuild_crossencoder: bool = False, 
    ) -> CrossEncoder:
        input_model_path = self.build_model_path(
            model_name=model_name, model_path=model_path
        )
        max_seq_length = self.config["Evaluator"].get("max_seq_length", 512)

        cache_key = input_model_path
        if reuse_if_cached and cache_key in self._model_cache:
            logging.info(f"Reutilizando modelo cacheado: {os.path.basename(input_model_path)}")
            return self._model_cache[cache_key]

        logging.info(f"Cargando cross-encoder desde: {input_model_path}")

        # CrossEncoder no admite model_kwargs ni prompts; usa device y max_length directamente.
        try:
            if model_name == QWEN_RERANKER_MODEL_NAME:
                logging.info(
                    "Usando implementación Qwen3RerankerInferenceModel para "
                    f"{QWEN_RERANKER_MODEL_NAME}"
                )
                model = Qwen3RerankerInferenceModel(
                    model_name=input_model_path,
                    max_length=max_seq_length,
                )
            else:
                model = CrossEncoder(
                    model_name_or_path=input_model_path,
                    max_length=max_seq_length,
                    device=DEVICE,
                    model_kwargs={"torch_dtype": TORCH_DTYPE},
                    trust_remote_code=True,
                    local_files_only=True,
                )
        except Exception:
            logging.exception(
                f"Error construyendo CrossEncoder desde {input_model_path}"
            )
            raise

        # --- Fix: asegurar que el tokenizer tiene pad_token (para CrossEncoder estándar) ---
        if hasattr(model, "tokenizer") and model.tokenizer.pad_token is None:
            if model.tokenizer.eos_token is not None:
                model.tokenizer.pad_token = model.tokenizer.eos_token
                logging.warning(
                    f"pad_token no definido → asignado eos_token"
                    f"('{model.tokenizer.eos_token}')"
                )
            elif model.tokenizer.unk_token is not None:
                model.tokenizer.pad_token = model.tokenizer.unk_token
                logging.warning(
                    f"pad_token no definido → asignado unk_token"
                    f"('{model.tokenizer.unk_token}')"
                )
            elif hasattr(model, "model"):
                model.tokenizer.add_special_tokens({"pad_token": "[PAD]"})
                model.model.resize_token_embeddings(len(model.tokenizer))
                logging.warning(
                    "pad_token no definido y sin eos/unk → añadido '[PAD]'"
                )

        logging.info(
            f"CrossEncoder listo | dtype={TORCH_DTYPE} | device={DEVICE} | "
            f"max_length={max_seq_length}"
        )

        self._model_cache[cache_key] = model
        return model

    # -------- evaluación + persistencia --------

    def evaluate(
        self,
        model: CrossEncoder,                                   # [CE] tipo CrossEncoder
        task,
        prediction_dir: str,
        encode_kwargs: Optional[Dict[str, Any]] = None,
    ):
        encode_kwargs = encode_kwargs or {}
        logging.info(
            f"Ejecutando mteb.evaluate | encode_kwargs={encode_kwargs} | "
            f"prediction_dir={prediction_dir}"
        )
        if hasattr(model, "model"):
            model.model.eval()

        try:
            evaluation = mteb.MTEB(tasks=[task])
            eval_splits = evaluation.tasks[0].metadata.eval_splits

            results = []
            for split in eval_splits:
                with torch.no_grad():
                    autocast_ctx = (
                        torch.autocast(device_type="cuda", dtype=TORCH_DTYPE)
                        if DEVICE == "cuda"
                        else nullcontext()
                    )
                    with autocast_ctx:
                        result = evaluation.run(
                            model,
                            eval_splits=[split],
                            # top_k=100,
                            save_predictions=True,
                            output_folder=prediction_dir,
                            encode_kwargs=encode_kwargs,
                        )
                        results.extend(result)

            logging.info("Evaluación completada correctamente.")
            return results

        except Exception:
            logging.exception(f"Error durante mteb.MTEB.run en {prediction_dir}")
            raise
        # try:
        #     with torch.no_grad():
        #         autocast_ctx = (
        #             torch.autocast(device_type="cuda", dtype=TORCH_DTYPE)
        #             if DEVICE == "cuda"
        #             else nullcontext()
        #         )
        #         with autocast_ctx:
        #             results = mteb.evaluate(
        #                 model=model,
        #                 tasks=[task],
        #                 encode_kwargs=encode_kwargs, # type: ignore
        #                 prediction_folder=prediction_dir,
        #                 overwrite_strategy="always",
        #                 cache=cache,
        #             )
        #     logging.info("Evaluación completada correctamente.")
        #     return results
        # except Exception:
        #     logging.exception(f"Error durante mteb.evaluate en {prediction_dir}")
        #     raise

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
            out["NDCG"][k] = metrics.get(f"ndcg{s}") or metrics.get(f"ndcg_at_{k}")
            out["MAP"][k] = metrics.get(f"map{s}") or metrics.get(f"map_at_{k}")
            out["MRR"][k] = metrics.get(f"mrr{s}") or metrics.get(f"mrr_at_{k}")
            out["Recall"][k] = metrics.get(f"recall{s}") or metrics.get(f"recall_at_{k}")
            out["Precision"][k] = metrics.get(f"precision{s}") or metrics.get(f"precision_at_{k}")

        return out

    def save_results_csv(
        self,
        jsonl_path: str,
        csv_path: str,
        task_type: str = "Reranking",
        ks: Optional[List[int]] = None,
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
            cols = ["metric"] + [f"k{k}" for k in ks]
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
        force_rebuild_crossencoder: bool = False,
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
                self.save_results_csv(
                    result_path,
                    result_path.replace(".jsonl", ".csv"),
                    task_type="Reranking",
                    ks=[1, 3, 5, 10, 20],
                )
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
                force_rebuild_crossencoder=force_rebuild_crossencoder,
            )

            prediction_dir = self.build_prediction_dir(
                domain=domain, prediction_dir=prediction_dir
            )

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

            self.save_results_csv(
                result_path,
                result_path.replace(".jsonl", ".csv"),
                task_type="Reranking",
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
            description="Evaluación CrossEncoder: Reranking"   # [CE]
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
            model_list_path = os.path.join(os.path.dirname(__file__), "crossencoder_model_list.txt")
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

        available_datasets: Dict[str, List[str]] = self.config["available-eval-sets"]["Reranking"]
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

    mteb_evaluator = EvaluationCrossEncoder(clear_mteb_cache=False)

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
                if DEVICE == "cuda":
                    torch.cuda.empty_cache()

    logging.info("=" * 80)
    logging.info("Evaluación completada.")