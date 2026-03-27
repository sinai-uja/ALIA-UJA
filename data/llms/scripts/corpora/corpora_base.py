import os
import sys
import logging
from abc import ABC, abstractmethod
from typing import Dict

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# ======================================================================

class CorporaStep(ABC):
    """
    Clase abstracta base para los pasos del pipeline de corpus.
    """
    def __init__(self, name: str, domain: str, version: int = -1, force: bool = False, **kwargs):
        self.name = name
        self.domain = domain
        self.version = version
        self.force = force
        self.kwargs = kwargs
        
        # Cargar configuración
        self.config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        if not os.path.exists(self.config_path):
            raise FileNotFoundError("No se encontró config.yaml")
        
        self.full_config = load_config(self.config_path)
        self.paths_config = self.full_config['paths']
        
        # Generar rutas
        self.paths = self.get_paths()

    def _get_base_paths(self, step_name: str) -> Dict[str, str]:
        """
        Genera las rutas comunes para todos los pasos.
        """
        config = self.paths_config
        name = self.name
        domain = self.domain
        version = self.version

        path_root_corpora = config['path-root-corpora']
        path_root_data = config['path-root-data'].format(domain=domain)
        
        path_dir_corpus = os.path.join(
            path_root_corpora,
            config['path-dir-corpus'].format(domain=domain, name=name) 
            if version == -1 
            else config['path-dir-corpus-version'].format(domain=domain, name=name, version=version)
        )
        
        path_file_info = os.path.join(
            path_dir_corpus,
            config['path-file-info'].format(name=name) 
            if version == -1 
            else config['path-file-info-version'].format(name=name, version=version)
        )
        
        stats_path_dir = os.path.join(
            path_dir_corpus,
            config['path-dir-stats']
        )
        os.makedirs(stats_path_dir, exist_ok=True)
        
        stats_path_file_count = os.path.join(
            stats_path_dir,
            config['path-file-count'].format(name=name, step=step_name) 
            if version == -1 
            else config['path-file-count-version'].format(name=name, version=version, step=step_name)
        )
        
        return {
            "path-root-data": path_root_data,
            "path-root-corpora": path_root_corpora,
            "path-dir-corpus": path_dir_corpus,
            "path-file-info": path_file_info,
            "stats-path-dir": stats_path_dir,
            "stats-path-file-count": stats_path_file_count
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
