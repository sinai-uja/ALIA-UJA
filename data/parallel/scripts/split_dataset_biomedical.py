import polars as pl
import glob
import os
import logging
from tqdm import tqdm
import threading
import time
import psutil
import random

# Configure logging
log_path = 'logs/split_del_dataset_de_medicina.log'
logging.basicConfig(filename=log_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def log_memory_usage():
    while True:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        logging.info(f"RAM Usage: {mem_info.rss / 1024 / 1024:.2f} MB")
        time.sleep(10)

def transform_text(text):
    """
    Aplica la transformación:
    sentence.replace(".\n", ".\t").replace("\n", " ").replace("\t", "\n")
    """
    return text.replace(".\n", ".\t").replace("\n", " ").replace("\t", "\n")

# Start memory logging thread
mem_thread = threading.Thread(target=log_memory_usage)
mem_thread.daemon = True
mem_thread.start()

# Define paths and dataset identifiers
input_path = 'data/raw/biomedical/'
output_path = 'data/proccessed/biomedical/'
dataset_identifiers = {
    'IBECS': '01',
    'MedlinePlus': '02',
    'Pubmed': '03'
}

# Set random seed for reproducibility
random.seed(42)

# Create output directory if it doesn't exist
os.makedirs(output_path, exist_ok=True)
logging.info(f"Output directory {output_path} created or already exists.")

# Find all parquet files
logging.info(f"Searching for parquet files in {input_path}")
parquet_files = glob.glob(os.path.join(input_path, '**', '*.parquet'), recursive=True)
logging.info(f"Found {len(parquet_files)} parquet files.")

processed_dfs = []
for file in tqdm(parquet_files, desc="Processing files"):
    try:
        logging.info(f"Processing file: {file}")
        df = pl.read_parquet(file)

        # Validate columns
        if 'text_es' not in df.columns or 'text_en' not in df.columns:
            logging.warning(f"Skipping file {file} because it lacks 'text_es' or 'text_en' columns.")
            continue

        # Drop rows with null values
        original_rows = len(df)
        df = df.drop_nulls(subset=['text_es', 'text_en'])
        new_rows = len(df)
        if original_rows > new_rows:
            logging.info(f"Dropped {original_rows - new_rows} rows with null values from {file}")

        # Determine dataset identifier
        dataset_name = None
        for name, identifier in dataset_identifiers.items():
            if name in file:
                dataset_name = name
                dataset_id = identifier
                break
        
        if not dataset_name:
            logging.warning(f"Skipping file {file} as it does not match any known dataset.")
            continue

        # Handle ID column
        if 'id' in df.columns:
            # Modify existing ID
            df = df.with_columns(
                (pl.lit(dataset_id) + pl.col('id').cast(pl.Utf8)).alias('id')
            )
        else:
            # Create new ID
            df = df.with_columns(
                (pl.lit(dataset_id) + pl.arange(0, len(df)).cast(pl.Utf8)).alias('id')
            )
        
        # Generate random mask for 50% of rows
        num_rows = len(df)
        apply_transform = [random.random() < 0.5 for _ in range(num_rows)]
        
        # Apply text transformation with 50% probability to BOTH Spanish and English texts
        logging.info(f"Applying text transformations to {file}")
        df = df.with_columns([
            pl.Series('apply_transform', apply_transform)
        ])
        
        # Apply transformation conditionally to both columns
        df = df.with_columns([
            pl.when(pl.col('apply_transform'))
              .then(pl.col('text_es').map_elements(transform_text, return_dtype=pl.Utf8))
              .otherwise(pl.col('text_es'))
              .alias('text_es'),
            pl.when(pl.col('apply_transform'))
              .then(pl.col('text_en').map_elements(transform_text, return_dtype=pl.Utf8))
              .otherwise(pl.col('text_en'))
              .alias('text_en')
        ])
        
        # Select columns (drop the helper column)
        df = df.select(['id', 'text_es', 'text_en'])
        processed_dfs.append(df)
        logging.info(f"Successfully processed file: {file}")

    except Exception as e:
        logging.error(f"Error processing file {file}: {e}")
        print(f"Error processing file {file}: {e}")

if not processed_dfs:
    logging.error("No dataframes were processed. Exiting.")
    print("No dataframes were processed. Exiting.")
else:
    # Concatenate all dataframes
    full_df = pl.concat(processed_dfs)
    logging.info(f"Total rows in the concatenated dataframe: {len(full_df)}")

    # Shuffle the dataframe
    full_df = full_df.sample(fraction=1.0, shuffle=True, seed=42)

    # Define fixed sizes for validation and test
    val_size = 100
    test_size = 5000
    
    # Check if dataset is large enough
    total_size = len(full_df)
    if total_size < (val_size + test_size):
        logging.error(f"Dataset too small. Total rows: {total_size}, but need at least {val_size + test_size} rows.")
        print(f"Error: Dataset has only {total_size} rows, but need at least {val_size + test_size} rows for validation and test sets.")
    else:
        # Split the data with fixed sizes
        val_df = full_df.slice(0, val_size)
        test_df = full_df.slice(val_size, test_size)
        train_df = full_df.slice(val_size + test_size)

        logging.info("Data split successfully.")

        # Save the splits as parquet files
        logging.info("Saving the splits as parquet files...")
        train_df.write_parquet(os.path.join(output_path, 'train.parquet'))
        val_df.write_parquet(os.path.join(output_path, 'validation.parquet'))
        test_df.write_parquet(os.path.join(output_path, 'test.parquet'))
        logging.info("Parquet files saved successfully.")

        logging.info("Dataset split and saved successfully.")
        logging.info(f"Train set size: {len(train_df)}")
        logging.info(f"Validation set size: {len(val_df)}")
        logging.info(f"Test set size: {len(test_df)}")

        print("Dataset split and saved successfully using polars. Check the log file for details: logs/split_del_dataset_de_medicina.log")