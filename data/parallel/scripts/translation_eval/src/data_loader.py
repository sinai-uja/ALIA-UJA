"""Data loading utilities."""

import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class DataLoader:
    """Handles loading and validation of translation data."""
    
    @staticmethod
    def load_parquet(filepath: str) -> pd.DataFrame:
        """Load data from parquet file."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {filepath}")
        
        logger.info(f"Loading data from {filepath}")
        df = pd.read_parquet(path)
        logger.info(f"Loaded {len(df)} examples")
        
        return df
    
    @staticmethod
    def validate_data(df: pd.DataFrame, column_mapping: Dict[str, str]) -> None:
        """Validate that required columns exist."""
        required_keys = ['source', 'prediction', 'reference']
        
        # DEBUG - Print what we're working with
        logger.info(f"DataFrame columns: {df.columns.tolist()}")
        logger.info(f"Column mapping: {column_mapping}")
        
        # Check that all required keys are in the mapping
        missing_keys = [k for k in required_keys if k not in column_mapping]
        if missing_keys:
            raise ValueError(f"column_mapping missing required keys: {missing_keys}")
        
        # Check that mapped columns exist in dataframe
        missing_columns = [column_mapping[k] for k in required_keys if column_mapping[k] not in df.columns]
        if missing_columns:
            # Show what we were looking for vs what exists
            logger.error(f"Looking for columns: {[column_mapping[k] for k in required_keys]}")
            logger.error(f"Available columns: {df.columns.tolist()}")
            raise ValueError(f"Missing required columns: {missing_columns}")

        # Check for null values
        mapped_columns = [column_mapping[k] for k in required_keys]
        null_counts = df[mapped_columns].isnull().sum()
        if null_counts.any():
            logger.warning(f"Null values found: {null_counts[null_counts > 0].to_dict()}")
    
    @staticmethod
    def prepare_data(data_file: str, column_mapping: dict) -> tuple:
        """Load and prepare data, filtering out rows with null values."""
        
        df = pd.read_parquet(data_file)
        
        # Obtener nombres de columnas
        source_col = column_mapping.get('source')
        prediction_col = column_mapping.get('prediction')
        reference_col = column_mapping.get('reference')
        
        print(f"DataFrame columns: {list(df.columns)}")
        print(f"Column mapping: {column_mapping}")
        
        # Verificar nulos ANTES
        null_counts = df[[source_col, prediction_col, reference_col]].isnull().sum()
        print(f"Null values found: {null_counts.to_dict()}")
        
        # FILTRAR filas con cualquier valor nulo
        initial_count = len(df)
        df = df.dropna(subset=[source_col, prediction_col, reference_col])
        final_count = len(df)
        
        if initial_count != final_count:
            print(f"WARNING: Removed {initial_count - final_count} rows with null values")
            print(f"Remaining: {final_count} rows")
        else:
            print(len(df), "total rows.")
        
        sources = df[source_col].tolist()
        predictions = df[prediction_col].tolist()
        references = df[reference_col].tolist()
        
        return sources, predictions, references