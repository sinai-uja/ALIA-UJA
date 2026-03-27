import os, sys
import argparse
import logging
import polars as pl
from bs4 import BeautifulSoup
from typing import List, Mapping

# Importación de utilidades locales
sys.path.append(os.path.realpath("."))
from utils.utils_alia import load_parquet, sink_parquet, sink_jsonl, ALIACorporaUtils, TokenManager
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

class CorporaClean(CorporaStep):
    
    def get_paths(self):
        paths = self._get_base_paths("clean")
        config = self.paths_config
        name = self.name
        version = self.version
        
        path_file_corpus_initial = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-initial'].format(name=name, format="parquet")  
            if version == -1 
            else config['path-file-corpus-initial-version'].format(name=name, version=version, format="parquet")
        )
        output_path_file_corpus_clean_parquet = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-clean'].format(name=name, format="parquet") 
            if version == -1 
            else config['path-file-corpus-initial-clean'].format(name=name, version=version, format="parquet")
        )
        output_path_file_corpus_clean_jsonl = os.path.join(
            paths['path-dir-corpus'],
            config['path-file-corpus-clean'].format(name=name, format="jsonl") 
            if version == -1 
            else config['path-file-corpus-initial-clean'].format(name=name, version=version, format="jsonl")
        )
        
        paths.update({
            "path-file-corpus-initial": path_file_corpus_initial,
            "output-path-file-corpus-clean-parquet": output_path_file_corpus_clean_parquet,
            "output-path-file-corpus-clean-jsonl": output_path_file_corpus_clean_jsonl
        })
        return paths

    def _log_changes(self, original_texts: List, modified_texts: List):
        """Log detailed changes between original and modified text."""
        
        # Log detailed changes (same as clean() method)
        logging.info("\n=== DETAILED CHANGES ===")
        changes_count = 0
        
        for i, (original, modified) in enumerate(zip(original_texts, modified_texts)):
        
            logging.info(f"\n=== SUMMARY ===")
            logging.info(f"Modified {changes_count} out of {len(original_texts)} rows")
    
            
            logging.info(f"\nRow {i}:")
            
            # Show preview of original and modified
            orig_preview = original[:100].replace('\n', '\\n') if original else ""
            mod_preview = modified[:100].replace('\n', '\\n') if modified else ""
            logging.info(f"  Original: {orig_preview}{'...' if len(original) > 100 else ''}")
            logging.info(f"  Modified: {mod_preview}{'...' if len(modified) > 100 else ''}")
            
            # Identify specific changes
            changes_applied = []
            if '#' in original and '#' not in modified:
                hash_count = original.count('#')
                changes_applied.append(f"Removed {hash_count} '#' character(s)")
            
            import re
            img_pattern = r'!\[.*?\]\(.*?\)'
            orig_imgs = re.findall(img_pattern, original)
            if orig_imgs:
                changes_applied.append(f"Removed {len(orig_imgs)} markdown image(s)")
            
            # Check for newline reduction
            orig_newlines = len(re.findall(r'[\r\n]{2,}', original))
            if orig_newlines > 0:
                changes_applied.append(f"Reduced {orig_newlines} multiple newline sequence(s)")

            wiki_section_pattern = r'(?m)^\s*=+\s*(.+?)\s*=+\s*$'
            if re.search(wiki_section_pattern, original):
                changes_applied.append("Normalized Wikipedia section header(s)")

            missing_punct_before_newline = r'([^\s\.,;:!?\)\]\}\"\'»”])\r?\n\s*([A-ZÁÉÍÓÚÜÑ])'
            if re.search(missing_punct_before_newline, original):
                changes_applied.append("Added '.' before newline where punctuation was missing and next line started with uppercase")
            
            if changes_applied:
                logging.info(f"  Changes: {'; '.join(changes_applied)}")
        
        logging.info(f"\n=== SUMMARY ===")
        logging.info(f"Modified {changes_count} out of {len(original_texts)} rows")

    def clean_html(self, html_content):
        """
        Deletes HTML content and returns clean text.
        """
        if not isinstance(html_content, str):
            raise TypeError("El contenido debe ser una cadena de texto (str).")
        
        # Analiza el HTML
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Obtiene el texto sin etiquetas, eliminando espacios extra
        clean_text = soup.get_text(separator=" ", strip=True)
        
        return clean_text

    def _apply_transformations(self, config: Mapping[str, str], df: pl.DataFrame) -> pl.DataFrame:
        """Apply configured transformations to a DataFrame."""
        
        # Get the column name to transform
        text_column_name = config.get('text-column', 'text')
        
        # Start with the column expression
        text_col = pl.col(text_column_name)
        
        # try:
        #     if config.get('remove-html', True):
        #         text_col = text_col.map_elements(self.clean_html, return_dtype=pl.String)
        # except Exception as e:
        #     logging.error(f"> Error removing HTML: {e}")
        
        try:
            if config.get('remove-titles', True):
                text_col = text_col.str.replace_all(r"#", "", literal=True)
        except Exception as e:
            logging.error(f"> Error removing '#' characters: {e}")
        
        try:
            if config.get('remove-urls', True):
                text_col = text_col.str.replace_all(r"!\[.*?\]\(.*?\)", "")
        except Exception as e:
            logging.error(f"> Error removing images: {e}")
        
        try:
            if config.get('remove-skiplines', True):
                text_col = text_col.str.replace_all(r"[\r\n]{2,}", "\n")
        except Exception as e:
            logging.error(f"> Error reducing newlines: {e}")

        try:
            if config.get('normalize-wikipedia-sections', True):
                text_col = text_col.str.replace_all(
                    r"(?m)^\s*=+\s*(.+?)\s*=+\s*$",
                    r"$1:"
                )
        except Exception as e:
            logging.error(f"> Error normalizing Wikipedia sections: {e}")

        try:
            if config.get('add-dot-before-newline', True):
                text_col = text_col.str.replace_all(
                    r"([^\s\.,;:!?\)\]\}\"'»”])\r?\n\s*([A-ZÁÉÍÓÚÜÑ])",
                    "$1.\n$2"
                )
        except Exception as e:
            logging.error(f"> Error adding punctuation before newlines: {e}")
        
        # Alias back to the original column name to replace it
        transformed_df = df.with_columns(text_col.alias(text_column_name))
        return transformed_df

    def clean_dataframe(self, config: Mapping[str, str], df: pl.DataFrame, log_changes: bool = True) -> pl.DataFrame:
        """Clean a Polars DataFrame directly without reading from file."""
        logging.info(f"> Starting cleaning process for DataFrame with {len(df)} rows")
        
        # Apply transformations
        df_modified = self._apply_transformations(config, df)
        logging.info(f"> Transformations applied. 🧮 Current shape: {df_modified.shape}")
        
        # Log detailed changes
        if log_changes:
            original_texts = df[config.get('text-column', 'text')].to_list()
            modified_texts = df_modified[config.get('text-column', 'text')].to_list()
            self._log_changes(original_texts, modified_texts)
        
        logging.info("> ✅ Cleaning process completed.")
        
        return df_modified

    def process_cleaning(self, config: Mapping[str, str], name: str, corpus: pl.DataFrame):
        """Limpia el texto del corpus."""
        logging.info('-'*30 + ' LIMPIAR EL TEXTO ' + '-'*30)
        try:
            # Leemos lazy para optimizar memoria antes de procesar        
            logging.info(f"Aplicando limpieza regex a {len(corpus)} filas...")
            # Aplicamos la limpieza. 
            corpus_clean = self.clean_dataframe(config = config, df = corpus, log_changes = False)  
        except Exception as e:
            logging.error(f"Error durante la limpieza de {name}: {e}")
            corpus_clean = corpus.clone() 
        return corpus_clean

    def run(self):
        paths = self.paths
        config: Mapping[str, str] = self.full_config['clean']
        name = self.name
        
        # 1 - Comprobar si ya existe el corpus
        if os.path.exists(paths['output-path-file-corpus-clean-parquet']):
            if not os.path.exists(paths['output-path-file-corpus-clean-jsonl']):
                logging.warning(f"El corpus clean parquet '{name}' ya existe, pero no el JSONL. Generando JSONL...")
                # Convertir Parquet a JSONL
                df = load_parquet(paths['output-path-file-corpus-clean-parquet'])
                sink_jsonl(df, paths['output-path-file-corpus-clean-jsonl'])
                try: os.chmod(paths['output-path-file-corpus-clean-jsonl'], 0o777)
                except Exception as e: pass
                logging.info(f"✅ Corpus JSONL guardado en: {paths['output-path-file-corpus-clean-jsonl']}")
            logging.info(f"El corpus clean '{name}' ya existe. Saltando paso.")
            # (*) Contar tokens y actualizar info
            ALIACorporaUtils.count_corpus_tokens(
                input_path_corpus= paths['output-path-file-corpus-clean-parquet'], 
                output_path_file_token_count_csv= paths['stats-path-file-count']
            )
            ALIACorporaUtils.update_corpus_info(
                path_file_info_json= paths['path-file-info'], 
                input_path_file_token_count_csv= paths['stats-path-file-count'], 
                step= "clean"
            )
            return
        
        # 2. Leer corpus inicial
        logging.info(f"Leyendo corpus inicial desde: {os.path.basename(paths['path-file-corpus-initial'])}")
        try:
            corpus_initial = load_parquet(paths['path-file-corpus-initial'])
        except Exception as e:
            logging.error(f"No se pudo leer el corpus inicial: {e}")
            sys.exit(1)
        logging.info(f"> 🧮 Corpus leído con {corpus_initial.height} filas y {corpus_initial.width} columnas {corpus_initial.columns}.")
        
        # 3. Limpiar corpus
        corpus_clean = self.process_cleaning(
            name = name,
            config = config,
            corpus = corpus_initial,
        )
        tokenizer = TokenManager()
        corpus_clean = tokenizer.add_tokens_column_to_dataset_efficient(dataset= corpus_clean, text_column=config.get('text-column', 'text'))
        
        logging.info(f"> 🧮 Corpus limpio con {corpus_clean.height} filas y {corpus_clean.width} columnas {corpus_clean.columns}.")
        
        # 4. Guardar corpus limpio
        logging.info(f"Guardando corpus limpio en: {os.path.basename(paths['output-path-file-corpus-clean-parquet'])}")
        sink_parquet(corpus_clean, paths['output-path-file-corpus-clean-parquet'])
        logging.info(f"Guardando corpus limpio en: {os.path.basename(paths['output-path-file-corpus-clean-jsonl'])}")
        sink_jsonl(corpus_clean, paths['output-path-file-corpus-clean-jsonl'])
        try: 
            os.chmod(paths['output-path-file-corpus-clean-parquet'], 0o777)
            os.chmod(paths['output-path-file-corpus-clean-jsonl'], 0o777)
        except Exception as e: pass
        del corpus_clean
        
        # 5. Contar tokens y actualizar info
        ALIACorporaUtils.count_corpus_tokens(
            input_path_corpus= paths['output-path-file-corpus-clean-parquet'], 
            output_path_file_token_count_csv= paths['stats-path-file-count']
        )
        ALIACorporaUtils.update_corpus_info(
            path_file_info_json= paths['path-file-info'], 
            input_path_file_token_count_csv= paths['stats-path-file-count'], 
            step= "clean"
        )
        
        logging.info("\n🎉 Pipeline finalizado exitosamente.")

def get_args():
    parser = argparse.ArgumentParser(description="Datatrove Curation Pipeline")
    parser.add_argument("--name", required=True, type=str, help="Nombre del corpus")
    parser.add_argument("--domain", required=True, type=str, help="Dominio del corpus")
    parser.add_argument("--version", type=int, default=-1, help="Versión del corpus (default: -1)")
    return parser.parse_args()

def main():
    args = get_args()
    step = CorporaClean(name=args.name, domain=args.domain, version=args.version)
    step.run()

if __name__ == "__main__":
    main()
