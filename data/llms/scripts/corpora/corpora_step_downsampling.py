import os
import sys
import logging
import argparse
import gc
import polars as pl
from typing import Mapping, List, Tuple

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_parquet, write_jsonl, write_parquet, ALIACorporaUtils, TokenManager
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

# ======================================================================

'''
INPUT:
Corpus
- S fuentes diferentes (valores en la columna "source_id")
- N documentos (filas en el dataframe), 
- NSi número de documentos por fuente Si (filas en el dataframe con source_id=Si)
- T número total de tokens totales (suma de todos los documentos)
- TSi número total de tokens por fuente Si (suma de todos los documentos de la fuente Si)
TASKS:
1. Downsampling del corpus a un objetivo de tokens T' de manera estratificada
2. Downsampling del corpus a un objetivo de tokens T' de manera equitativa
3. Downsampling del corpus a un objetivo de tokens TSi' por fuente Si (con i=1..S)
4. Downsampling del corpus a un objetivo de documentos N' de manera estratificada
5. Downsampling del corpus a un objetivo de documentos N' de manera equitativa
6. Downsampling del corpus a un objetivo de documentos NSi' por fuente Si (con i=1..S)
'''

class CorporaDownsampling(CorporaStep):
    
    def get_paths(self):
        paths = self._get_base_paths("downsampling")
        config = self.paths_config
        name = self.name
        domain = self.domain
        version = self.version
        
        input_path_file_enriched_corpus = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-enriched'].format(domain=domain, name=name, format="parquet") 
            if version == -1 
            else config['path-file-corpus-enriched-version'].format(domain=domain, name=name, version=version, format="parquet")
        )
        if self.full_config['downsampling']['plain-text'].get('special-input-file', ''):
            input_path_file_enriched_corpus =  os.path.join(
                paths['path-dir-corpus'],
                self.full_config['downsampling']['plain-text']['special-input-file']
            )
        output_path_file_template_corpus_parquet = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-template-corpus'].format(name=name, format="parquet")  
            if version == -1 
            else config['path-file-template-corpus-version'].format(name=name, version=version, format="parquet")
        )
        output_path_file_template_corpus_jsonl = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-template-corpus'].format(name=name, format="jsonl")  
            if version == -1 
            else config['path-file-template-corpus-version'].format(name=name, version=version, format="jsonl")
        )
        path_file_info_downsampling = os.path.join(
            paths['path-dir-corpus'],
            config['path-dir-stats'],
            config['path-file-info-downsampling'].format(name=name) 
            if version == -1 
            else config['path-file-info-downsampling-version'].format(name=name, version=version)
        )
        
        paths.update({
            "input-path-file-enriched-corpus": input_path_file_enriched_corpus,
            "output-path-file-template-corpus-parquet": output_path_file_template_corpus_parquet,
            "output-path-file-template-corpus-jsonl": output_path_file_template_corpus_jsonl,
            "path-file-info-downsampling": path_file_info_downsampling
        })
        return paths

    def _build_task_output_filename(
        self,
        task_type: str, 
        task_params: dict, 
    ) -> Tuple[Tuple[str, str], str]:
        """ Construye el nombre del fichero de salida basado en la tarea y sus parámetros. 
        Format:
            paths['output-path-file-template-corpus-parquet']: 'ALIA-corpus-<task>-<sources>-<target>.parquet'
        Example 1:
            task_type: tokens_general_stratified
            task_params: {'target': 50000000}
            return 'ALIA-corpus-tokens_general_stratified-all-target_50000000.parquet'
        """
        paths = self.paths
        if 'mapping' in task_params:
            total_target_tokens = sum(task_params['mapping'].values())
        
        # Output files
        output_filename_parquet = paths['output-path-file-template-corpus-parquet'].replace(
            "<task>", 
            task_type
        ).replace(
            "<sources>", 
            f"S{len(task_params['mapping'])}" if 'mapping' in task_params else "all"
        ).replace(
            "<target>", 
            f"target_S{len(task_params['mapping'])}-total_tokens_{total_target_tokens}" if 'mapping' in task_params else f"target_{task_params['target']}" if 'target' in task_params else "unknown"
        )
        output_filename_jsonl = output_filename_parquet.replace(".parquet", ".jsonl")
        # Info file
        info_filename = paths['path-file-info-downsampling'].replace(
            "<task>", 
            task_type
        ).replace(
            "<sources>", 
            f"S{len(task_params['mapping'])}" if 'mapping' in task_params else "all"
        ).replace(
            "<target>", 
            f"target_S{len(task_params['mapping'])}-total_tokens_{total_target_tokens}" if 'mapping' in task_params else f"target_{task_params['target']}" if 'target' in task_params else "unknown"
        )
        
        return (output_filename_parquet, output_filename_jsonl), info_filename

    def perform_task(
        self,
        corpus: pl.DataFrame,
        task_type: str,
        task_params: Mapping,
        seed: int = 42,
    ):
        """Ejecuta una tarea de downsampling, construye la ruta de salida y despacha a la función adecuada.

        - Acepta nombres de tarea con '_' (YAML) o con '-' y prefijo 'downsampling-' (código).
        - Construye el nombre de salida usando `_build_task_output_filename`.
        - Inyecta argumentos comunes: paths, corpus, config (con seed) y output_path_file_corpus_downsampled.
        - Devuelve las rutas de salida generadas (parquet/jsonl) para que el caller pueda usarlas (p.ej. token counting).
        """
        if not isinstance(task_params, Mapping):
            raise ValueError("task_params debe ser un Mapping (dict-like).")

        # 1) Normalización del nombre de tarea (compatibilidad YAML vs código)
        t = (task_type or "").strip()
        t = t.replace("-", "_")
        if t.startswith("downsampling_"):
            t = t[len("downsampling_"):]

        # 2) Construir params para nombre de fichero (depende de si es target global o mapping por fuente)
        task_params = dict(task_params)
        
        # Para tareas "per_source", `_build_task_output_filename` espera 'mapping' para calcular S{n}
        if "mapping" not in task_params and "per_source" in t:
            if "target_tokens_mapping" in task_params:
                task_params["mapping"] = task_params["target_tokens_mapping"]
            elif "target_documents_mapping" in task_params:
                task_params["mapping"] = task_params["target_documents_mapping"]

        # Para tareas equitativas, permitir que el YAML use 'target' como alias del parámetro específico
        if "target" not in task_params and "per_source" not in t:
            if "target_tokens_in_source" in task_params:
                task_params["target"] = task_params["target_tokens_in_source"]
            elif "target_documents_in_source" in task_params:
                task_params["target"] = task_params["target_documents_in_source"]

        # 3) Ruta de salida para esta tarea
        output_files, info_file = self._build_task_output_filename(
            task_type=t,
            task_params=task_params
        )

        # 4) Args comunes
        common_kwargs = dict(
            seed=seed,
            corpus=corpus,
            output_path_files_corpus_downsampled=output_files
        )
        
        # 5) Comprobar existencia previa
        if os.path.exists(output_files[0]) and not self.force:
            if not os.path.exists(output_files[1]):
                logging.info(f"El fichero de salida JSONL no existe pero el Parquet sí: {output_files[1]}. Se genera el JSONL desde el Parquet.")
                _corpus = load_parquet(output_files[0])
                write_jsonl(_corpus, output_files[1])
                del _corpus
            logging.info(f"El fichero de salida ya existe y --force no está activado: {output_files[0]}. Se omite la tarea.")
            return {
                "task_type": t,
                "output_path_parquet": output_files[0],
                "output_path_jsonl": output_files[1],
                "info_file_path": info_file
            }

        # 6) Dispatch + adaptación de nombres de parámetros (target vs target_tokens, etc.)
        if t == "tokens_general_stratified":
            self.downsampling_tokens_general_stratified(
                **common_kwargs, # type: ignore
                target_tokens=task_params.get("target", 0),
                text_column=task_params.get("text_column", "text"),
                source_column=task_params.get("source_column", "source_id"),
            )

        elif t == "tokens_general_equitative":
            self.downsampling_tokens_general_equitative(
                **common_kwargs, # type: ignore
                target_tokens_in_source=task_params.get("target", 0),
                text_column=task_params.get("text_column", "text"),
                source_column=task_params.get("source_column", "source_id"),
            )

        elif t == "tokens_per_source":
            mapping = (task_params.get("mapping") or {})
            sources = list(mapping.keys())
            self.downsampling_tokens_per_source(
                **common_kwargs, # type: ignore
                sources=sources,
                target_tokens_mapping=mapping,
                text_column=task_params.get("text_column", "text"),
                source_column=task_params.get("source_column", "source_id"),
            )

        elif t == "documents_general_stratified":
            self.downsampling_documents_general_stratified(
                **common_kwargs, # type: ignore
                target_documents=task_params.get("target", 0),
                source_column=task_params.get("source_column", "source_id"),
            )

        elif t == "documents_general_equitative":
            self.downsampling_documents_general_equitative(
                **common_kwargs, # type: ignore
                target_documents_in_source=task_params.get("target", 0),
                source_column=task_params.get("source_column", "source_id"),
            )

        elif t == "documents_per_source":
            mapping = (task_params.get("mapping") or {})
            sources = list(mapping.keys())
            self.downsampling_documents_per_source(
                **common_kwargs, # type: ignore
                sources=sources,
                target_documents_mapping=mapping,
                source_column=task_params.get("source_column", "source_id"),
            )

        else:
            logging.error(f"Tarea desconocida: {task_type} (normalizada: {t})")
            raise ValueError(f"Tarea desconocida: {task_type} (normalizada: {t})")

        return {
            "task_type": t,
            "output_path_parquet": output_files[0],
            "output_path_jsonl": output_files[1],
            "info_file_path": info_file
        }

    # Task 1: Downsampling del corpus a un objetivo de tokens T' de manera estratificada
    def downsampling_tokens_general_stratified(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        target_tokens: int = 0,
        text_column: str = "text",
        source_column: str = "source_id"
    ):
        """Realiza downsampling estratificado del corpus basado en tokens.

        Objetivo: seleccionar documentos de forma que el total de tokens del corpus resultante
        sea ~target_tokens, manteniendo (aprox.) la distribución original de tokens por fuente.

        Estrategia:
          1) Contar tokens por documento.
          2) Calcular tokens por fuente y asignar presupuesto proporcional por fuente.
          3) Barajar (reproducible) y, por fuente, tomar un prefijo hasta agotar el presupuesto.
          4) Escribir a Parquet y también a JSONL.
        """
        
        # 1) Validaciones iniciales
        if target_tokens is None or target_tokens <= 0:
            raise ValueError(f"target_tokens debe ser > 0 (recibido: {target_tokens})")
        if text_column not in corpus.columns:
            raise ValueError(f"No existe la columna de texto '{text_column}' en el corpus")
        if source_column not in corpus.columns:
            raise ValueError(f"No existe la columna de fuente '{source_column}' en el corpus")

        os.makedirs(os.path.dirname(output_path_files_corpus_downsampled[0]), exist_ok=True)

        # 2) Stats globales y por fuente
        if "tokens" not in corpus.columns:
            # Instanciar TokenManager
            tm = TokenManager()
            logging.info("Calculando tokens (esto puede tardar)...")
            # Añadir columna tokens
            corpus = tm.add_tokens_column_to_dataset_efficient(dataset=corpus, text_column=text_column)
            logging.info("> Cómputo de tokens completado.")
            del tm
            gc.collect()

        tokens_total = int(corpus.select(pl.sum("tokens")).item())
        if tokens_total <= 0:
            raise ValueError("El corpus tiene 0 tokens (tras el conteo); no se puede downsamplear.")

        if target_tokens >= tokens_total:
            logging.warning(
                f"target_tokens ({target_tokens}) >= tokens_total ({tokens_total}); "
                f"se devuelve el corpus completo sin downsampling."
            )
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        corpus_by_source = (
            corpus.group_by(source_column)
            .agg(
                pl.sum("tokens").alias("_tokens_source"),
                pl.len().alias("_docs_source"),
            )
            .sort(source_column)
        )

        # 3) Asignación proporcional con corrección de redondeo para que sume exactamente target_tokens
        rows = list(corpus_by_source.iter_rows(named=True))
        exact_alloc = []
        base_sum = 0
        for r in rows:
            exact = (r["_tokens_source"] / tokens_total) * target_tokens
            base = int(exact)  # floor
            frac = float(exact - base)
            exact_alloc.append((r[source_column], base, frac))
            base_sum += base

        remainder = target_tokens - base_sum
        if remainder < 0:
            remainder = 0

        # Repartir los tokens restantes a las mayores fracciones (método de restos mayores)
        exact_alloc.sort(key=lambda x: x[2], reverse=True)
        alloc_map = {sid: base for sid, base, _ in exact_alloc}
        for sid, _, _ in exact_alloc[:remainder]:
            alloc_map[sid] += 1

        alloc_df = pl.DataFrame(
            {
                source_column: list(alloc_map.keys()),
                "_target_tokens_source": list(alloc_map.values()),
            }
        )

        # 4) Selección: barajar y tomar prefijo por fuente hasta presupuesto
        shuffled = corpus.sample(fraction=1.0, shuffle=True, seed=seed)

        selected = (
            shuffled.join(alloc_df, on=source_column, how="left")
            .with_columns(
                pl.col("tokens").cum_sum().over(source_column).alias("_cum_tokens")
            )
            .filter(pl.col("_cum_tokens") <= pl.col("_target_tokens_source"))
            .drop(["_cum_tokens", "_target_tokens_source"])
        )

        # 5) Persistencia
        write_parquet(df=selected, file_path=output_path_files_corpus_downsampled[0])
        write_jsonl(df=selected, file_path=output_path_files_corpus_downsampled[1])

        logging.info(
            f"Downsampling (tokens, stratified) completado: {selected.height} docs seleccionados."
        )
        
        gc.collect()
        del shuffled, selected, corpus_by_source, alloc_df
        gc.collect()

    # Task 2: Downsampling del corpus a un objetivo de tokens T' de manera equitativa
    def downsampling_tokens_general_equitative(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        target_tokens_in_source: int = 0,
        text_column: str = "text",
        source_column: str = "source_id"
    ):
        """ Realiza downsampling equitativo del corpus basado en tokens. """
        pass

    # Task 3: Downsampling del corpus a un objetivo de tokens TSi' por fuente Si (con i=1..S)
    def downsampling_tokens_per_source(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        sources: List[str] = [],
        target_tokens_mapping: Mapping[str, int] = {},
        text_column: str = "text",
        source_column: str = "source_id"
    ):
        """ Realiza downsampling del corpus basado en tokens por fuente. 

        Objetivo: seleccionar documentos de forma que el total de tokens de las fuentes indicadas 
        en el 'mapping' sea ~target_tokens
        - Si el número de tokens de una fuente es menor que su target, se seleccionarán todos 
        los documentos de dicha fuente.
        Para las fuentes no indicadas en el 'mapping', se seleccionarán todos sus documentos (es decir, 
        esa fuente no se modifica y se mantiene para el corpus final).

        Estrategia:
          1) Contar tokens por documento.
          2) Barajar (reproducible) y, por fuente, tomar un prefijo hasta agotar el presupuesto.
          3) Escribir a Parquet y también a JSONL.
        """
        # 1) Validaciones iniciales
        if not target_tokens_mapping:
            logging.warning("No se ha proporcionado un mapping de tokens por fuente. Se devuelve el corpus completo.")
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        if text_column not in corpus.columns:
            raise ValueError(f"No existe la columna de texto '{text_column}' en el corpus")
        if source_column not in corpus.columns:
            raise ValueError(f"No existe la columna de fuente '{source_column}' en el corpus")

        os.makedirs(os.path.dirname(output_path_files_corpus_downsampled[0]), exist_ok=True)

        # 2) Stats globales y por fuente
        if "tokens" not in corpus.columns:
            tm = TokenManager()
            logging.info("Calculando tokens (esto puede tardar)...")
            corpus = tm.add_tokens_column_to_dataset_efficient(dataset=corpus, text_column=text_column)
            logging.info("> Cómputo de tokens completado.")
            del tm
            gc.collect()

        # 3) Separar corpus: fuentes a procesar vs fuentes a mantener íntegras
        mapped_sources = list(target_tokens_mapping.keys())
        
        corpus_to_keep = corpus.filter(~pl.col(source_column).is_in(mapped_sources))
        corpus_to_process = corpus.filter(pl.col(source_column).is_in(mapped_sources))

        if corpus_to_process.is_empty():
            logging.warning("Ninguna de las fuentes indicadas en el mapping existe en el corpus.")
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        # 4) Selección en corpus_to_process: barajar y tomar prefijo por fuente
        alloc_df = pl.DataFrame({
            source_column: list(target_tokens_mapping.keys()),
            "_target_tokens_source": list(target_tokens_mapping.values())
        })

        shuffled = corpus_to_process.sample(fraction=1.0, shuffle=True, seed=seed)

        selected_processed = (
            shuffled.join(alloc_df, on=source_column, how="left")
            .with_columns(
                pl.col("tokens").cum_sum().over(source_column).alias("_cum_tokens")
            )
            .filter(pl.col("_cum_tokens") <= pl.col("_target_tokens_source"))
            .drop(["_cum_tokens", "_target_tokens_source"])
        )

        # 5) Combinar y persistir
        selected = pl.concat([corpus_to_keep, selected_processed])

        write_parquet(df=selected, file_path=output_path_files_corpus_downsampled[0])
        write_jsonl(df=selected, file_path=output_path_files_corpus_downsampled[1])

        logging.info(
            f"Downsampling (tokens, per source) completado: {selected.height} docs seleccionados "
            f"({selected_processed.height} de fuentes procesadas, {corpus_to_keep.height} de fuentes mantenidas)."
        )
        
        gc.collect()
        del shuffled, selected_processed, selected, corpus_to_keep, corpus_to_process, alloc_df
        gc.collect()

    # Task 4: Downsampling del corpus a un objetivo de documentos N' de manera estratificada
    def downsampling_documents_general_stratified(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        target_documents: int = 0,
        source_column: str = "source_id"
    ):
        """Realiza downsampling estratificado del corpus basado en documentos.

        Objetivo: seleccionar documentos de forma que el total de documentos del corpus
        resultante sea ~target_documents, manteniendo (aprox.) la distribución original
        de documentos por fuente.

        Estrategia:
          1) Calcular nº de documentos por fuente.
          2) Asignar presupuesto proporcional por fuente con corrección por restos mayores.
          3) Barajar (reproducible) y, por fuente, tomar un prefijo hasta agotar presupuesto.
          4) Escribir a Parquet y también a JSONL.
        """
        # 1) Validaciones iniciales
        if target_documents is None or target_documents <= 0:
            raise ValueError(f"target_documents debe ser > 0 (recibido: {target_documents})")
        if source_column not in corpus.columns:
            raise ValueError(f"No existe la columna de fuente '{source_column}' en el corpus")

        os.makedirs(os.path.dirname(output_path_files_corpus_downsampled[0]), exist_ok=True)

        docs_total = int(corpus.height)
        if docs_total <= 0:
            raise ValueError("El corpus está vacío; no se puede downsamplear.")

        if target_documents >= docs_total:
            logging.warning(
                f"target_documents ({target_documents}) >= docs_total ({docs_total}); "
                f"se devuelve el corpus completo sin downsampling."
            )
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        # 2) Stats por fuente
        corpus_by_source = (
            corpus.group_by(source_column)
            .agg(pl.len().alias("_docs_source"))
            .sort(source_column)
        )

        # 3) Asignación proporcional con corrección de redondeo para que sume exactamente target_documents
        rows = list(corpus_by_source.iter_rows(named=True))
        exact_alloc = []
        base_sum = 0
        for r in rows:
            exact = (r["_docs_source"] / docs_total) * target_documents
            base = int(exact)  # floor
            frac = float(exact - base)
            exact_alloc.append((r[source_column], base, frac))
            base_sum += base

        remainder = target_documents - base_sum
        if remainder < 0:
            remainder = 0

        # Repartir los documentos restantes a las mayores fracciones (método de restos mayores)
        exact_alloc.sort(key=lambda x: x[2], reverse=True)
        alloc_map = {sid: base for sid, base, _ in exact_alloc}
        for sid, _, _ in exact_alloc[:remainder]:
            alloc_map[sid] += 1

        alloc_df = pl.DataFrame(
            {
                source_column: list(alloc_map.keys()),
                "_target_docs_source": list(alloc_map.values()),
            }
        )

        # 4) Selección: barajar y tomar prefijo por fuente hasta presupuesto
        shuffled = corpus.sample(fraction=1.0, shuffle=True, seed=seed)

        selected = (
            shuffled.join(alloc_df, on=source_column, how="left")
            .with_columns(
                pl.lit(1).cum_sum().over(source_column).alias("_cum_docs")
            )
            .filter(pl.col("_cum_docs") <= pl.col("_target_docs_source"))
            .drop(["_cum_docs", "_target_docs_source"])
        )

        # 5) Persistencia
        write_parquet(df=selected, file_path=output_path_files_corpus_downsampled[0])
        write_jsonl(df=selected, file_path=output_path_files_corpus_downsampled[1])

        logging.info(
            f"Downsampling (documents, stratified) completado: {selected.height} docs seleccionados."
        )

        gc.collect()
        del shuffled, selected, corpus_by_source, alloc_df
        gc.collect()

    # Task 5: Downsampling del corpus a un objetivo de documentos N' de manera equitativa
    def downsampling_documents_general_equitative(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        target_documents_in_source: int = 0,
        source_column: str = "source_id"
    ):
        """Realiza downsampling equitativo del corpus basado en documentos.

        Objetivo: seleccionar, para cada fuente, hasta `target_documents_in_source`
        documentos. Si una fuente tiene menos documentos que el target, se conserva
        íntegramente.
        """
        # 1) Validaciones iniciales
        if target_documents_in_source is None or target_documents_in_source <= 0:
            raise ValueError(
                f"target_documents_in_source debe ser > 0 (recibido: {target_documents_in_source})"
            )
        if source_column not in corpus.columns:
            raise ValueError(f"No existe la columna de fuente '{source_column}' en el corpus")

        os.makedirs(os.path.dirname(output_path_files_corpus_downsampled[0]), exist_ok=True)

        if corpus.height <= 0:
            raise ValueError("El corpus está vacío; no se puede downsamplear.")

        # 2) Presupuesto equitativo por fuente
        corpus_by_source = (
            corpus.group_by(source_column)
            .agg(pl.len().alias("_docs_source"))
            .sort(source_column)
        )

        alloc_df = pl.DataFrame(
            {
                source_column: corpus_by_source.get_column(source_column).to_list(),
                "_target_docs_source": [target_documents_in_source] * corpus_by_source.height,
            }
        )

        # 3) Selección: barajar y tomar prefijo por fuente hasta presupuesto
        shuffled = corpus.sample(fraction=1.0, shuffle=True, seed=seed)

        selected = (
            shuffled.join(alloc_df, on=source_column, how="left")
            .with_columns(
                pl.lit(1).cum_sum().over(source_column).alias("_cum_docs")
            )
            .filter(pl.col("_cum_docs") <= pl.col("_target_docs_source"))
            .drop(["_cum_docs", "_target_docs_source"])
        )

        # 4) Persistencia
        write_parquet(df=selected, file_path=output_path_files_corpus_downsampled[0])
        write_jsonl(df=selected, file_path=output_path_files_corpus_downsampled[1])

        logging.info(
            f"Downsampling (documents, equitative) completado: {selected.height} docs seleccionados."
        )

        gc.collect()
        del shuffled, selected, corpus_by_source, alloc_df
        gc.collect()

    # Task 6: Downsampling del corpus a un objetivo de documentos NSi' por fuente Si (con i=1..S)
    def downsampling_documents_per_source(
        self,
        seed: int,
        corpus: pl.DataFrame,
        output_path_files_corpus_downsampled: Tuple[str, str] = ("",""),
        sources: List[str] = [],
        target_documents_mapping: Mapping[str, int] = {},
        source_column: str = "source_id"
    ):
        """Realiza downsampling del corpus basado en documentos por fuente.

        Objetivo: seleccionar documentos de forma que cada fuente indicada en
        `target_documents_mapping` tenga hasta su target de documentos.
        - Si una fuente tiene menos documentos que su target, se conservan todos.
        - Las fuentes no incluidas en el mapping se conservan íntegras.
        """
        # 1) Validaciones iniciales
        if not target_documents_mapping:
            logging.warning("No se ha proporcionado un mapping de documentos por fuente. Se devuelve el corpus completo.")
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        if source_column not in corpus.columns:
            raise ValueError(f"No existe la columna de fuente '{source_column}' en el corpus")

        os.makedirs(os.path.dirname(output_path_files_corpus_downsampled[0]), exist_ok=True)

        # 2) Separar corpus: fuentes a procesar vs fuentes a mantener íntegras
        mapped_sources = list(target_documents_mapping.keys())

        corpus_to_keep = corpus.filter(~pl.col(source_column).is_in(mapped_sources))
        corpus_to_process = corpus.filter(pl.col(source_column).is_in(mapped_sources))

        if corpus_to_process.is_empty():
            logging.warning("Ninguna de las fuentes indicadas en el mapping existe en el corpus.")
            write_parquet(df=corpus, file_path=output_path_files_corpus_downsampled[0])
            write_jsonl(df=corpus, file_path=output_path_files_corpus_downsampled[1])
            return

        # 3) Selección en corpus_to_process: barajar y tomar prefijo por fuente
        alloc_df = pl.DataFrame(
            {
                source_column: list(target_documents_mapping.keys()),
                "_target_docs_source": list(target_documents_mapping.values()),
            }
        )

        shuffled = corpus_to_process.sample(fraction=1.0, shuffle=True, seed=seed)

        selected_processed = (
            shuffled.join(alloc_df, on=source_column, how="left")
            .with_columns(
                pl.lit(1).cum_sum().over(source_column).alias("_cum_docs")
            )
            .filter(pl.col("_cum_docs") <= pl.col("_target_docs_source"))
            .drop(["_cum_docs", "_target_docs_source"])
        )

        # 4) Combinar y persistir
        selected = pl.concat([corpus_to_keep, selected_processed])

        write_parquet(df=selected, file_path=output_path_files_corpus_downsampled[0])
        write_jsonl(df=selected, file_path=output_path_files_corpus_downsampled[1])

        logging.info(
            f"Downsampling (documents, per source) completado: {selected.height} docs seleccionados "
            f"({selected_processed.height} de fuentes procesadas, {corpus_to_keep.height} de fuentes mantenidas)."
        )

        gc.collect()
        del shuffled, selected_processed, selected, corpus_to_keep, corpus_to_process, alloc_df
        gc.collect()

    def run(self):
        paths = self.paths
        config = self.full_config
        name = self.name
        
        # 1. Cargar corpus enriquecido
        logging.info(f"Cargando corpus enriquecido desde: {os.path.basename(paths['input-path-file-enriched-corpus'])}")
        corpus_enriched = load_parquet(paths['input-path-file-enriched-corpus'])
        logging.info(f"> Corpus cargado: {corpus_enriched.height} documentos.")
        
        # 2. Realizar downsampling según las tareas definidas
        tasks = config['downsampling']['plain-text']['tasks']
        for i, task in enumerate(tasks):
            logging.info(f"Ejecutando tarea de downsampling: {task['type']} [{i+1}/{len(tasks)}]")
            
            # Aumentar parámetros
            task['params']['text_column'] = config['downsampling']['plain-text'].get('text-column', 'text')
            task['params']['source_column'] = config['downsampling']['plain-text'].get('source-column', 'source_id')
            
            logging.info(f"Parámetros: {task}")
            try:
                task_output = self.perform_task(
                    corpus = corpus_enriched,
                    task_type = task['type'],
                    task_params = task['params'],
                    seed = config['downsampling'].get('seed', 42),
                )
            except Exception as e:
                logging.error(f"Error al ejecutar la tarea {task['type']}: {e}")
                raise e

            logging.info(f"Tarea {task_output['task_type']} completada. Salida en: {os.path.basename(task_output['output_path_parquet'])}, {os.path.basename(task_output['output_path_jsonl'])}")
            
            # 3. Contar tokens y actualizar info
            ALIACorporaUtils.count_corpus_tokens(
                input_path_corpus = task_output['output_path_parquet'], 
                output_path_file_token_count_csv = task_output['info_file_path']
            )
        
        logging.info("\n🎉 Pipeline finalizado exitosamente.")


def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de downsampling de Corpus")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Forzar procesamiento incluso si los datasets enriquecidos ya existen"
    )
    return parser.parse_args()

def main():
    args = get_args()
    step = CorporaDownsampling(name=args.name, domain=args.domain, version=args.version, force=args.force)
    step.run()

if __name__ == "__main__":
    main()