import os, sys, json, shutil
import argparse
import logging
import multiprocessing
import polars as pl
from tqdm import tqdm
import gzip, gc

# ============= CONFIGURACIÓN OFFLINE MODE =============

current_dir = os.getcwd()
DATATROVE_MODELS_DIR = os.path.abspath(os.path.join(current_dir, "utils", "datatrove"))

# Verificar que el directorio existe
if not os.path.exists(DATATROVE_MODELS_DIR):
    print("=" * 80, file=sys.stderr)
    print(" ERROR: No se encuentra el directorio de modelos", file=sys.stderr)
    print(f"   Ruta esperada: {DATATROVE_MODELS_DIR}", file=sys.stderr)
    print(f"   Directorio actual: {current_dir}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    sys.exit(1)

os.environ["HF_HOME"] = DATATROVE_MODELS_DIR

remote_url = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"

from huggingface_hub import cached_assets_path

asset_dir = cached_assets_path(
    library_name="datatrove", namespace="lid", subfolder="ft176"
)
os.makedirs(asset_dir, exist_ok=True)

# Nombre EXACTO que usa datatrove: https:__ + strip + replace 
filename = remote_url.replace("://", ":__").replace(
    "/", "_"
)  # "https:__dl.fbaipublicfiles.com_fasttext_supervised-models_lid.176.bin"
model_path_dst = os.path.join(asset_dir, filename)
completed_file = model_path_dst + ".completed"

# Tu modelo fuente (ajusta si está en lid/ft176/lid.176.bin)
model_path_src = os.path.join(DATATROVE_MODELS_DIR, "lid", "ft176", "lid.176.bin")

# Copia directa (no symlink)
if not os.path.exists(model_path_dst):
    if os.path.exists(model_path_src):
        shutil.copy2(model_path_src, model_path_dst)
        logging.info(f"✅ Copiado: {model_path_dst}")
    else:
        logging.error(f" No existe fuente: {model_path_src}. Descárgalo manualmente.")
        sys.exit(1)

if not os.path.exists(completed_file):
    open(completed_file, "a").close()
    logging.info(f"✅ .completed: {completed_file}")

logging.info("🚀 Offline OK")
logging.info(f"asset_dir  : {os.path.basename(asset_dir)}")
logging.info(f"model_dst  : {os.path.basename(model_path_dst)}")
logging.info(f"completed  : {os.path.basename(completed_file)}")

# ======================================================

# Configurar el método de inicio antes de importar datatrove (Best Practice)
if __name__ == "__main__":
    try:
        multiprocessing.set_start_method("forkserver", force=True)
    except RuntimeError:
        pass

# ======================================================================

from datatrove.executor.local import LocalPipelineExecutor
# from datatrove.pipeline.extractors import Trafilatura
from datatrove.pipeline.readers import JsonlReader
from datatrove.pipeline.writers.jsonl import JsonlWriter
from datatrove.pipeline.filters import (
    GopherQualityFilter,
    GopherRepetitionFilter,
    LanguageFilter,
    FineWebQualityFilter,
)
from datatrove.pipeline.dedup import (
    MinhashDedupSignature,
    MinhashDedupBuckets,
    MinhashDedupCluster,
    MinhashDedupFilter,
)
from datatrove.pipeline.dedup.minhash import MinhashConfig
from datatrove.pipeline.formatters import (
    FTFYFormatter,
    PIIFormatter,
    SymbolLinesFormatter,
)
from datatrove.utils.hashing import HashConfig

# ======================================================================

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_parquet, sink_parquet, sink_jsonl, ALIACorporaUtils

try:
    from scripts.corpora.corpora_base import CorporaStep
except ImportError:
    from corpora_base import CorporaStep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")


# ======================================================


class CorporaDatatrove(CorporaStep):
    def __init__(
        self,
        name: str,
        domain: str,
        version: int = -1,
        tasks: int = 25,
        force: bool = False,
    ):
        super().__init__(name, domain, version)
        self.tasks = tasks

    def get_paths(self):
        paths = self._get_base_paths("datatrove")
        config = self.paths_config
        name = self.name
        version = self.version
        domain = self.domain

        path_dir_parts_parquet = os.path.join(
            paths["path-dir-corpus"], config["path-dir-parts-parquet"]
        )
        path_dir_parts_jsonl = os.path.join(
            paths["path-dir-corpus"], config["path-dir-parts-jsonl"]
        )
        output_path_dir_datatrove = os.path.join(
            paths["path-dir-corpus"], config["path-dir-datatrove"]
        )
        output_path_dir_datatrove_clean = os.path.join(
            paths["path-dir-corpus"], config["path-dir-datatrove-clean"]
        )
        output_path_file_datatrove_parquet = os.path.join(
            paths["path-dir-corpus"],
            config["path-file-corpus-datatrove"].format(
                domain=domain, name=name, format="parquet"
            )
            if version == -1
            else config["path-file-corpus-datatrove-version"].format(
                domain=domain, name=name, version=version, format="parquet"
            ),
        )
        output_path_file_datatrove_jsonl = os.path.join(
            paths["path-dir-corpus"],
            config["path-file-corpus-datatrove"].format(
                domain=domain, name=name, format="jsonl"
            )
            if version == -1
            else config["path-file-corpus-datatrove-version"].format(
                domain=domain, name=name, version=version, format="jsonl"
            ),
        )

        paths.update(
            {
                "path-dir-parts-parquet": path_dir_parts_parquet,
                "path-dir-parts-jsonl": path_dir_parts_jsonl,
                "output-path-dir-datatrove": output_path_dir_datatrove,
                "output-path-dir-datatrove-clean": output_path_dir_datatrove_clean,
                "output-path-file-datatrove-parquet": output_path_file_datatrove_parquet,
                "output-path-file-datatrove-jsonl": output_path_file_datatrove_jsonl,
            }
        )
        return paths

    def merge_jsonl_to_parquet(self):
        """Une los JSONL (salida de DataTrove) en un único parquet y jsonl."""

        logging.info('-'*30)
        logging.info(' UNIFICAR CORPUS DATATROVE ')
        logging.info('-'*30)

        # 1. Leer archivos limpios generados por datatrove
        logging.info(
            f"Leyendo archivos de: {self.paths['output-path-dir-datatrove-clean']}"
        )
        if not os.path.exists(self.paths["output-path-dir-datatrove-clean"]):
            logging.error(
                f"La carpeta no existe: {self.paths['output-path-dir-datatrove-clean']}"
            )
            return
        files = [
            f
            for f in os.listdir(self.paths["output-path-dir-datatrove-clean"])
            if f.endswith(".jsonl.gz")
        ]
        if not files:
            logging.error(
                f"No se encontraron archivos .jsonl.gz en: {self.paths['output-path-dir-datatrove-clean']}"
            )
            return

        # 2. Leer y concatenar
        dataframes = []
        # Usamos tqdm para barra de progreso
        for filename in tqdm(files, desc="Leyendo JSONL GZ"):
            full_path = os.path.join(
                self.paths["output-path-dir-datatrove-clean"], filename
            )
            try:
                with gzip.open(full_path, "rt", encoding="utf-8") as f:
                    # Leemos línea a línea para evitar errores de memoria masivos si el jsonl es gigante
                    json_list = [json.loads(line) for line in f]

                if json_list:
                    df = pl.DataFrame(json_list)
                    dataframes.append(df)
            except Exception as e:
                logging.error(f"Error leyendo {filename}: {e}")
        if not dataframes:
            logging.error("No se pudo leer ningún archivo o la carpeta está vacía.")
            return

        # 3. Concatenar todos los DataFrames
        corpus_datatrove: pl.DataFrame = pl.concat(dataframes)
        if corpus_datatrove is None or corpus_datatrove.is_empty():
            logging.error("No se pudo leer ningún archivo o la carpeta está vacía.")
            return

        # 4. Guardar corpus limpio con datatrove
        logging.info(
            f"Guardando corpus limpio con datatrove en: {os.path.basename(self.paths['output-path-file-datatrove-parquet'])}"
        )
        sink_parquet(corpus_datatrove, self.paths["output-path-file-datatrove-parquet"])
        logging.info(
            f"Guardando corpus limpio con datatrove en: {os.path.basename(self.paths['output-path-file-datatrove-jsonl'])}"
        )
        sink_jsonl(corpus_datatrove, self.paths["output-path-file-datatrove-jsonl"])

        # Limpieza explícita
        del corpus_datatrove
        gc.collect()

    def step_language_filter(self, input_path, output_base, cfg):
        """Paso 1: Filtrado de idioma."""
        logging.info(">>> Iniciando Paso 1: Filtrado de Idioma")

        step_output = os.path.join(output_base, "01.es")
        excluded_output = os.path.join(output_base, "01.filtered-out")

        pipeline = [
            JsonlReader(input_path, glob_pattern="*.jsonl"),
            # Trafilatura(favour_precision=True, timeout=1),
            LanguageFilter(
                language_threshold=cfg["language_score"],
                languages=("es"),
                exclusion_writer=JsonlWriter(excluded_output),
            ),
            JsonlWriter(step_output),
        ]

        LocalPipelineExecutor(
            pipeline=pipeline,
            tasks=self.tasks,
            logging_dir=os.path.join(output_base, "logs/01_language"),
        ).run()

        return step_output

    def step_deduplication(self, input_path, output_base, cfg):
        """Paso 2: Deduplicación MinHash (4 sub-etapas)."""
        logging.info(">>> Iniciando Paso 2: Deduplicación MinHash")

        # Rutas intermedias
        sig_path = os.path.join(output_base, "minhash", "signatures")
        buckets_path = os.path.join(output_base, "minhash", "buckets")
        remove_ids = os.path.join(output_base, "minhash", "remove_ids")
        dedup_output = os.path.join(output_base, "02.deduplicated")

        minhash_cfg = MinhashConfig(
            hash_config=HashConfig(hash_fc="xxhash", precision=64),
            num_buckets=cfg.get(
                "minhash_buckets", 25
            ),  # Parametrizable desde yaml o default
            hashes_per_bucket=cfg.get("minhash_hashes", 12),
            n_grams=cfg.get("minhash_ngrams", 5),
        )

        # 2.1 Firmas
        logging.info("  > 2.1 Signatures")
        LocalPipelineExecutor(
            [
                JsonlReader(input_path),
                MinhashDedupSignature(
                    output_folder=sig_path, config=minhash_cfg, language="es"
                ),
            ],
            tasks=self.tasks,
            logging_dir=os.path.join(output_base, "logs/mh1"),
        ).run()

        # 2.2 Buckets
        logging.info("  > 2.2 Buckets")
        LocalPipelineExecutor(
            [
                MinhashDedupBuckets(
                    input_folder=sig_path,
                    output_folder=buckets_path,
                    config=minhash_cfg,
                )
            ],
            tasks=self.tasks,
            logging_dir=os.path.join(output_base, "logs/mh2"),
        ).run()

        # 2.3 Cluster (Normalmente single-threaded o low task count por la naturaleza del clustering)
        logging.info("  > 2.3 Cluster")
        LocalPipelineExecutor(
            [
                MinhashDedupCluster(
                    input_folder=buckets_path,
                    output_folder=remove_ids,
                    config=minhash_cfg,
                )
            ],
            tasks=1,
            logging_dir=os.path.join(output_base, "logs/mh3"),
        ).run()

        # 2.4 Filtro Final
        logging.info("  > 2.4 Filter")
        LocalPipelineExecutor(
            [
                JsonlReader(input_path),
                MinhashDedupFilter(
                    input_folder=remove_ids,
                    exclusion_writer=JsonlWriter(
                        os.path.join(output_base, "02.removed_duplicates")
                    ),
                ),
                JsonlWriter(dedup_output),
            ],
            tasks=self.tasks,
            logging_dir=os.path.join(output_base, "logs/mh4"),
        ).run()

        return dedup_output

    def step_quality_filter(self, input_path, output_base, output_dir, cfg):
        """Paso 3: Filtros de calidad y formateo final."""
        logging.info(">>> Iniciando Paso 3: Filtros de Calidad y Formato")

        pipeline = [
            JsonlReader(input_path),
            GopherRepetitionFilter(
                language="es",
                dup_line_frac=cfg["gopher_repetition_filter"]["dup_line_frac"],
                top_n_grams=cfg["gopher_repetition_filter"]["top_n_grams"],
                dup_n_grams=cfg["gopher_repetition_filter"]["dup_n_grams"],
                exclusion_writer=JsonlWriter(
                    os.path.join(output_base, "03.removed_gopherrep")
                ),
            ),
            FineWebQualityFilter(
                language="es",
                char_duplicates_ratio=cfg["fineweb_quality_filter"][
                    "char_duplicates_ratio"
                ],
                line_punct_thr=cfg["fineweb_quality_filter"]["line_punct_thr"],
                new_line_ratio=cfg["fineweb_quality_filter"]["new_line_ratio"],
                short_line_thr=cfg["fineweb_quality_filter"].get("short_line_thr", 0.67), # Métrica añadida por patrimonio
                exclusion_writer=JsonlWriter(
                    os.path.join(output_base, "03.removed_fwqlty")
                ),
            ),
            GopherQualityFilter(
                language="es",
                min_doc_words= cfg["gopher_quality_filter"]["min_doc_words"],
                max_doc_words= cfg["gopher_quality_filter"]["max_doc_words"],
                max_avg_word_length=cfg["gopher_quality_filter"]["max_avg_word_length"],
                min_avg_word_length=cfg["gopher_quality_filter"]["min_avg_word_length"],
                stop_words=cfg["gopher_quality_filter"]["stopwords"],
                max_non_alpha_words_ratio=cfg["gopher_quality_filter"]["max_non_alpha_words_ratio"],
                min_stop_words=cfg["gopher_quality_filter"]["min_stop_words"],
                exclusion_writer=JsonlWriter(
                    os.path.join(output_base, "03.removed_gopherqual")
                ),
            ),
            FTFYFormatter(),
            PIIFormatter(),
            SymbolLinesFormatter(symbols_to_remove=["|"]),
            JsonlWriter(output_dir),
        ]

        LocalPipelineExecutor(
            pipeline=pipeline,
            tasks=self.tasks,
            logging_dir=os.path.join(output_base, "logs/final"),
        ).run()

        return output_dir

    def run(self):
        paths = self.paths
        config = self.full_config
        name = self.name

        print(f"--- Datatrove Curation Pipeline ---")
        print(f"Corpus: {name} | Dominio: {self.domain} | Versión: {self.version}")
        print(f"Entrada: {os.path.basename(paths['path-dir-parts-jsonl'])}")
        print(f"Salida:  {os.path.basename(paths['output-path-dir-datatrove'])}")
        print(f"Tasks:   {self.tasks}")
        print("-" * 40)

        os.makedirs(paths["output-path-dir-datatrove"], exist_ok=True)

        if os.path.exists(paths["output-path-file-datatrove-parquet"]):
            if not os.path.exists(paths["output-path-file-datatrove-jsonl"]):
                logging.warning(
                    f"El corpus enriched parquet '{name}' ya existe, pero no el JSONL. Generando JSONL..."
                )
                # Convertir Parquet a JSONL
                df = load_parquet(paths["output-path-file-datatrove-parquet"])
                sink_jsonl(df, paths["output-path-file-datatrove-jsonl"])
                try:
                    os.chmod(paths["output-path-file-datatrove-jsonl"], 0o777)
                except Exception as e:
                    pass
                logging.info(
                    f"✅ Corpus JSONL guardado en: {paths['output-path-file-datatrove-jsonl']}"
                )
            logging.info("El corpus datatrove ya existe.")
            # (*) Contar tokens y actualizar info
            ALIACorporaUtils.count_corpus_tokens(
                input_path_corpus=paths[
                    "output-path-file-datatrove-parquet"
                ],
                output_path_file_token_count_csv=paths["stats-path-file-count"],
            )
            ALIACorporaUtils.update_corpus_info(
                path_file_info_json=paths["path-file-info"],
                input_path_file_token_count_csv=paths["stats-path-file-count"],
                step="datatrove",
            )
            return

        # 3. Ejecución del Pipeline Secuencial

        # Paso 1: Filtro de Idioma
        path_after_lang = self.step_language_filter(
            paths["path-dir-parts-jsonl"],
            paths["output-path-dir-datatrove"],
            config["datatrove"]["language-filter"],
        )

        # Paso 2: Deduplicación
        path_after_dedup = self.step_deduplication(
            path_after_lang,
            paths["output-path-dir-datatrove"],
            config["datatrove"]["deduplication"],
        )

        # Paso 3: Calidad Final
        self.step_quality_filter(
            path_after_dedup,
            paths["output-path-dir-datatrove"],
            paths["output-path-dir-datatrove-clean"],
            config["datatrove"]["quality-filter"],
        )

        # 4. Unión de los JSONL generados en un único parquet y jsonl
        self.merge_jsonl_to_parquet()

        # 5. Contar tokens y actualizar info
        ALIACorporaUtils.count_corpus_tokens(
            input_path_corpus=paths["output-path-file-datatrove-parquet"],
            output_path_file_token_count_csv=paths["stats-path-file-count"],
        )
        ALIACorporaUtils.update_corpus_info(
            path_file_info_json=paths["path-file-info"],
            input_path_file_token_count_csv=paths["stats-path-file-count"],
            step="datatrove",
        )

        logging.info("\n🎉 Pipeline finalizado exitosamente.")


def get_args():
    parser = argparse.ArgumentParser(description="Datatrove Curation Pipeline")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument(
        "--version", type=int, default=-1, help="Versión del corpus (default: -1)"
    )
    parser.add_argument(
        "--tasks", type=int, default=25, help="Número de procesos paralelos"
    )
    return parser.parse_args()


def main():
    args = get_args()
    step = CorporaDatatrove(
        name=args.name, domain=args.domain, version=args.version, tasks=args.tasks
    )
    step.run()


if __name__ == "__main__":
    main()
