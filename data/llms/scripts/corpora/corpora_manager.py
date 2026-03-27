import os, sys, logging
from typing import List, Mapping
import importlib.util

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config, RichArgumentParser
try:
    from scripts.corpora.corpora_base import CorporaStep
except ImportError:
    from corpora_base import CorporaStep
    
# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# ======================================================================

class CorporaManager:
    
    def __init__(self):
        self.config = load_config(os.path.join(os.path.dirname(__file__), "config.yaml"))
        # argumentos
        self.args = self.get_args(steps=self.config["pipeline"].get("steps", []))
        self.steps = self.get_steps()
        logging.info(f"> Pasos a ejecutar: {self.steps}\n")
        # rutas
        self.paths = self.get_paths(self.config.get("paths", {}))
    
    def get_args(self, steps: List[str] = []):
        
        """Captura los argumentos de la línea de comandos."""
        
        if not steps:
            raise ValueError("La lista de pasos 'steps' no puede estar vacía. Revise la configuración.")
        
        # Usamos nuestra clase personalizada y el formatter de rich
        parser = RichArgumentParser(
            description="Script de procesamiento de Corpus"
        )
        
        # Argumentos existentes
        parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
        parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
        parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
        
        # Functionality A: Single Task
        parser.add_argument(
            "--single_step", 
            type=str, 
            choices=steps, 
            default="", 
            help="Ejecutar una única tarea específica"
        )
        
        # Functionality B: Range (Start/End)
        parser.add_argument(
            "--start_step", 
            type=str, 
            choices=steps, 
            default="", 
            help="Tarea de inicio del pipeline"
        )
        
        parser.add_argument(
            "--end_step", 
            type=str, 
            choices=steps, 
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
            start_idx = steps.index(args.start_step)
            end_idx = steps.index(args.end_step)
            
            if end_idx < start_idx:
                parser.error(
                    f"La tarea final '{args.end_step}' (índice {end_idx}) "
                    f"no puede ser anterior a la tarea inicial '{args.start_step}' (índice {start_idx})."
                )

        return args
    
    def get_paths(self, _config: Mapping[str, str]) -> Mapping[str, str]:
    
        """Centraliza la lógica de generación de rutas para evitar condicionales repetidos."""
        if not _config:
            raise ValueError("La configuración de rutas 'paths' no puede estar vacía. Revise la configuración.")
        
        path_root_corpora_scripts = _config['path-root-scripts']
        path_file_initial_step = _config['path-file-initial-step']
        path_file_clean_step = _config['path-file-clean-step']
        path_file_split_step = _config['path-file-split-step']
        path_file_datatrove_step = _config['path-file-datatrove-step']
        path_file_complete_step = _config['path-file-complete-step']
        path_file_downsampling_step = _config['path-file-downsampling-step']
        
        
        return {
            "path-root-scripts": path_root_corpora_scripts,
            "path-file-initial-step": path_file_initial_step,
            "path-file-clean-step": path_file_clean_step,
            "path-file-split-step": path_file_split_step,
            "path-file-datatrove-step": path_file_datatrove_step,
            "path-file-complete-step": path_file_complete_step,
            "path-file-downsampling-step": path_file_downsampling_step
        }
    
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
        
    def run_step(
        self,
        name: str,
        domain: str,
        version: str,
        force: bool = False,
        step_name: str = ""
    ):
        """Ejecuta un paso específico del pipeline de procesamiento del corpus."""
        
        if not step_name:
            raise ValueError("El parámetro 'step' no puede estar vacío.")
        
        logging.info(f"== 🛫 Ejecutando paso: {step_name} para el corpus '{name}' en el dominio '{domain}' ==")
        
        # Construir rutas y nombre del módulo
        script_path = os.path.join(self.paths['path-root-scripts'], self.paths[f'path-file-{step_name}-step'])
        module_name = f"scripts.corpora.corpora_step_{step_name}"
        
        # Importación dinámica
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo crear el spec/loader para: {script_path}")

        step_module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = step_module
        spec.loader.exec_module(step_module)

        # Buscar la clase correspondiente: Corpora<StepName> (e.g., CorporaInitial, CorporaClean)
        class_name = f"Corpora{step_name.capitalize()}"
        
        if not hasattr(step_module, class_name):
            # Fallback para scripts no migrados (si los hubiera)
            if hasattr(step_module, "run_main"):
                logging.warning(f"⚠️ La clase {class_name} no existe en {module_name}. Usando run_main() como fallback.")
                step_module.run(name=name, domain=domain, version=version)
                logging.info(f"== 🛬 Paso '{step_name}' completado (Legacy) ==")
                return
            else:
                raise AttributeError(f"El módulo {script_path} no define la clase {class_name} ni la función run_main(...)")

        # Instanciar y ejecutar
        step_class = getattr(step_module, class_name)
        step_instance: CorporaStep = step_class(name=name, domain=domain, version=version, force=force)
        step_instance.run()

        logging.info(f"== 🛬 Paso '{step_name}' completado ==")
    
    def run_pipeline(self):
        
        for idx, step in enumerate(self.steps):
            
            logging.info(f"---"*15)
            logging.info(f"--- INICIANDO PASO {idx+1}/{len(self.steps)}: {step.upper()} ---")
            logging.info(f"---"*15)
            
            try:
                self.run_step(
                    name=self.args.name,
                    domain=self.args.domain,
                    version=self.args.version,
                    force=self.args.force,
                    step_name=step
                )
            except Exception as e:
                logging.error(f"Error en el paso '{step}': {e}")
                sys.exit(1)
            
            logging.info(f"---"*15)
            logging.info(f"--- PASO {idx+1}/{len(self.steps)}: {step.upper()} FINALIZADO ---")
            logging.info(f"---"*15 + "\n")
        
        logging.info("=== 🎉 Pipeline de procesamiento del corpus completado con éxito. 🎉 ===")
    
if __name__ == "__main__":
    corporaManager = CorporaManager()
    corporaManager.run_pipeline()

        