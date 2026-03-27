import os
import sys
import logging
from abc import ABC, abstractmethod
from typing import Dict, Mapping, List, Tuple, Union
import copy
import polars as pl 

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import TokenManager, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

class InstructionsStep(ABC):
    
    """
    Clase abstracta base para los pasos del pipeline de instrucciones.
    """
    
    def __init__(self, domain: str, lang: str = "es", force: bool = False, **kwargs):
        self.domain = domain
        self.lang = lang
        self.force = force
        self.kwargs = kwargs
        
        # Cargar configuración
        self.config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        if not os.path.exists(self.config_path):
            raise FileNotFoundError("No se encontró config.yaml")
        
        self.full_config = load_config(self.config_path)
        self.paths_config = self.full_config['paths'] 
        self.config = dict()
        
        # Generar rutas
        self.paths = self.get_paths()
        
        self.TOKENIZER = self.init_tokenizer()
        self.SEED = self.full_config.get('seed', 42)

    # ==================== TOKENIZER ====================
    def init_tokenizer(self):
        """Inicializar TokenManager para cómputo de tokens."""
        logging.info("Initializing TokenManager for token computation...")
        TOKENIZER = TokenManager()
        return TOKENIZER
    
    def load_step_config(self, full_config: Mapping, step_name: str) -> dict:
        """Cargar configuración específica del paso."""
        if self.domain == "general":
            config: Dict = copy.deepcopy(full_config['general-instruction'])
        else:
            config: Dict = copy.deepcopy(full_config['domain-instruction'])
        try: config.update(copy.deepcopy(full_config[step_name]))
        except KeyError: pass
        config['downsampling-tasks'] = copy.deepcopy(full_config['downsampling-tasks'])
        
        return config
    
    def format_to_conversations(
        self,
        corpus: pl.DataFrame,
        keep_extra_fields: bool = True,
    ) -> pl.DataFrame:
        
        """Formatear corpus downsampled a formato conversación."""
        
        # 1) Validaciones básicas (columnas requeridas)
        required = {"question", "response"}
        missing = required - set(corpus.columns)
        if missing:
            raise ValueError(f"Faltan columnas requeridas en 'corpus': {sorted(missing)}")

        # 2) Solo validar nulos (permitir strings vacíos "")
        bad = (
            corpus
            .with_row_index("row_idx")
            .filter(
                pl.col("question").is_null()
                | pl.col("response").is_null()
            )
            .select("row_idx")
            .head(1)
        )
        if bad.height > 0:
            line_no = int(bad["row_idx"][0]) + 1
            raise ValueError(f"Falta question/response en línea {line_no}")

        # 3) Construir la nueva columna conversations (List[Struct])
        conversations_expr = pl.concat_list(
            [
                pl.struct([pl.lit("system").alias("from"), pl.lit("").alias("value")]),
                pl.struct([pl.lit("human").alias("from"), pl.col("question").alias("value")]),
                pl.struct([pl.lit("gpt").alias("from"), pl.col("response").alias("value")]),
            ]
        ).alias("conversations")

        # 4) Mantener o no campos extra + eliminar system_prompt
        if keep_extra_fields:
            out_df = corpus.drop("system_prompt", strict=False).with_columns(conversations_expr)
        else:
            out_df = corpus.select(conversations_expr)
        
        return out_df
    
    def compute_stats(
        self,
        corpus: pl.DataFrame, # type: ignore
        criteria_columns: List[str] = [],
        category_column: str = "category",
        stats_name: str = "Corpus Statistics"
    ) -> pl.DataFrame:
        
        """Compute and print basic statistics of the corpus. (Igual que original)"""
        
        logging.info(f"Computing statistics for the corpus {stats_name}...")
        logging.info(f"> Corpus has {corpus.shape[0]:,} rows.")
        logging.info(f"> Corpus columns: {corpus.columns}")
        
        with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=250):
            print(corpus.sample(10, seed=self.SEED, shuffle=True))
        
        total_instructions = corpus.shape[0]
        total_tokens = corpus['tokens'].sum()
        avg_tokens = corpus['tokens'].mean()
        
        print(f"Corpus Statistics")
        print(f"  Total instructions: {total_instructions:,}")
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Average tokens per instruction: {avg_tokens:.2f}\n")
        
        all_stats: List[pl.DataFrame] = []
        
        # Overall stats
        overall_stats = pl.DataFrame({
            "statistic_type": ["Overall"],
            category_column: [stats_name],
            "num_instructions": [total_instructions],
            "total_tokens": [total_tokens],
            "avg_tokens": [avg_tokens]
        })
        all_stats.append(overall_stats)
        
        # Stats by query_type, context_type, justification_type
        if criteria_columns and category_column:
            for col in criteria_columns:
                if col in corpus.columns:
                    stats_by_type = (corpus
                        .group_by(col)
                        .agg([
                            pl.len().alias("num_instructions"),
                            pl.sum("tokens").alias("total_tokens"),
                            pl.mean("tokens").alias("avg_tokens")
                        ])
                        .sort("total_tokens", descending=True)
                    )
                    stats_by_type = stats_by_type.with_columns(pl.lit(col).alias("statistic_type")).rename({col: category_column})
                    all_stats.append(stats_by_type)
        
        # Stats by category
        if category_column:
            stats_by_category = (corpus
                .group_by(category_column)
                .agg([
                    pl.len().alias("num_instructions"),
                    pl.sum("tokens").alias("total_tokens"),
                    pl.mean("tokens").alias("avg_tokens")
                ])
                .sort("total_tokens", descending=True)
            )
            stats_by_category = stats_by_category.with_columns(pl.lit(category_column).alias("statistic_type"))
            all_stats.append(stats_by_category)
        
        # Cast y concatenar
        all_stats_cast = []
        for df in all_stats:
            df_cast = df.with_columns([
                pl.col("num_instructions").cast(pl.Int64),
                pl.col("total_tokens").cast(pl.Int64),
                pl.col("avg_tokens").cast(pl.Float64)
            ])
            all_stats_cast.append(df_cast)
        
        stats_df: pl.DataFrame = pl.concat(all_stats_cast, how="diagonal")
        stats_df = stats_df.select(
            ["statistic_type", category_column, "num_instructions", "total_tokens", "avg_tokens"]
        )
        
        return stats_df
    
    def _get_base_paths(self) -> Dict[str, str]:
        
        """
        Genera las rutas comunes para todos los pasos.
        """
        
        config = self.paths_config
        path_dir_root = config['path-dir-root']
        path_dir_datasets = os.path.join(
            path_dir_root,
            config['path-dir-datasets-instructions']
        )
        os.makedirs(path_dir_datasets, exist_ok=True)
        path_dir_corpora = os.path.join(
            path_dir_root,
            config['path-dir-corpora-instructions'].format(
                domain=self.domain, 
                lang=self.lang
            )
        )
        os.makedirs(path_dir_corpora, exist_ok=True)
        path_dir_stats = os.path.join(
            path_dir_root,
            config['path-dir-stats-instructions'].format(domain=self.domain, lang=self.lang)
        )
        os.makedirs(path_dir_stats, exist_ok=True)
        
        return {
            "path-dir-root": path_dir_root,
            "path-dir-datasets-instructions": path_dir_datasets,
            "path-dir-corpora-instructions": path_dir_corpora,
            "path-dir-stats-instructions": path_dir_stats
        }
    
    @abstractmethod
    def get_paths(self) -> Dict[str, str]:
        """
        Debe ser implementado por las subclases para retornar el diccionario de rutas completo.
        Se recomienda llamar a self._get_base_paths(step_name) y extender el diccionario.
        """
        pass

    @abstractmethod
    def run(self):
        """
        Lógica principal del paso.
        """
        pass