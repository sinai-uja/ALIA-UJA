import os, sys
import logging
from abc import ABC, abstractmethod
from typing import Dict
import polars as pl
from pathlib import Path 
import re, glob
import gc

# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import load_parquet, load_jsonl, ALIADataUtils
from utils.utils_alia import write_csv, write_jsonl, write_parquet
try:
    from scripts.instructions.corpora.instructions_step_base import InstructionsStep
except ImportError:
    from instructions_step_base import InstructionsStep

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

class InstructionsInitialStep(InstructionsStep):
    
    def __init__(
        self,
        domain: str,
        lang: str = "es",
        force: bool = False,
    ):
        super().__init__(domain, lang, force)
        self.config = self.load_step_config(self.full_config, 'initial')
    
    def get_paths(self):
        
        """Centraliza la lógica de generación de rutas para evitar condicionales repetidos."""
        
        paths = self._get_base_paths() # type: ignore
        config = self.paths_config
        path_dir_datasets_proccesed = os.path.join(
            paths['path-dir-datasets-instructions'], 
            "processed",
            self.domain,
            self.lang
        )
        os.makedirs(path_dir_datasets_proccesed, exist_ok=True)
        
        paths['path-file-initial-instructions-parquet'] = os.path.join(
            path_dir_datasets_proccesed,
            config['path-file-initial-instructions'].format(
                domain=self.domain, 
                lang=self.lang,
                format="parquet"
            )
        )
        paths['path-file-initial-instructions-jsonl'] = os.path.join(
            path_dir_datasets_proccesed,
            config['path-file-initial-instructions'].format(
                domain=self.domain, 
                lang=self.lang,
                format="jsonl"
            )
        )
        paths['path-file-stats'] = os.path.join(
            paths['path-dir-stats-instructions'],
            config['path-file-stats-instructions'].format(
                domain=self.domain, 
                lang=self.lang,
                step="initial",
                suffix="",
            ).replace("--", "-")
        )
        
        return paths

    # Format datasets
    
    def format_domain_instruction_dataset(
        self,
        dataset: pl.DataFrame,  # type: ignore
        dataset_path: str
    ) -> pl.DataFrame:
        
        """Formatea el corpus para tareas de instrucción. (Igual que original)"""
        logging.info("Formatting instruction corpus...")
        
        # 0. Validaciones básicas (columnas requeridas)
        if "System prompt" in dataset.columns: dataset = dataset.rename({"System prompt": "system_prompt"})
        if "Question" in dataset.columns: dataset = dataset.rename({"Question": "question"})
        if "Response" in dataset.columns: dataset = dataset.rename({"Response": "response"})
        required = {"question", "response"}
        missing = required - set(dataset.columns)
        if missing:
            logging.error(f"El dataset debe contener las columnas {missing} para formatear a formato conversación.")
            raise ValueError(f"El dataset debe contener las columnas {missing} para formatear a formato conversación.")
        if "system_prompt" not in dataset.columns:
            dataset = dataset.with_columns(pl.lit("").alias("system_prompt"))

        # 1. Combinar prompt, question y response en 'instruction'
        dataset = dataset.with_columns(
            pl.concat_str([
                pl.col("system_prompt"), pl.lit("\n"), 
                pl.col("question"), pl.lit("\n"), 
                pl.col("response")
            ]).alias(self.config['text-column'])
        )
        
        # 2. Extraer tipos de instrucción del nombre del fichero
        logging.info("\t\tExtracting instruction types from filename...")
        filename = Path(dataset_path).name  # Formato: datos_sinteticos-{criteria_1}-{criteria_2}(-{criteria_3}.jsonl
        criterias = []
        try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
        except: criteria_names = []
        if criteria_names: 
            # 1. Extraer criterios del nombre del archivo usando regex
            match = re.match(self.config['pattern'], filename.replace(".jsonl", ""))
            if match:
                grupos = re.split(r'-', match.group(1))
                for i in range(len(grupos)):
                    criterias.append(grupos[i])
                logging.info(f"Los campos resuperados han sido: {criterias}")
            else:
                raise ValueError(f"El nombre del archivo no cumple con el formato esperado: {filename}")
            dataset = dataset.with_columns(
                [ pl.lit(criteria).cast(pl.Utf8).alias(criteria_names[i]) for i, criteria in enumerate(criterias) ]
            )
            if len(criterias) == len(criteria_names) or not criteria_names:
                logging.info(f"Los criterios extraídos ({len(criterias)}) coinciden con el número de nombres de criterios configurados ({len(criteria_names)}).")
                logging.info(f"> Mapping: {dict(zip(criteria_names, criterias))}")
            else:
                logging.error(f"El número de criterios extraídos {criterias}({len(criterias)}) no coincide con el número de nombres de criterios configurados {criteria_names}({len(criteria_names)})")
            # 2. Nueva columna
            logging.info("\t\tCreating instruction category column...")
            category = "-".join(criterias)
            dataset = dataset.with_columns(pl.lit(category).alias(self.config['category-column']))
            logging.info(f"  Category assigned: {category}")
        
        # 4. Número de tokens
        logging.info("Computing number of tokens for each instruction...")
        dataset = self.TOKENIZER.add_tokens_column_to_dataset_efficient(dataset=dataset, text_column=self.config['text-column'])
        logging.info(f"> Total tokens in corpus: {dataset['tokens'].sum():,}")
        
        # 5. Columnas finales
        if "id_chunk" in dataset.columns: # modificar 'id_chunk' por 'id'
            dataset = dataset.rename({"id_chunk": "id"})
        
        column_selection = []
        if "source_id" not in dataset.columns: 
            dataset = dataset.with_columns(pl.lit(f"general_{self.domain}_{self.lang}_{category}").alias("source_id"))
        if "id" not in dataset.columns: 
            dataset = dataset.with_columns(
                pl.concat_str([pl.col("source_id"), pl.col("source_id").cum_count().cast(pl.Utf8)], separator="_").alias("id")
            )
        column_selection = [
            "source_id", "id",
            "system_prompt", "question", "response", 
            self.config['text-column'], 
            "tokens", 
            self.config['category-column'],
        ]
        column_selection.extend(criteria_names)
        dataset = dataset.select(column_selection)
        
        logging.info(f"\tFormatted instruction corpus shape: {dataset.shape}")
        logging.info(f"\twith columns: {dataset.columns}")
        
        return dataset

    def format_general_instruction_dataset(
        self,
        dataset: pl.DataFrame,  # type: ignore
        dataset_path: str
    ) -> pl.DataFrame:
        """
        Deformat Conversation to structured format for general instructions.
        - Maps conversations to struct fields (adds missing system as empty).
        - Unnests to columns.
        - Renames _source_file to source_id.
        - Creates instruction by joining system_prompt, question, response with '\\n\\n'.
        - Selects only final columns.
        """
        
        def _extract_fields(conv_list):
            """
            Extracts system_prompt, question, and response from conversations list.
            Missing fields default to empty string.
            """
            system_prompt = ''
            question = ''
            response = ''
            for conv in conv_list:
                if conv['from'] == 'system':
                    system_prompt = conv['value']
                elif conv['from'] == 'human':
                    question = conv['value']
                elif conv['from'] == 'gpt':
                    response = conv['value']
            return {
                'system_prompt': system_prompt,
                'question': question,
                'response': response
            }
        
        source_id = re.search(self.config['pattern'], dataset_path).group(1) # if re.search(self.config['pattern'], dataset_path) else os.path.basename(dataset_path) # type: ignore

        
        logging.info("Deformatting corpus from conversation format...")
        
        select_columns = [
            self.config['category-column'],
            'id',
            'system_prompt',
            'question',
            'response',
            self.config['text-column']
        ]
        
        if self.config['category-column'] not in dataset.columns: 
            dataset = dataset.with_columns(pl.lit(source_id).alias(self.config['category-column']))
        if "source" in dataset.columns: 
            dataset = dataset.drop("source")
        
        if "id" not in dataset.columns: 
            dataset = dataset.with_columns(
                pl.concat_str([pl.col(self.config['category-column']), pl.col(self.config['category-column']).cum_count().cast(pl.Utf8)], separator="_").alias("id")
            )
        
        try:
            logging.info(f"Dataset columns before deformatting: {dataset.columns}")
            dataset = (
                dataset
                # add conversations columns
                .with_columns(
                    pl.col('conversations')
                    .map_elements(
                        _extract_fields,
                        return_dtype=pl.Struct([
                            pl.Field('system_prompt', pl.Utf8),
                            pl.Field('question', pl.Utf8),
                            pl.Field('response', pl.Utf8)
                        ])
                    )
                    .alias('fields')
                )
                .unnest('fields')
            )
            logging.info(f"Dataset columns after deformatting: {dataset.columns}")
        
        except Exception as e:
            logging.error(f"Error deformating corpus from conversation format: {e}")    
            
        dataset = (
            dataset
            .with_columns(
                pl.concat_str(
                    ['question', 'response'],
                    separator='\n'
                ).alias(self.config['text-column'])
            )
            .select(select_columns)
        )
        
        try:
            logging.info("Adding tokens column to dataset...")
            output_df = self.TOKENIZER.add_tokens_column_to_dataset_efficient(
                dataset, 
                text_column = self.config['text-column']
            )
        except Exception as e:
            logging.error(f"Error adding tokens column: {e}")
            return dataset
        
        return output_df

    # Run format datasets
    def format_instruction_datasets(self):
        
        path_dir_datasets_raw = os.path.join(self.paths['path-dir-datasets-instructions'], "raw", self.domain, self.lang)
        os.makedirs(path_dir_datasets_raw, exist_ok=True)
        logging.info(f"> Peeking: {path_dir_datasets_raw}")
        path_dir_datasets_interim = os.path.join(self.paths['path-dir-datasets-instructions'], "interim", self.domain, self.lang)
        os.makedirs(path_dir_datasets_interim, exist_ok=True)
        logging.info(f"> Peeking: {path_dir_datasets_interim}")
        
        raw_files = sorted(glob.glob(os.path.join(path_dir_datasets_raw, "*.jsonl")))
        raw_files_len = len(raw_files)
        
        logging.info(f"Processing instruction corpus in raw directory - {raw_files_len} files")
        
        for i, path_file_dataset_raw in enumerate(raw_files):
            
            logging.info(f"📑 Computing file {i+1} out of {raw_files_len} ({os.path.basename(path_file_dataset_raw)})")
            
            path_file_dataset_interim = os.path.join(
                path_dir_datasets_interim, 
                os.path.basename(path_file_dataset_raw) if self.domain != "general" else os.path.basename(path_file_dataset_raw).replace("_SFT", "")
            )
            
            if os.path.exists(path_file_dataset_interim):
                logging.info(f"\tFile {os.path.basename(path_file_dataset_raw)} already exists in {path_file_dataset_interim}")
                interim_dataset = load_jsonl(path_file_dataset_interim)
                try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
                except: criteria_names = []
                self.compute_stats(
                    interim_dataset, 
                    criteria_columns = criteria_names,
                    category_column = self.config['category-column'],
                    stats_name=f"Interim Dataset - {os.path.basename(path_file_dataset_raw)}"
                )
                continue
                    
            try:
                dataset = load_jsonl(path_file_dataset_raw)
            except Exception as e:
                logging.error(f"Error loading {path_file_dataset_raw}: {e}")
                continue
            
            logging.info(f"Loaded dataset with {dataset.shape[0]:,} instructions")
            
            # Formatear
            if self.domain == "general":
                interim_dataset = self.format_general_instruction_dataset(
                    dataset, 
                    os.path.basename(path_file_dataset_raw), 
                )
            else:
                interim_dataset = self.format_domain_instruction_dataset(
                    dataset, 
                    os.path.basename(path_file_dataset_raw)
                )
            
            # Guardar intermedio
            logging.info(f"Saving interim processed dataset to {path_file_dataset_interim}")
            write_jsonl(interim_dataset, path_file_dataset_interim)
            try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
            except: criteria_names = []
            self.compute_stats(
                interim_dataset, 
                criteria_columns = criteria_names,
                category_column = self.config['category-column'],
                stats_name=f"Interim Dataset - {os.path.basename(path_file_dataset_raw)}"
            )
            del interim_dataset
            gc.collect()
            logging.info("="*50 + "\n")
                
    def agreggate_instruction_datasets(self):
        
        # Combinar todos los intermedios en corpus procesado
        path_dir_datasets_interim = os.path.join(self.paths['path-dir-datasets-instructions'], "interim", self.domain, self.lang)
        logging.info("\tCombining all processed instruction datasets into a single corpus...")
        interim_files = sorted(glob.glob(os.path.join(path_dir_datasets_interim, "*.jsonl")))
        
        # Agregar el primer dataset
        processed_corpus = load_jsonl(interim_files[0])
        logging.info(f"\t- Current shape: {processed_corpus.shape}")
        
        for file in interim_files[1:]:
            df = pl.read_ndjson(file, schema=processed_corpus.schema)
            logging.info(f"\tIncluding interim file {file.split('/')[-1]}. Shape: {df.shape}")
            processed_corpus = processed_corpus.vstack(df)
            logging.info(f"\t- Current shape: {processed_corpus.shape}. Total tokens: {processed_corpus['tokens'].sum():,}")
            del df
        
        # Guardar corpus procesado final
        logging.info(f"\tSaving combined processed instruction corpus to {os.path.basename(self.paths['path-file-initial-instructions-parquet'])} and {os.path.basename(self.paths['path-file-initial-instructions-jsonl'])}")
        write_parquet(processed_corpus, self.paths['path-file-initial-instructions-parquet'])
        write_jsonl(processed_corpus, self.paths['path-file-initial-instructions-jsonl'])
        logging.info(f"\tProcessed instruction corpus saved with {processed_corpus.shape[0]:,} instructions.")
        
        # stats
        try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
        except: criteria_names = []
        stats = self.compute_stats(
            corpus = processed_corpus, 
            criteria_columns = criteria_names,
            category_column = self.config['category-column'],
            stats_name="Complete Initial Instruction Corpus"
        )
        write_csv(stats, self.paths['path-file-stats'])

    def run(self):
        
        """Genera la primera versión del corpus uniendo datasets."""
        logging.info(f"Running initial instruction processing step for domain {self.domain}")
               
        # Determinar ruta de salida del corpus formateado
        output_corpus_path = self.paths['path-file-initial-instructions-parquet']
        if self.config['special-input-file']: 
            output_corpus_path = self.config['special-input-file']
            
        # Cargar corpus existente si ya se ha generado previamente
        if os.path.exists(output_corpus_path):
            logging.info(f"Loading existing initial instruction corpus from {os.path.basename(output_corpus_path)}")
            corpus = ALIADataUtils.load_data(output_corpus_path)
            try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
            except: criteria_names = []
            stats = self.compute_stats(
                corpus = corpus, 
                criteria_columns = criteria_names,
                category_column = self.config['category-column'],
                stats_name="Complete Initial Instruction Corpus"
            )
            write_csv(stats, self.paths['path-file-stats'])
        else:
        # Si no existe corpus generado, crear uno nuevo
            self.format_instruction_datasets()
            self.agreggate_instruction_datasets()
        

        
