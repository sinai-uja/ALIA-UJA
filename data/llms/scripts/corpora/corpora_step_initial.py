import polars as pl
import os
import json
import sys
import argparse
import logging
from tqdm import tqdm

# Importación de utilidades locales
sys.path.append(os.path.realpath("."))
from utils.utils_alia import load_parquet, sink_parquet, sink_jsonl, ALIACorporaUtils
try:
    from scripts.corpora.corpora_base import CorporaStep
except ImportError:
    from corpora_base import CorporaStep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# ======================================================================

class CorporaInitial(CorporaStep):
    
    def get_paths(self):
        paths = self._get_base_paths("initial")
        config = self.paths_config
        name = self.name
        version = self.version
        domain = self.domain

        output_path_file_corpus_initial_parquet = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-initial'].format(name=name, format="parquet")  
            if version == -1 
            else config['path-file-corpus-initial-version'].format(name=name, version=version, format="parquet")
        )
        output_path_file_corpus_initial_jsonl = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-initial'].format(name=name, format="jsonl")  
            if version == -1 
            else config['path-file-corpus-initial-version'].format(name=name, version=version, format="jsonl")
        )
        
        paths.update({
            "output-path-file-corpus-initial-parquet": output_path_file_corpus_initial_parquet,
            "output-path-file-corpus-initial-jsonl": output_path_file_corpus_initial_jsonl
        })
        return paths

    def run(self):
        """Genera la primera versión del corpus uniendo datasets."""
        paths = self.paths
        name = self.name
        
        # 1 - Comprobar si ya existe el corpus
        if os.path.exists(paths['output-path-file-corpus-initial-parquet']):
            if not os.path.exists(paths['output-path-file-corpus-initial-jsonl']):
                logging.warning(f"El corpus initial parquet '{name}' ya existe, pero no el JSONL. Generando JSONL...")
                # Convertir Parquet a JSONL
                df = load_parquet(paths['output-path-file-corpus-initial-parquet'])
                sink_jsonl(df, paths['output-path-file-corpus-initial-jsonl'])
                try: os.chmod(paths['output-path-file-corpus-initial-jsonl'], 0o777)
                except Exception as e: pass
                logging.info(f"✅ Corpus JSONL guardado en: {paths['output-path-file-corpus-initial-jsonl']}")
            logging.info(f"El corpus initial '{name}' ya existe. Saltando paso.")
            # (*) Contar tokens y actualizar info
            ALIACorporaUtils.count_corpus_tokens(
                input_path_corpus= paths['output-path-file-corpus-initial-parquet'], 
                output_path_file_token_count_csv= paths['stats-path-file-count']
            )
            ALIACorporaUtils.update_corpus_info(
                path_file_info_json= paths['path-file-info'], 
                input_path_file_token_count_csv= paths['stats-path-file-count'], 
                step= "initial"
            )
            return

        logging.info('-'*30 + ' GENERAR PRIMERA VERSIÓN ' + '-'*30)
        
        # 2 - Cargar info del corpus
        if not os.path.exists(paths['path-file-info']):
            logging.error(f"No se encuentra el archivo de información: {paths['path-file-info']}")
            sys.exit(1)
        corpus_info = json.load(open(paths['path-file-info'], "r"))
        if "datasets" not in corpus_info:
            logging.error(f"El archivo de información no contiene la clave 'datasets': {paths['path-file-info']}")
            sys.exit(1)
        if corpus_info['datasets'] is None or len(corpus_info['datasets']) == 0:
            logging.error(f"No hay datasets listados en el archivo de información: {paths['path-file-info']}")
            sys.exit(1)

        # 3 - Construir el corpus uniendo datasets
        logging.info(f"Construyendo corpus '{name}' con {len(corpus_info['datasets'])} datasets...")
        lazy_frames = []
        for d in tqdm(corpus_info['datasets'], desc="Escaneando datasets"):
            parquet_path = os.path.join(paths['path-root-data'], d, "dataset.parquet")
            if os.path.exists(parquet_path):
                lf = (
                    pl.scan_parquet(parquet_path)
                    .select([
                        pl.col('id').cast(pl.Utf8),
                        pl.col('text').cast(pl.Utf8)
                    ])
                    .with_columns(pl.lit(d).alias("source_id"))
                )
                lazy_frames.append(lf)
            else:
                logging.warning(f"⚠️ No se encontró parquet para {d}")
        
        if lazy_frames:
            # Usamos sink_parquet para streaming (eficiente en memoria)
            corpus_initial: pl.LazyFrame = pl.concat(lazy_frames)
            logging.info(f"Escribiendo corpus inicial en parquet...")
            sink_parquet(
                df=corpus_initial,
                file_path=paths['output-path-file-corpus-initial-parquet']
            )
            logging.info(f"Escribiendo corpus inicial en JSONL...")
            sink_jsonl(
                df=corpus_initial,
                file_path=paths['output-path-file-corpus-initial-jsonl']
            )
            try: 
                os.chmod(paths['output-path-file-corpus-initial-parquet'], 0o777)
                os.chmod(paths['output-path-file-corpus-initial-jsonl'], 0o777)
            except Exception as e: pass
            logging.info(f"✅ Corpus guardado en: {os.path.basename(paths['output-path-file-corpus-initial-parquet'])} y {os.path.basename(paths['output-path-file-corpus-initial-jsonl'])}")
        else:
            logging.error("No se encontraron datasets válidos para concatenar.")

        del corpus_initial
        
        # 5. Contar tokens y actualizar info
        ALIACorporaUtils.count_corpus_tokens(
            input_path_corpus= paths['output-path-file-corpus-initial-parquet'], 
            output_path_file_token_count_csv= paths['stats-path-file-count']
        )
        ALIACorporaUtils.update_corpus_info(
            path_file_info_json= paths['path-file-info'], 
            input_path_file_token_count_csv= paths['stats-path-file-count'], 
            step= "initial"
        )
            
        logging.info("🎉 Pipeline finalizado exitosamente.")

def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de procesamiento de Corpus")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    return parser.parse_args()

def main():
    args = get_args()
    step = CorporaInitial(name=args.name, domain=args.domain, version=args.version)
    step.run()

if __name__ == "__main__":
    main()
