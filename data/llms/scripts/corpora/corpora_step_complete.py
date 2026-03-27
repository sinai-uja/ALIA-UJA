import os
import sys
import glob
import json
import logging
import argparse
import polars as pl
from typing import Mapping, List

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_csv, load_parquet, sink_jsonl, sink_parquet, TokenManager
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
logging.info(f"Iniciando módulo {__file__}")

# ======================================================================

class CorporaComplete(CorporaStep):
    
    def get_paths(self):
        paths = self._get_base_paths("complete")
        config = self.paths_config
        name = self.name
        version = self.version
        domain = self.domain
        
        path_file_datatrove_corpus = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-datatrove'].format(domain=domain, name=name, format="parquet") 
            if version == -1 
            else config['path-file-corpus-datatrove-version'].format(domain=domain, name=name, version=version, format="parquet")
        )
        output_path_dir_corpus_enriched = os.path.join(
            paths['path-dir-corpus'],
            config['path-dir-corpus-enriched'].format(domain=domain, name=name) 
            if version == -1 
            else config['path-dir-corpus-enriched-version'].format(domain=domain, name=name, version=version)
        )
        output_path_file_enriched_corpus_parquet = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-enriched'].format(domain=domain, name=name, format="parquet") 
            if version == -1 
            else config['path-file-corpus-enriched-version'].format(domain=domain, name=name, version=version, format="parquet")
        )
        output_path_file_enriched_corpus_jsonl = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-enriched'].format(domain=domain, name=name, format="jsonl") 
            if version == -1 
            else config['path-file-corpus-enriched-version'].format(domain=domain, name=name, version=version, format="jsonl")
        )
        
        path_file_mapping_dataset = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            config["path-file-mapping-dataset"]
        )
        path_file_mapping_feature = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            config["path-file-mapping-feature"]
        )
        
        paths.update({
            "path-file-datatrove-corpus": path_file_datatrove_corpus,
            "output-path-dir-corpus-enriched": output_path_dir_corpus_enriched,
            "output-path-file-enriched-corpus-parquet": output_path_file_enriched_corpus_parquet,
            "output-path-file-enriched-corpus-jsonl": output_path_file_enriched_corpus_jsonl,
            "path-file-mapping-dataset": path_file_mapping_dataset,
            "path-file-mapping-feature": path_file_mapping_feature
        })
        return paths

    def aggregate_corpus(self, dir_path: str, output_path: str) -> pl.DataFrame | None:
        """
        Agrega todos los archivos parquet en un directorio en un único DataFrame y lo guarda.
        """
        try:
            list_parquet = glob.glob(os.path.join(dir_path, "*.parquet"))
            if not list_parquet:
                logging.error(f"No se encontraron ficheros parquet en {dir_path}")
                return None

            logging.info(f"Agregando {len(list_parquet)} ficheros parquet desde {dir_path}...")
            df = (
                pl.scan_parquet(
                    list_parquet,
                    cast_options=pl.ScanCastOptions(extra_struct_fields="ignore")
                )
                .collect(engine="auto")
            )
            return df
        except Exception as e:
            logging.exception(f"Error al agregar los ficheros del corpus en {output_path}: {e}")
            return None

    def map_corpus_source_id(self, corpus: pl.DataFrame, mapping: pl.DataFrame) -> pl.DataFrame:
        """
        Aplica el mapping al campo source_id del corpus para unificar datasets.
        """
        return (
            corpus
            .join(mapping, left_on="source_id", right_on="original_dataset", how="left")
            .with_columns(
                pl.when(pl.col("mapped_dataset").is_not_null())
                .then(pl.col("mapped_dataset"))
                .otherwise(pl.col("source_id"))
                .alias("source_id")
            )
            .select(["source_id", "id", "text"])
            .sort("source_id")
        )

    def map_dataset_features(
        self,
        dataset: pl.DataFrame,
        mapping: pl.DataFrame | Mapping[str, str],
    ) -> pl.DataFrame:
        """
        Renombra columnas del dataset según un mapping original->nuevo.
        """
        
        logging.info("Mapping dataset features...")
        logging.info(f"\t> Original columns: {dataset.columns}")
        
        if isinstance(mapping, pl.DataFrame):
            required_cols = {"original_column_name", "mapped_column_name"}
            missing = required_cols.difference(mapping.columns)
            if missing:
                logging.error(
                    f"mapping DataFrame must contain columns {required_cols}, "
                    f"missing: {sorted(missing)}"
                )
                sys.exit(1)

            # Construye dict {original: nuevo}
            mapping_dict = dict(
                zip(
                    mapping["original_column_name"].to_list(),
                    mapping["mapped_column_name"].to_list(),
                )
            )
        else:
            mapping_dict = dict(mapping)

        if not mapping_dict:
            # No hay nada que mapear; devuelve copia defensiva
            return dataset.clone()

        # Filtra solo columnas que existen en el dataset
        applicable_mapping = {
            old: new for old, new in mapping_dict.items() if old in dataset.columns
        }

        if not applicable_mapping:
            # Ninguna columna a renombrar; devuelve copia defensiva
            return dataset.clone()

        # Usa DataFrame.rename con dict old->new (no muta el original, devuelve nuevo df)
        new_dataset = dataset.rename(applicable_mapping) 
        
        logging.info(f"\t> Mapped columns: {new_dataset.columns}")
        
        return new_dataset

    def get_unique_datasets(self, corpus: pl.DataFrame) -> list[str]:
        """
        Obtiene la lista ordenada de datasets únicos en el corpus.
        """
        return sorted(corpus["source_id"].unique().to_list())

    def find_parquet_files(self, dataset_path_template: str, domain: str) -> list[str]:
        """
        Busca recursivamente todos los archivos parquet en el directorio especificado para un dominio.
        """
        base_dir = dataset_path_template.format(domain=domain)
        parquet_files = [
            os.path.join(root, file)
            for root, _, files in os.walk(base_dir)
            for file in files
            if file.endswith(".parquet")
        ]
        return parquet_files

    def process_dataset(
        self,
        ds: str,
        datasets_metadata_cols: list[str],
        mapping: pl.DataFrame,
        corpus: pl.DataFrame,
        parquet_files: list[str],
        output_dir: str,
        force: bool
    ) -> None:
        """
        Procesa un dataset específico: carga, enriquece con metadatos y guarda si no existe o si force=True.
        """
        try:
            dataset_path = next(
                (p for p in parquet_files if os.path.basename(os.path.dirname(p)) == ds),
                None
            )
            if not dataset_path:
                logging.error(f"\t⚠️ Dataset '{ds}' not found in processed datasets.")
                return

            output_path = os.path.join(output_dir, f"{ds}.parquet")
            if os.path.exists(output_path) and not force:
                logging.info(f"\t✅ Enriched dataset '{ds}' already exists. Skipping...")
                return

            logging.info(f"Processing dataset: {ds}")

            try:
                dataset = load_parquet(dataset_path)
                
                # Safe casting: skip List, Array, Struct types; cast others to Utf8
                cast_exprs = []
                for c in dataset.columns:
                    dtype = dataset.schema[c]
                    if dtype not in [pl.List, pl.Array, pl.Struct]:
                        cast_exprs.append(pl.col(c).cast(pl.Utf8))
                
                if cast_exprs:
                    dataset = dataset.with_columns(cast_exprs)
                
            except Exception as e:
                logging.exception(f"Error al leer el dataset {dataset_path}: {e}")
                return

            subset = corpus.filter(pl.col("source_id") == ds)
            
            # Map dataset columns
            dataset = self.map_dataset_features(dataset, mapping)
            metadata_cols = [c for c in datasets_metadata_cols if c in dataset.columns]

            if metadata_cols:
                joined = dataset.select(["id"] + metadata_cols).join(
                    subset,
                    on="id",
                    how="left"
                )
                enriched = (
                    joined.with_columns(
                        pl.struct([pl.col(c) for c in metadata_cols])
                        .map_elements(
                            lambda x: json.dumps(x, ensure_ascii=False),
                            return_dtype=pl.Utf8
                        )
                        .alias("metadata")
                    )
                    .select(["source_id", "id", "text", "metadata"])
                    .filter(pl.col("text").is_not_null())  # Solo filas con text
                )
            else:
                enriched = (
                    subset.with_columns(pl.lit("{}").alias("metadata"))
                    .select(["source_id", "id", "text", "metadata"])
                )

            example = enriched.head(1).select(pl.exclude("text"))
            with pl.Config(fmt_str_lengths=200, tbl_rows=1):
                print(f"Example\n{example} > metadata fields: {metadata_cols}")

            # Save token count
            tm = TokenManager()
            logging.info("Calculando tokens (esto puede tardar)...")
            # Añadir columna tokens
            complete_enriched = tm.add_tokens_column_to_dataset(dataset=enriched, text_column="text")
            sink_parquet(complete_enriched, output_path)
            try:
                os.chmod(output_path, 0o777)
            except Exception:
                pass
            logging.info(f"✅ Saved enriched dataset: {os.path.basename(output_path)}\n")

        except Exception as e:
            logging.exception(f"❌ [FATAL] Error processing dataset '{ds}': {e}")

    def run(self):
        paths = self.paths
        config = self.full_config
        domain = self.domain
        name = self.name
        force = self.force
        
        os.makedirs(paths['output-path-dir-corpus-enriched'], exist_ok=True)

        # 4. Procesar corpus enriquecido solo si no existe o si se fuerza
        if os.path.exists(paths['output-path-file-enriched-corpus-parquet']) and not force:
            if not os.path.exists(paths['output-path-file-enriched-corpus-jsonl']):
                logging.warning(f"El corpus enriched parquet '{name}' ya existe, pero no el JSONL. Generando JSONL...")
                # Convertir Parquet a JSONL
                df = load_parquet(paths['output-path-file-enriched-corpus-parquet'])
                sink_jsonl(df, paths['output-path-file-enriched-corpus-jsonl'])
                try: os.chmod(paths['output-path-file-enriched-corpus-jsonl'], 0o777)
                except Exception as e: pass
                logging.info(f"✅ Corpus JSONL guardado en: {paths['output-path-file-enriched-corpus-jsonl']}")
            logging.info("El corpus enriquecido ya existe. Use --force para reprocesar.")
            return

        logging.info("Loading corpus...")
        if not os.path.exists(paths['path-file-datatrove-corpus']):
            logging.error(f"No se encontró el corpus en {paths['path-file-datatrove-corpus']}")
            sys.exit(1)
        corpus_datatrove = load_parquet(paths['path-file-datatrove-corpus'])

        # Asegurarse de que 'source_id' existe
        if "source_id" not in corpus_datatrove.columns:
            logging.warning("El corpus no contiene la columna 'source_id'. Creando a partir de 'metadata'...")
            corpus_datatrove = corpus_datatrove.with_columns(
                pl.col("metadata").struct.field("source_id").alias("source_id")
            )
            corpus_datatrove = corpus_datatrove.drop("metadata")
            logging.info("Columna 'source_id' creada.")
        
        # Obtener lista de datasets únicos (mapping I)
        logging.info("Loading 'dataset_id' mapping...")
        if not os.path.exists(paths['path-file-mapping-dataset']):
            logging.warning(f"No se encontró el fichero de mapping: {paths['path-file-mapping-dataset']}. Saltando mapping...")
        else:
            dataset_mapping = load_csv(paths['path-file-mapping-dataset'])
            logging.info("Mapping corpus source_id...")
            corpus_datatrove = self.map_corpus_source_id(corpus_datatrove, dataset_mapping)
        datasets = self.get_unique_datasets(corpus_datatrove)
        logging.info(f"> Found {len(datasets)} datasets.")

        # Obtener lista de datasets únicos post-mapping
        logging.info("Loading feature mapping...")
        try: 
            columns_metadata = config["completion"]["features"][domain]
        except KeyError:
            logging.warning(f"No se encontraron features para el dominio '{domain}' en la configuración. Enriqueciendo el corpus con todas las disponibles...")
            columns_metadata = []
        
        parquet_files = self.find_parquet_files(paths["path-root-data"], domain)
        if not os.path.exists(paths['path-file-mapping-feature']):
            logging.error(f"No se encontró el fichero de mapping: {paths['path-file-mapping-feature']}. Saltando mapping...")
        else:    
            dataset_mapping = load_csv(paths['path-file-mapping-feature'])
            logging.info("Mapping corpus features...")
        
        for ds in datasets:
            self.process_dataset(
                ds, 
                columns_metadata, 
                dataset_mapping,
                corpus_datatrove, 
                parquet_files, 
                paths['output-path-dir-corpus-enriched'], 
                force
            )

        logging.info("Corpus enriquecido guardado correctamente.")

        # 5. Agregar corpus enriquecido
        corpus_enriched = self.aggregate_corpus(paths['output-path-dir-corpus-enriched'], paths['output-path-file-enriched-corpus-parquet'])
        
        # Comprobar que 'corpus_enriched' tiene la columna 'tokens'
        if 'tokens' not in corpus_enriched.columns: # type: ignore
            logging.info("Calculando tokens para el corpus enriquecido...")
            tm = TokenManager()
            corpus_enriched = tm.add_tokens_column_to_dataset_efficient(dataset=corpus_enriched, text_column="text") # type: ignore
        
        if corpus_enriched is not None:
            # 6. Guardar corpus enriquecido
            logging.info(f"Guardando corpus enriquecido en: {os.path.basename(paths['output-path-file-enriched-corpus-parquet'])}")
            sink_parquet(corpus_enriched, paths['output-path-file-enriched-corpus-parquet'])
            logging.info(f"Guardando corpus enriquecido en: {os.path.basename(paths['output-path-file-enriched-corpus-jsonl'])}")
            sink_jsonl(corpus_enriched, paths['output-path-file-enriched-corpus-jsonl'])
        
        logging.info("\n🎉 Pipeline finalizado exitosamente.")

def get_args():
    """Captura los argumentos de la línea de comandos."""
    parser = argparse.ArgumentParser(description="Script de enriquecimiento de Corpus")
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
    step = CorporaComplete(name=args.name, domain=args.domain, version=args.version, force=args.force)
    step.run()

if __name__ == "__main__":
    main()
