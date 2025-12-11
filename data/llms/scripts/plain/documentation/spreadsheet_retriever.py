import os, sys, yaml
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/") 
import polars as pl
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import ALIADataUtils as autils
import requests

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class SpreadsheetRetriever():
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing SpreadsheetRetriever")
        self.config = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )
        
        # Save the google spreadsheet
        self._get_spreadsheet()

    def _get_spreadsheet(self) -> pl.DataFrame:
        url = self.config['google-spreadsheet']['url'].format(
            id=self.config['google-spreadsheet']['id'],
            sheet=self.config['google-spreadsheet']['sheet'],
            api_key=self.config['google-spreadsheet']['api_key'],
            range=self.config['google-spreadsheet']['range']
        )
        path = self.config['google-spreadsheet']['path']
        try:
            autils.get_spreadsheet(url, path)
            self.spreadsheet = pl.read_csv(path)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error retrieving spreadsheet: {e}")
        
    def _get_datasetrow(self, dataset_id: str):
        dataset_id = dataset_id.encode('utf-8').decode('utf-8')
        row = self.spreadsheet.filter(pl.col("Dataset ID") == dataset_id).select("*").to_dicts()
        if row:
            return row[0]
        empty_row = [""] * len(self.spreadsheet.columns)
        logging.error(f"Dataset ID '{dataset_id}' not found in the spreadsheet. Returning empty row.")
        return empty_row

    def _save_datasetrow(self, path, dataset_id) -> bool:
        columns = self.spreadsheet.columns
        new_entry = self._get_datasetrow(dataset_id)
        try:
            df = pl.DataFrame(new_entry, schema=columns, orient="row")
            df.write_csv(path)
            try: os.chmod(path, 0o777)  # Cambiar permisos del archivo a 777
            except Exception as e: pass
            return True
        except Exception as e:
            raise Exception(f"Error saving spreadsheet for dataset '{dataset_id}': {e}")

    def retrieve_spreadsheet(self, dataset_id) -> bool:
        
        # 1. Actualizar el formulario
        self._get_spreadsheet()
        
        # 2. Guardar la entrada del dataset
        try_path = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
        if 'interim' in try_path:
            new_path = try_path.replace('interim', 'processed')
            os.makedirs(new_path, exist_ok=True)
            try: os.chmod(new_path, 0o777)  # Cambiar permisos del archivo a 777
            except Exception as e: pass
            try_path = new_path
        path = try_path + "/datasheet.csv"
                
        row = self._save_datasetrow(path=path, dataset_id=dataset_id)
        if row: 
            self.logger.info(f"Spreadsheet entry for dataset '{dataset_id}' saved successfully.")
            return True
        
        self.logger.error(f"Failed to save spreadsheet entry for dataset '{dataset_id}'.")
        return False
