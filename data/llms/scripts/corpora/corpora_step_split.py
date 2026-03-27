import os
import sys
import argparse
import logging
from tqdm import tqdm

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
try:
    from utils.utils_alia import load_parquet
except ImportError:
    # Fallback por si se ejecuta fuera de la estructura exacta para pruebas
    import yaml
    def load_config(path):
        with open(path, 'r') as f:
            return yaml.safe_load(f)

try:
    from scripts.corpora.corpora_base import CorporaStep
except ImportError:
    from corpora_base import CorporaStep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s\n[%(levelname)s] %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# ======================================================================

class CorporaSplit(CorporaStep):
    
    def get_paths(self):
        paths = self._get_base_paths("split")
        config = self.paths_config
        name = self.name
        version = self.version
        
        path_file_corpus_clean = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-clean'].format(name=name, format="parquet")  
            if version == -1 
            else config['path-file-corpus-clean-version'].format(name=name, version=version, format="parquet")
        )
        
        output_path_dir_parts_parquet = os.path.join(
            paths['path-dir-corpus'],
            config['path-dir-parts-parquet']
        )
        output_path_dir_parts_jsonl = os.path.join(
            paths['path-dir-corpus'],
            config['path-dir-parts-jsonl']
        )
            
        paths.update({
            "path-file-corpus-clean": path_file_corpus_clean,
            "output-path-dir-parts-parquet": output_path_dir_parts_parquet,
            "output-path-dir-parts-jsonl": output_path_dir_parts_jsonl,
        })
        return paths

    def run(self):
        paths = self.paths
        parts = self.full_config['split']['parts']
        
        if os.path.exists(paths['output-path-dir-parts-parquet']) and os.path.exists(paths['output-path-dir-parts-jsonl']):
            logging.info("Los subdatasets (split) ya existen. Saltando paso.")
            return

        logging.info('-'*30 + ' DIVIDIR PARQUET Y JSONL ' + '-'*30)

        os.makedirs(paths['output-path-dir-parts-parquet'], exist_ok=True)
        os.makedirs(paths['output-path-dir-parts-jsonl'], exist_ok=True)
            
        # Leemos el dataset limpio
        df = load_parquet(paths['path-file-corpus-clean'])
        total_filas = len(df)
        filas_por_parte = total_filas // parts

        logging.info(f"Dividiendo {total_filas} filas en {parts} partes (~{filas_por_parte} filas/parte).")

        for i in tqdm(range(parts), desc="Exportando partes"):
            inicio = i * filas_por_parte
            # Ajuste para que la última parte tome todo el remanente
            fin = (i + 1) * filas_por_parte if i < parts - 1 else total_filas
            length = fin - inicio
            
            # Slice es zero-copy en Polars (muy rápido)
            sub_df = df.slice(inicio, length)
            
            part_name = f"archivo_parte_{i + 1}"
            
            # Guardar Parquet
            sub_df.write_parquet(os.path.join(paths['output-path-dir-parts-parquet'], f"{part_name}.parquet"))
            try: os.chmod(os.path.join(paths['output-path-dir-parts-parquet'], f"{part_name}.parquet"), 0o777)
            except Exception as e: pass
            
            # Guardar JSONL (NDJSON)
            sub_df.write_ndjson(os.path.join(paths['output-path-dir-parts-jsonl'], f"{part_name}.jsonl"))
            try: os.chmod(os.path.join(paths['output-path-dir-parts-jsonl'], f"{part_name}.jsonl"), 0o777)
            except Exception as e: pass
            
            logging.info(f"> Parte {i + 1}: filas {inicio} a {fin} guardadas.")
            
        logging.info("\n🎉 Pipeline finalizado exitosamente.")

def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de procesamiento de Corpus")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    return parser.parse_args()

def main():
    args = get_args()
    step = CorporaSplit(name=args.name, domain=args.domain, version=args.version)
    step.run()

if __name__ == "__main__":
    main()