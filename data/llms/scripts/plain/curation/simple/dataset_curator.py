import logging
import os, sys
BASE_DIR = os.path.dirname(os.path.realpath(__file__)) # Samuel: he puesto las lineas 3 - 6 porque fallaba la curacion. He comentado las que se ven
ROOT_DIR = os.path.abspath(os.path.join(BASE_DIR, "../../"))
if ROOT_DIR not in sys.path:
    sys.path.append(ROOT_DIR)
# sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import polars as pl
import yaml
import sys
import gc
import time
from typing import Tuple
from utils.utils_alia import ALIADataUtils as autils
from documentation.documentation_generator import DocumentationGenerator
sys.path.append(os.path.abspath("./"))
from utils.utils_alia import TokenManager as UtilsTokenManager
import datetime

class DatasetCurator:
    
    """
    DatasetCurator is a class designed to manage the curation and processing of datasets, particularly for workflows involving YAML configuration, parquet files, and tokenization. It provides methods for validating configuration files, setting up logging, retrieving dataset paths, loading and unifying datasets, deduplicating data, adding token counts, and maintaining metadata about processed datasets.

    Attributes:
        config (dict): Loaded configuration from a YAML file.
        listado_recursos (str): Path to the YAML file listing available datasets.
        sr (DocumentationGenerator): Instance for generating YAML resource documentation.
        token_manager (TokenManager): Instance for managing tokenization of datasets.

    Methods:
        __init__():
            Initializes the DatasetCurator by loading configuration, validating it, setting up logging, and preparing resource/documentation managers.

        _validate_config():
            Validates the presence of required keys and paths in the configuration file.

        _setup_logging():
            Configures the logging format and level for the class.

        get_dataset_path(dataset_name: str) -> str:
            Retrieves the file path for a given dataset name from the YAML resource file.

        get_dataset(dataset_name: str) -> Tuple[pl.DataFrame, bool] | Tuple[str, bool]:
            Loads the dataset as a Polars DataFrame or returns the dataset path if multiple parquet files are found.

        union_datasets_add_column(dataset_path: str, dataset_name: str) -> pl.DataFrame:
            Combines multiple parquet files in a directory, adds a 'year' column, and ensures string columns are properly typed.

        process_dataset(dataset_name: str):
            Main method to process a dataset: loads, deduplicates, adds token counts, saves the processed dataset, and updates metadata.
    """
    
    def __init__(self):
        """
        Initializes the class by loading configuration from a YAML file, validating the configuration,
        setting up logging, and initializing required resources such as the documentation generator
        and token manager.

        Args:
            self (str): The instance of the class.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
            yaml.YAMLError: If there is an error parsing the YAML configuration file.
            KeyError: If required configuration keys are missing.
        """
        self.config = yaml.safe_load(
            open(os.path.abspath("data/llms/scripts/plain/config.yaml"), "r")
        )
        # self._validate_config()
        self._setup_logging()
        self.dg = DocumentationGenerator()
        self.token_manager = UtilsTokenManager()

    def _validate_config(self):
        """
        Validates the presence and correctness of required configuration keys and paths.

        Checks that all required keys are present in the configuration dictionary and that
        the specified directory and file exist. If any required key is missing or a path
        does not exist, logs an error and exits the program.

        Raises:
            SystemExit: If a required key is missing or a specified path does not exist.
            AssertionError: If the required file does not exist in the specified directory.
        """
        required_keys = ['tiktoken_dir', 'tiktoken_check', 'tiktoken_model', 'listadoRecursosInterim']
        for key in required_keys:
            if key not in self.config:
                logging.error(f"The config file does not contain '{key}'. Please check the config file.")
                sys.exit(1)
        if not os.path.exists(self.config['tiktoken_dir']):
            logging.error(f"The directory {self.config['tiktoken_dir']} does not exist. Please check the path.")
            sys.exit(1)
        assert os.path.exists(os.path.join(self.config['tiktoken_dir'], self.config['tiktoken_check']))

    def _setup_logging(self):
        """Sets up logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_dataset(self, dataset_path: str) -> Tuple[pl.DataFrame, bool] | Tuple[str, bool]:
        """
        Retrieves a dataset from the specified dataset name.

        Args:
            dataset_name (str): The name of the dataset to retrieve.

        Returns:
            Tuple[pl.DataFrame, bool] | Tuple[str, bool]: 
                - If a single parquet file is found, returns a tuple containing the loaded Polars DataFrame and a boolean flag set to False.
                - If multiple parquet files are found, returns a tuple containing the dataset path as a string and a boolean flag set to True.

        Raises:
            SystemExit: If no parquet files are found in the dataset path.
        """
        # dataset_path = self.get_dataset_path(dataset_name)
        parquet_files = autils.find_parquet_files(dataset_path)
        if not parquet_files:
            logging.error(f"No parquet files found in the dataset path {dataset_path}. Please check the configuration file.")
            sys.exit(1)
        if len(parquet_files) > 1:
            logging.warning(f"Multiple parquet files found in the dataset path {dataset_path}.")
            return dataset_path, True
        else:
            dataset = pl.read_parquet(parquet_files)
            return dataset, False

    def union_datasets_add_column(self, dataset_path: str, dataset_name: str) -> pl.DataFrame:
        """
        Unions multiple Parquet datasets from a specified directory, optionally adding a 'year' column 
        based on the filename if the dataset name contains 'Boletines_Oficiales'.

        For each Parquet file in the given directory:
          - If the dataset name contains 'Boletines_Oficiales', extracts the year from the filename and adds it as a new column.
          - Ensures all columns of type Utf8 are explicitly cast to Utf8.
          - Concatenates all datasets into a single Polars DataFrame.

        Args:
            dataset_path (str): Path to the directory containing Parquet files.
            dataset_name (str): Name of the dataset, used to determine if the 'year' column should be added.

        Returns:
            pl.DataFrame: The concatenated DataFrame containing all rows from the input Parquet files, 
                          with the 'year' column added if applicable.

        Raises:
            SystemExit: If the resulting DataFrame is empty after concatenation.
        """
        parquet_files = autils.find_parquet_files(dataset_path)
        logging.info(f"Unioning datasets in {dataset_path} with dataset name {dataset_name}.")
        lazy_frames = []
        if 'Boletin_Oficial' in dataset_name or "EURLEX" in dataset_name:
            for file_path in parquet_files:
                year = os.path.splitext(os.path.basename(file_path))[0]
                lf = pl.scan_parquet(file_path)
                schema = lf.collect_schema()
                # Solo columnas que YA son Utf8
                str_cols = [col for col in schema.keys() if schema[col] == pl.Utf8]
                if str_cols:  # Solo si hay columnas str
                    lf = lf.with_columns(
                        [pl.col(col).cast(pl.Utf8) for col in str_cols]
                    )
                if 'boletin' in schema:
                    lf = lf.with_columns(
                        pl.col('boletin').cast(pl.Utf8)
                    )
                if 'group' in schema:
                    lf = lf.with_columns(
                        pl.col('group').cast(pl.Utf8)
                    )
                lf = lf.with_columns(pl.lit(year).alias("year"))
                lazy_frames.append(lf)

        if 'Licitaciones' in dataset_name:
            for file_path in parquet_files:
                year = file_path.split('/')[-1].split('_')[0]
                lf = pl.scan_parquet(file_path)
                schema = lf.collect_schema()
                # Forzar todas las columnas a string (Utf8)
                lf = lf.with_columns([
                    pl.col(col).cast(pl.Utf8) for col in schema.keys()
                ])
                # Añadir columna year
                lf = lf.with_columns(pl.lit(year).alias("year"))
                lazy_frames.append(lf)

        lazy_df = pl.concat(lazy_frames, how='diagonal')
        full_dataset = lazy_df.collect()
        if full_dataset.is_empty():
            logging.error("The unioned dataset is empty. Please check the parquet files.")
            sys.exit(1)
        return full_dataset

    def _fix_dataset_features(self, dataset: pl.DataFrame) -> pl.DataFrame: # !
        return None

    def process_dataset(self, dataset_name: str):
        """
        Processes a dataset by performing the following steps:
        
        1. Generates YAML resources for the 'interim' stage.
        2. Determines the dataset's path and creates a corresponding 'processed' directory if it does not exist.
        3. If the processed dataset does not exist:
            - Loads the dataset and checks for the presence of a 'tokens' column, exiting if found.
            - If multiple datasets are indicated, unions them and adds a distinguishing column.
            - Renames columns to standardized names ('identificador' to 'id', 'txt' or 'content' to 'text').
            - Identifies and removes duplicate rows based on the 'text' column, saving duplicate IDs to a CSV file.
            - Converts all column names to lowercase and ensures string columns are of type Utf8.
            - Adds a 'tokens' column using the token manager.
            - Saves the processed dataset as a Parquet file.
        4. If the processed dataset exists, loads it from disk.
        5. Counts the total number of tokens in the dataset and logs the result.
        6. Updates or creates a CSV file ('all_info_datasets.csv') with metadata about the dataset, including its name, domain, path, size, RAM usage, and token count.
        7. Generates YAML resources for the 'processed' stage.

        Args:
            dataset_name (str): The name of the dataset to process.

        Raises:
            SystemExit: If a 'tokens' column already exists in the dataset or if required datasets are not found.
        """
        
        self.dg.generate_yaml_resources()
        time.sleep(5)

        path = autils.search_dataset_dir(self.config['root'], dataset_name)
        if not path:
            path = autils.search_dataset_dir(self.config['root'].replace("processed", "interim"), dataset_name)
        if not path:
            raise Exception(f"Dataset {dataset_name} not found in the interim or processed directories.")
        
        if "interim" in path: dataset_path = path
        else: dataset_path = path.replace("processed", "interim")
        save_path = dataset_path.replace("interim", "processed")
                
        if not os.path.exists(save_path):
            logging.info(f"Creating directory {save_path} for processed dataset.")
            os.makedirs(save_path, mode=0o777, exist_ok=True)
            try: os.chmod(save_path, 0o777)  # Cambiar permisos del archivo a 777
            except Exception as e: logging.warning(f"No se han podido cambiar los permisos de '{save_path}': {e}")

        if not os.path.exists(f"{save_path}/dataset.parquet"):
            
            dataset, several = self.get_dataset(dataset_path)
            logging.info(f"Processed dataset not found at {save_path}/dataset.parquet. Proceeding with processing.")

            # A. Un parquet
            if several is False:
                if 'tokens' in dataset.columns:
                    logging.warning("Tokens column already exists in the dataset. Removing it before adding a new one.")
                    sys.exit(1)
            
            # B. Varios parquets
            if several is True:                
                if len(dataset_name) > 1:
                    dataset = self.union_datasets_add_column(dataset_path, dataset_name)
                else:
                    logging.error(f"Dataset {dataset_name} not found in the configuration file or no parquet files found.")
                    sys.exit(1)
            
            # COLUMNA DE IDENTIFICADOR (ID)

            if "identificador" in dataset.columns:
                dataset = dataset.rename({"identificador": "id"})
            if "Identificador" in dataset.columns:
                dataset = dataset.rename({"Identificador": "id"})
            
            # SELECCIÓN DE LA COLUMNA CORRECTA DE TEXTO
            
            text_column = ""

            if "pdf_content" in dataset.columns: # 1. pdf
                text_column = "pdf_content"
            elif "pdf_text" in dataset.columns: # 2. pdf
                text_column = "pdf_text"
            elif "html_content" in dataset.columns: # 3. html
                text_column = "contenido"
            elif "contenido" in dataset.columns: # 4. html
                text_column = "contenido"
            elif "content" in dataset.columns: # 5. html
                text_column = "content"
            elif "text" in dataset.columns: # 6. text
                text_column = "text"
            elif "txt" in dataset.columns: # 7. text
                text_column = "txt"
                    
            logging.info(f"Using '{text_column}' as the 'text' column for processing.")
            
            if text_column != "text" and text_column and "text" in dataset.columns:
                dataset = dataset.drop(["text"]) # 1. eliminar el text
            
            _dataset = dataset.rename({text_column: "text"}) # 2. renombrar
            del dataset
                        
            remove_columns = ["txt", "content", "contenido", "pdf_content", "pdf_text", "html_content"] # 3. eliminar
            remove_columns = list(set(remove_columns) & set(_dataset.columns))
            dataset = _dataset.drop(remove_columns)            
            text_column = "text"
        
            if not text_column: 
                raise Exception("No text column found in the dataset. Please check the dataset structure.")
            
            # PROCESAMIENTO
            try:
                dupes = dataset.group_by(text_column).len().filter(pl.col("len") > 1)
                df_duplicates = (
                    dataset.join(dupes.select(text_column), on=text_column, how="inner")
                        .select("id")
                )
                output_file = f"{save_path}/duplicated_rows.csv"
                df_duplicates.write_csv(output_file)
                try: os.chmod(output_file, 0o777)  # Cambiar permisos del archivo a 777
                except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{output_file}': {e}")
                dataset = dataset.unique(subset=[text_column], keep="first")

                # NORMALIZAR COLUMNAS Y TIPO DE DATOS
                dataset = dataset.rename({col: col.lower() for col in dataset.columns})
                columns = [col for col in dataset.columns if col != "tokens"]
                str_cols = [col for col in columns if dataset.schema[col] == pl.Utf8]
                dataset = dataset.with_columns([pl.col(col).cast(pl.Utf8) for col in str_cols])
                # AÑADIR COLUMNA TOKENS
                dataset = self.token_manager.add_tokens_column_to_dataset(dataset, text_column)

                # ! ARREGLAR LAS FEATURES
                dataset = self._fix_dataset_features(dataset)
                logging.info(f"Dataset size: {dataset.shape[0]} rows and {dataset.shape[1]} columns.")
                
                # GUARDAR DATASET PROCESADO
                dataset.write_parquet(f"{save_path}/dataset.parquet", use_pyarrow=True)
                try: os.chmod(f"{save_path}/dataset.parquet", 0o777)  # Cambiar permisos del archivo a 777
                except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{f"{save_path}/dataset.parquet"}': {e}")
            
            except Exception as e:
                logging.error(f"Error processing the dataset {dataset_name}: {e}", exc_info=True)
                
        else:
            logging.info(f"Processed dataset found at {save_path}/dataset.parquet. Skipping processing.")
            dataset = pl.read_parquet(f"{save_path}/dataset.parquet")

        tokens_dataset = self.token_manager.get_tokens_in_dataset(dataset)
        logging.info(f"Total number of tokens in the dataset: {tokens_dataset}")

        parts = save_path.split(os.sep)
        if 'legal' in parts or 'biomedical' in parts or 'heritage' in parts:
            idx = parts.index('legal') if 'legal' in parts else parts.index('biomedical') if 'biomedical' in parts else parts.index('heritage')
            domain = parts[idx]
            idx += 1
            before = os.sep.join(parts[:idx])

        if not os.path.exists(f"{before}/all_info_datasets.csv"):
            df = pl.DataFrame(
                schema={
                    'dataset': pl.Utf8,
                    'domain': pl.Utf8,
                    'path': pl.Utf8,
                    'size-mb': pl.Utf8,
                    'size-ram-mb': pl.Utf8,
                    'tokens': pl.Utf8,
                    'date': pl.Utf8
                }
            )
        else:
            df = pl.read_csv(f"{before}/all_info_datasets.csv", schema={
                'dataset': pl.Utf8,
                'domain': pl.Utf8,
                'path': pl.Utf8,
                'size-mb': pl.Utf8,
                'size-ram-mb': pl.Utf8,
                'tokens': pl.Utf8,
                'date': pl.Utf8
            })

        if dataset_name in df['dataset'].to_list():
            logging.warning(f"Dataset {dataset_name} already exists in the all_info_datasets.csv file. Updating")
            df = df.filter(pl.col("dataset") != dataset_name)

        dataset_size = autils.get_folder_size_mb(save_path)
        dataset_ram_size = dataset.estimated_size("mb")
        entry = {
            "dataset": [dataset_name],
            "domain": [domain],
            "path": [os.path.join("/".join(dataset_path.split('/')[10:]), 'metadata.json')],
            "size-mb": [f"{dataset_size.__round__(2)}"],
            "size-ram-mb": [f"{dataset_ram_size.__round__(2)}"],
            "tokens": [f"{tokens_dataset}"],
            "date": [f"{datetime.datetime.now().strftime("%d-%m-%Y")}"]
        }
        df.vstack(pl.DataFrame(entry), in_place=True)
        df = df.sort("tokens")
        df.write_csv(f"{before}/all_info_datasets.csv")
        try: os.chmod(f"{before}/all_info_datasets.csv", 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{f"{before}/all_info_datasets.csv"}': {e}")
        logging.info(f"Dataset {dataset_name} added to the all_info_datasets.csv file.")
        
        del df
        del dataset
        self.dg.generate_yaml_resources()

