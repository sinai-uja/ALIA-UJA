import os, sys
import importlib.util
import yaml, json
import logging
import glob
from pathlib import Path
import time
import gc
import polars as pl
from polars.datatypes import Int64, String, Float64
from typing import List, Optional, Dict, Tuple
import re, copy
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import TokenManager, RichArgumentParser
try:
    from scripts.instructions.corpora.instructions_step_base import InstructionsStep
except ImportError:
    from instructions_step_base import InstructionsStep

# ==================== CONFIGURACION GLOBAL ====================
# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

class InstructionsManager:
    
    def __init__(self):
        self.config, self.seed = self.load_config(os.path.join(os.path.dirname(__file__), "config.yaml"))
        # argumentos
        self.args = self.get_args(choice_steps=self.config["pipeline"].get("steps", []))
        self.domain = self.args.domain
        self.lang = self.args.lang
        self.steps = self.get_steps()
        logging.info(f"> Pasos a ejecutar: {self.steps}\n")
        # rutas
        self.paths = self.get_paths(self.config.get("paths", {}))

    # ==================== CONFIGURACION GLOBAL ====================
    def load_config(self, config_path: str) -> tuple[dict, int]:
        """Cargar configuración YAML."""
        
        logging.info("Cargar configuración...")
        with open(config_path, 'r') as f:
            CONFIG = yaml.safe_load(f)
        
        SEED = CONFIG.get('seed', 42)
            
        return CONFIG, SEED

    def get_steps(self) -> List[str]:
        
        """ Determina qué pasos del pipeline se deben ejecutar según los argumentos proporcionados. """
        
        if self.args.single_step:
            logging.info(f"Ejecutando una única tarea: {self.args.single_step}")
            return [self.args.single_step]
        elif self.args.start_step and self.args.end_step:
            steps = self.config["pipeline"].get("steps", [])
            start_idx = steps.index(self.args.start_step)
            end_idx = steps.index(self.args.end_step) + 1
            logging.info(f"Ejecutando tareas desde '{self.args.start_step}' hasta '{self.args.end_step}'")
            return steps[start_idx:end_idx]
        elif self.args.start_step and not self.args.end_step:
            steps = self.config["pipeline"].get("steps", [])
            start_idx = steps.index(self.args.start_step)
            logging.info(f"Ejecutando tareas desde '{self.args.start_step}' hasta el final")
            return steps[start_idx:]
        elif not self.args.start_step and self.args.end_step:
            steps = self.config["pipeline"].get("steps", [])
            end_idx = steps.index(self.args.end_step) + 1
            logging.info(f"Ejecutando tareas desde el inicio hasta '{self.args.end_step}'")
            return steps[:end_idx]
        else:
            logging.info("Ejecutando todas las tareas del pipeline.")
            return self.config["pipeline"].get("steps", [])

    def get_args(self, choice_steps: List[str] = []):
        
        """Captura los argumentos de la línea de comandos."""
        
        if not choice_steps:
            raise ValueError("La lista de pasos 'steps' no puede estar vacía. Revise la configuración.")
        
        # Usamos nuestra clase personalizada y el formatter de rich
        parser = RichArgumentParser(
            description="Script de procesamiento de Corpus"
        )
        
        # Argumentos existentes
        parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
        parser.add_argument("--lang", required=True, type=str, choices=["es", "en"], help="Idioma del corpus (es o en)")
        
        # Functionality A: Single Task
        parser.add_argument(
            "--single_step", 
            type=str, 
            choices=choice_steps, 
            default="", 
            help="Ejecutar una única tarea específica"
        )
        
        # Functionality B: Range (Start/End)
        parser.add_argument(
            "--start_step", 
            type=str, 
            choices=choice_steps, 
            default="", 
            help="Tarea de inicio del pipeline"
        )
        
        parser.add_argument(
            "--end_step", 
            type=str, 
            choices=choice_steps, 
            default="", 
            help="Tarea final del pipeline (no puede ser anterior a start_step)"
        )
        
        # Force flag
        parser.add_argument(
            "--force", 
            action="store_true", 
            default=False, 
            help="Forzar la ejecución sobrescribiendo datos existentes"
        )

        args = parser.parse_args()

        # --- Post-Processing y Validación Lógica ---

        # 1. Validar orden de start/end task
        if args.start_step and args.end_step:
            start_idx = choice_steps.index(args.start_step)
            end_idx = choice_steps.index(args.end_step)
            
            if end_idx < start_idx:
                parser.error(
                    f"La tarea final '{args.end_step}' (índice {end_idx}) "
                    f"no puede ser anterior a la tarea inicial '{args.start_step}' (índice {start_idx})."
                )

        return args

    def get_paths(self, _config: dict):
        
        """Centraliza la lógica de generación de rutas para evitar condicionales repetidos."""
        if not _config:
            raise ValueError("La configuración de rutas 'paths' no puede estar vacía. Revise la configuración.")
        
        path_root_scripts = _config['path-root-scripts']
        path_file_initial_step = os.path.join(
            path_root_scripts,
            _config['path-script-step-initial']
        )
        path_file_downsampling_step = os.path.join(
            path_root_scripts,
            _config['path-script-step-downsampling']
        )
        path_file_build_raw_step = os.path.join(
            path_root_scripts,
            _config['path-script-step-build_raw']
        )
        path_file_build_train_step = os.path.join(
            path_root_scripts,
            _config['path-script-step-build_train']
        )
        
        return {
            "path-root-scripts": path_root_scripts,
            "path-script-step-initial": path_file_initial_step,
            "path-script-step-downsampling": path_file_downsampling_step,
            "path-script-step-build_raw": path_file_build_raw_step,
            "path-script-step-build_train": path_file_build_train_step
        }

    # ==================== TOKENIZER ====================
    def init_tokenizer(self):
        """Inicializar TokenManager para cómputo de tokens."""
        logging.info("Initializing TokenManager for token computation...")
        TOKENIZER = TokenManager()
        return TOKENIZER

    # ==================== STATISTICS ====================
    def compute_stats(self, 
                      corpus: pl.DataFrame, 
                      name: str,
                      indexation_column: str = "category"
        ) -> pl.DataFrame:
        """Compute and print basic statistics of the corpus. (Igual que original)"""
        logging.info(f"Computing statistics for the corpus de instrucciones {name}...")
        
        with pl.Config(fmt_str_lengths=100, tbl_rows=-1, tbl_cols=-1, tbl_width_chars=250):
            print(corpus.sample(10, seed=self.seed, shuffle=True))
        
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
            indexation_column: [name],
            "num_instructions": [total_instructions],
            "total_tokens": [total_tokens],
            "avg_tokens": [avg_tokens]
        })
        all_stats.append(overall_stats)
        
        # Stats by query_type, context_type, justification_type
        for col in ['query_type', 'context_type', 'justification_type']:
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
                stats_by_type = stats_by_type.with_columns(pl.lit(col).alias("statistic_type")).rename({col: indexation_column})
                all_stats.append(stats_by_type)
        
        # Stats by category
        stats_by_category = (corpus
            .group_by(indexation_column)
            .agg([
                pl.len().alias("num_instructions"),
                pl.sum("tokens").alias("total_tokens"),
                pl.mean("tokens").alias("avg_tokens")
            ])
            .sort("total_tokens", descending=True)
        )
        stats_by_category = stats_by_category.with_columns(pl.lit(indexation_column).alias("statistic_type"))
        all_stats.append(stats_by_category)
        
        # Cast y concatenar
        all_stats_cast = []
        for df in all_stats:
            df_cast = df.with_columns([
                pl.col("num_instructions").cast(Int64),
                pl.col("total_tokens").cast(Int64),
                pl.col("avg_tokens").cast(Float64)
            ])
            all_stats_cast.append(df_cast)
        
        stats_df: pl.DataFrame = pl.concat(all_stats_cast, how="diagonal")
        stats_df = stats_df.select(["statistic_type", indexation_column, "num_instructions", "total_tokens", "avg_tokens"])
        
        return stats_df

    # ==================== STATISTICS ====================
    def run_step(
        self,
        domain: str,
        lang: str = "es",
        force: bool = False,
        step_name: str = ""
    ):
        """Ejecuta un paso específico del pipeline de procesamiento del corpus."""
        
        if not step_name:
            raise ValueError("El parámetro 'step' no puede estar vacío.")
        
        logging.info(f"== 🛫 Ejecutando paso: {step_name} para el corpus de instrucciones del dominio '{domain}' (lang='{lang}') ==")
        
        # Construir rutas y nombre del módulo
        script_path = self.paths[f'path-script-step-{step_name}']
        module_name = f"scripts.instructions.corpora.instructions_step_{step_name}"
        
        # Importación dinámica
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo crear el spec/loader para: {script_path}")

        step_module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = step_module
        spec.loader.exec_module(step_module)

        # Buscar la clase correspondiente: InstructionsStep<StepName> (e.g., InstructionsStepInitial, InstructionsStepClean)
        class_name = f"Instructions{step_name.capitalize()}Step"
        
        if not hasattr(step_module, class_name):
            # Fallback para scripts no migrados (si los hubiera)
            if hasattr(step_module, "run"):
                logging.warning(f"⚠️ La clase {class_name} no existe en {module_name}. Usando run() como fallback.")
                step_module.run(domain=domain, lang=lang, force=force)
                logging.info(f"== 🛬 Paso '{step_name}' completado (Legacy) ==")
                return
            else:
                raise AttributeError(f"El módulo {script_path} no define la clase {class_name} ni la función run(...)")

        # Instanciar y ejecutar
        step_class = getattr(step_module, class_name)
        step_instance: InstructionsStep = step_class(domain=domain, lang=lang, force=force)
        step_instance.run()

        logging.info(f"== 🛬 Paso '{step_name}' completado ==")    
    
    def run_pipeline(self):
        
        for idx, step in enumerate(self.steps):
            
            logging.info(f"---"*15)
            logging.info(f"--- INICIANDO PASO {idx+1}/{len(self.steps)}: {step.upper()} ---")
            logging.info(f"---"*15)
            
            try:
                self.run_step(
                    domain=self.args.domain,
                    lang=self.args.lang,
                    force=self.args.force,
                    step_name=step
                )
            except Exception as e:
                logging.error(f"Error en el paso '{step}': {e}")
                # show complete traceback
                logging.exception("Traceback completo:")
                
                sys.exit(1)
            
            logging.info(f"---"*15)
            logging.info(f"--- PASO {idx+1}/{len(self.steps)}: {step.upper()} FINALIZADO ---")
            logging.info(f"---"*15 + "\n")
        
        logging.info("=== 🎉 Pipeline de procesamiento del corpus de instrucciones completado con éxito. 🎉 ===")
    
if __name__ == "__main__":
    corporaManager = InstructionsManager()
    corporaManager.run_pipeline()