import logging
import os
import polars as pl
import tiktoken
import yaml
import sys
import gc
from tqdm import tqdm
from typing import Union, Dict
import math
import os, sys
sys.path.append(f"{os.path.dirname(os.path.abspath(__file__))}/")
sys.path.append(os.path.abspath("./"))
from utils.utils_alia import TokenManager as UtilsTokenManager

class TokenManager:
    """
    TokenManager is a utility class for managing tokenization and token statistics in text datasets.

    This class provides methods to:
    - Load configuration for tokenization models and directories.
    - Count tokens in text using a specified encoding.
    - Add a column with token counts to a Polars DataFrame.
    - Count total tokens in a dataset or a subset of a dataset.
    - Compute token statistics (average and standard deviation) across dataset divisions.

    Attributes:
        config (dict): Configuration loaded from a YAML file.
        tiktoken_model (str): The name of the tiktoken model to use.
        tiktoken_dir (str): Directory for tiktoken cache.

    Methods:
        add_tokens_column(dataset: pl.DataFrame, text_column: str) -> pl.DataFrame:
            Adds a 'tokens' column to the dataset with the token count for each row.
        count_tokens_in_dataset(_dataset: pl.DataFrame | str) -> int:
            Returns the total number of tokens in the dataset.
        count_tokens_in_subset(_dataset: pl.DataFrame | str, divisor: str = None, subset: str = None) -> int:
            Returns the total number of tokens in a subset of the dataset defined by a divisor and subset value.
    """
    def __init__(self):
        """
        Initialize the TokenExtractor with configuration from YAML file.

        Loads configuration from a YAML file located relative to the current script,
        sets up tiktoken model parameters, and configures the tiktoken cache directory
        through environment variables.

        Attributes:
            config (dict): Configuration dictionary loaded from YAML file
            tiktoken_model (str): The tiktoken model name from configuration
            tiktoken_dir (str): Directory path for tiktoken cache from configuration
        """

        self.config = yaml.safe_load(
            open(os.path.abspath("data/llms/scripts/plain/config.yaml"), "r")
        )
        
        self.tiktoken = UtilsTokenManager()

    def add_tokens_column(self, dataset: pl.DataFrame, text_column: str) -> pl.DataFrame:
        """
        Adds a new column with token counts to the given Polars DataFrame.

        This method processes each row in the input DataFrame, extracts the text from the specified column,
        computes the tokens using the provided encoding, and appends a new 'tokens' column to the DataFrame.
        If the specified text column does not exist but a 'txt' column is present, it will be renamed accordingly.

        Args:
            dataset (pl.DataFrame): The input Polars DataFrame containing the data.
            text_column (str): The name of the column containing text to tokenize.

        Returns:
            pl.DataFrame: A new DataFrame with an additional 'tokens' column containing the token counts.

        Raises:
            ValueError: If the specified text column is not found and there is no 'txt' column to rename.
        """
        data = []
        if text_column not in dataset.columns:
            if 'txt' in dataset.columns:
                dataset = dataset.rename({"txt": text_column})
            else:
                raise ValueError(f"Column {text_column} not found in the dataset and no 'txt' column to rename.")
        total_rows = dataset.height
        for row in tqdm(dataset.iter_rows(named=True), desc="Calculating tokens", total=total_rows):
            id = row["id"]
            if id is None:
                logging.error("Row ID is None. Cannot process this row.")
                continue
            if text_column not in row:
                logging.error(f"Column {text_column} not found in row with ID {id}.")
                continue
            text = row[text_column]
            if text is None or not isinstance(text, str):
                logging.warning(f"Text in row with ID {id} is not a valid string. Got: {repr(text)}")
                tokens = 0
            else:
                tokens = self.tiktoken.get_tokens(text)
            data.append({'id': id, "tokens": tokens})
        new_df = pl.DataFrame(data)
        union_df = dataset.join(new_df, on='id', how="left")
        logging.info(f"Tokens column added to dataset with {len(new_df)} rows.")
        return union_df

