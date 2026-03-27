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

class InstructionsDownsamplingStep(InstructionsStep):
    
    def __init__(
        self,
        domain: str,
        lang: str = "es",
        force: bool = False,
    ):
        super().__init__(domain, lang, force)
        self.config = self.load_step_config(self.full_config, 'downsampling')
    
    def get_paths(self):
        
        """Centraliza la lógica de generación de rutas para evitar condicionales repetidos."""
        
        paths = self._get_base_paths()
        config = self.paths_config
        
        path_dir_datasets_proccesed = os.path.join(
            paths['path-dir-datasets-instructions'], 
            "processed",
            self.domain,
            self.lang
        )
        paths['path-file-initial-instructions-jsonl'] = os.path.join(
            path_dir_datasets_proccesed,
            config['path-file-initial-instructions'].format(
                domain=self.domain, 
                lang=self.lang,
                format="jsonl"
            )
        )
        
        return paths
    
    # ==================== DOWNSAMPLING GENERAL ====================
    def downsample_by_tokens_general(
        self,
        corpus: pl.DataFrame, 
        target_tokens: int, 
        category_col: str = "category"
    ) -> pl.DataFrame:
        """Tarea 1: Downsampling general por tokens conservando proporciones por categoria."""
        logging.info(f"Downsampling general by TOKENS to {target_tokens:,} total tokens (stratified by {category_col})")
        
        current_tokens = corpus['tokens'].sum()
        if current_tokens <= target_tokens:
            logging.warning(f"Corpus already under target tokens ({current_tokens:,} <= {target_tokens:,}). No downsampling needed.")
            return corpus
        
        # Agrupar por categoria y samplear proporcionalmente
        category_stats = corpus.group_by(category_col).agg([
            pl.sum('tokens').alias('cat_tokens'),
            pl.len().alias('cat_instructions')
        ])
        
        sampled_parts = []
        total_sampled_tokens = 0
        
        for row in category_stats.iter_rows():
            cat, cat_tokens, cat_instructions = row
            proportion = cat_tokens / current_tokens
            target_cat_tokens = int(target_tokens * proportion)
            
            cat_corpus = corpus.filter(pl.col(category_col) == cat)
            if cat_corpus['tokens'].sum() <= target_cat_tokens:
                sampled_parts.append(cat_corpus)
                total_sampled_tokens += cat_corpus['tokens'].sum()
                continue
            
            # Shuffle y cumulative filter para esta categoria
            shuffled = cat_corpus.sample(fraction=1.0, shuffle=True, seed=self.SEED)
            shuffled = shuffled.with_columns(pl.col('tokens').cum_sum().alias('cum_tokens'))
            sampled_cat = shuffled.filter(pl.col('cum_tokens') <= target_cat_tokens).drop('cum_tokens')
            
            sampled_parts.append(sampled_cat)
            total_sampled_tokens += sampled_cat['tokens'].sum()
            logging.info(f"  Category '{cat}': {cat_instructions} instr -> {sampled_cat.shape[0]} instr, "
                    f"{cat_tokens:,} -> {sampled_cat['tokens'].sum():,} tokens (target {target_cat_tokens:,})")
        
        result = pl.concat(sampled_parts)
        logging.info(f"General token downsampling completed: {result.shape[0]:,} instr, {result['tokens'].sum():,} tokens "
                f"(target {target_tokens:,}, diff {(result['tokens'].sum() - target_tokens)/1000:.0f}K)")
        return result

    def downsample_by_instructions_general(
        self, 
        corpus: pl.DataFrame, 
        target_instructions: int, 
        category_col: str = "category"
    ) -> pl.DataFrame:
        """Tarea 2: Downsampling general por instrucciones conservando proporciones por categoria."""
        logging.info(f"Downsampling general by INSTRUCTIONS to {target_instructions:,} total instructions (stratified by {category_col})")
        
        current_instructions = corpus.shape[0]
        if current_instructions <= target_instructions:
            logging.warning(f"Corpus already under target instructions ({current_instructions:,} <= {target_instructions:,}). No downsampling needed.")
            return corpus
        
        # Agrupar por categoria y samplear proporcionalmente
        category_stats = corpus.group_by(category_col).agg([
            pl.len().alias('cat_instructions'),
            pl.sum('tokens').alias('cat_tokens')
        ])
        
        sampled_parts = []
        
        for row in category_stats.iter_rows():
            cat, cat_instructions, cat_tokens = row
            proportion = cat_instructions / current_instructions
            target_cat_instructions = int(target_instructions * proportion)
            
            cat_corpus = corpus.filter(pl.col(category_col) == cat)
            if cat_corpus.shape[0] <= target_cat_instructions:
                sampled_parts.append(cat_corpus)
                continue
            
            # Sample aleatorio estratificado
            sampled_cat = cat_corpus.sample(n=target_cat_instructions, shuffle=True, seed=self.SEED)
            sampled_parts.append(sampled_cat)
            logging.info(f"  Category '{cat}': {cat_instructions} -> {sampled_cat.shape[0]} instr; "
                    f"{cat_tokens:,} -> {sampled_cat['tokens'].sum():,} tokens")
        
        result: pl.DataFrame = pl.concat(sampled_parts)
        logging.info(f"General instruction downsampling completed: {result.shape[0]:,} instr; {result['tokens'].sum():,} tokens (target: {target_instructions:,})")
        return result

    # ==================== DOWNSAMPLING ESPECIFICO ====================
    def downsample_specific_by_tokens(
        self,
        corpus: pl.DataFrame, 
        category_objectives: Dict[str, int], 
        category_col: str = "category"
    ) -> pl.DataFrame:
        """Tarea 3: Downsampling por tokens solo para categorias especificas."""
        logging.info(f"Specific token downsampling for categories: {category_objectives}")
        
        result = corpus.clone()
        
        for category, target_tokens in category_objectives.items():
            cat_corpus = result.filter(pl.col(category_col) == category)
            current_tokens = cat_corpus['tokens'].sum()
            
            if current_tokens <= target_tokens:
                logging.info(f"  Category '{category}': already <= target ({current_tokens:,} <= {target_tokens:,})")
                continue
            
            # Downsample solo esta categoria
            shuffled = cat_corpus.sample(fraction=1.0, shuffle=True, seed=self.SEED)
            shuffled = shuffled.with_columns(pl.col('tokens').cum_sum().alias('cum_tokens'))
            sampled_cat = shuffled.filter(pl.col('cum_tokens') <= target_tokens).drop('cum_tokens')
            
            # Reemplazar en resultado
            other_corpus = result.filter(pl.col(category_col) != category)
            result = pl.concat([other_corpus, sampled_cat])
            
            logging.info(f"  Category '{category}': {cat_corpus.shape[0]} instr, {current_tokens:,} -> "
                    f"{sampled_cat.shape[0]} instr, {sampled_cat['tokens'].sum():,} tokens")
        
        return result

    def downsample_specific_by_instructions(
        self,
        corpus: pl.DataFrame, 
        category_objectives: Dict[str, int], 
        category_col: str = "category"
    ) -> pl.DataFrame:
        """Tarea 4: Downsampling por instrucciones solo para categorias especificas."""
        logging.info(f"Specific instruction downsampling for categories: {category_objectives}")
        logging.info(f"> Available categories: {corpus[category_col].unique().to_list()}")
        
        result = corpus.clone()
        
        for category, target_instructions in category_objectives.items():
            cat_corpus = result.filter(pl.col(category_col) == category)
            
            if cat_corpus.shape[0] <= target_instructions:
                logging.info(f"  Category '{category}': already <= target ({cat_corpus.shape[0]} <= {target_instructions})")
                continue
            
            # Sample aleatorio solo esta categoria
            sampled_cat = cat_corpus.sample(n=target_instructions, shuffle=True, seed=self.SEED)
            
            # Reemplazar
            other_corpus = result.filter(pl.col(category_col) != category)
            result = pl.concat([other_corpus, sampled_cat])
            
            logging.info(f"  Category '{category}': {cat_corpus.shape[0]} -> {sampled_cat.shape[0]} instr, "
                    f"{cat_corpus['tokens'].sum():,} -> {sampled_cat['tokens'].sum():,} tokens")
        
        return result
    
    # ==================== UTILIDADES ====================
    def get_filename_suffix(
        self,
        task: str = "",
        target: int = 0,
        target_mapping: Dict[str, int] = {}
    ) -> str:
        
        """Formatear subset para nombre de archivo desde dict categoria:objetivo."""
        
        suffix = task
        
        if target:
            return f"{suffix}-target_{target}"
        elif target_mapping:
            if len(target_mapping) > 3:
                if len(set(target_mapping.values())) == 1:
                    output = f"categories_n{len(target_mapping)}-target_{list(target_mapping.values())[0]}"
                else:
                    output = f"categories_n{len(target_mapping)}-max_target_{sorted(list(target_mapping.values()), reverse=True)[0]}"
                return output
            parts = []
            for cat, obj in sorted(target_mapping.items()):
                parts.append(f"{cat}_{obj}")
            return suffix + "-" + "_".join(parts)

        return suffix

    def run(self):
                        
        # Tareas de downsampling (segun config)
        tasks = self.config.get('downsampling-tasks', [])
        
        corpus = load_jsonl(self.paths['path-file-initial-instructions-jsonl'])
        
        for task_config in tasks:
            
            task_type = task_config['type']  # 'tokens_general', 'instructions_general', 'tokens_specific', 'instructions_specific'
            target = task_config['target']
            
            logging.info("="*80)
            logging.info(f"Processing task: {task_type} -> target {target}")
            
            # Corpus base para esta tarea
            current_corpus = corpus.clone()
            suffix = ""
            
            if task_type == 'tokens_general':
                result = self.downsample_by_tokens_general(current_corpus, target, self.config['category-column'])
                suffix = self.get_filename_suffix(
                    task = task_type,
                    target = target
                )
                
            elif task_type == 'instructions_general':
                result = self.downsample_by_instructions_general(current_corpus, target, self.config['category-column'])
                suffix = self.get_filename_suffix(
                    task = task_type,
                    target = target
                )
                
            elif task_type == 'tokens_specific':
                if task_config['target']:
                    logging.info(f"Task config for 'tokens_specific' has 'target' field. All categories will be downsampled to this number of tokens. If you want specific targets per category, please remove the 'target' field and specify targets in 'categories'.")
                    target_mapping = {_type: task_config['target'] for _type in current_corpus[self.config['category-column']].unique().to_list()}
                else:
                    target_mapping = {obj['category']: obj['tokens'] for obj in task_config['categories']}
                result = self.downsample_specific_by_tokens(current_corpus, target_mapping, self.config['category-column'])
                suffix = self.get_filename_suffix(
                    task=task_type,
                    target = target,
                    target_mapping=target_mapping
                )
                
            elif task_type == 'instructions_specific':
                if task_config['target']:
                    logging.info(f"Task config for 'instructions_specific' has 'target' field. All categories will be downsampled to this number of instructions. If you want specific targets per category, please remove the 'target' field and specify targets in 'categories'.")
                    target_mapping = {_type: task_config['target'] for _type in current_corpus[self.config['category-column']].unique().to_list()}
                else:
                    target_mapping = {obj['category']: obj['instructions'] for obj in task_config['categories']}
                result = self.downsample_specific_by_instructions(
                    current_corpus, 
                    target_mapping, 
                    self.config['category-column']
                )
                suffix = self.get_filename_suffix(
                    task=task_type,
                    target = target,
                    target_mapping=target_mapping
                )
            
            else:
                logging.error(f"Unknown task type: {task_type}")
                continue
            
            # Nombre de salida
            logging.info(f"Task '{task_type}' completed. Result: {result.shape[0]:,} instr, {result['tokens'].sum():,} tokens. Saving with suffix '{suffix}'")
            output_path_parquet = os.path.join(
                self.paths['path-dir-corpora-instructions'],
                self.paths_config['path-file-downsampling-instructions'].format(
                    domain=self.domain, 
                    lang=self.lang,
                    suffix=suffix,
                    format="parquet"
                )
            )
            output_path_jsonl = os.path.join(
                self.paths['path-dir-corpora-instructions'],
                self.paths_config['path-file-downsampling-instructions'].format(
                    domain=self.domain, 
                    lang=self.lang,
                    suffix=suffix,
                    format="jsonl"
                )
            )
            
            # Formatear a formato conversación
            result = self.format_to_conversations(
                corpus = result, 
                keep_extra_fields = True
            )
            
            # Shuffle final
            result = result.sample(fraction=1.0, shuffle=True, seed=self.SEED)
            
            if not os.path.exists(output_path_parquet) or self.force:
                logging.info(f"Creating parquet file {os.path.basename(output_path_parquet)} in {self.paths['path-dir-corpora-instructions']}")
                write_parquet(result, output_path_parquet)
            if not os.path.exists(output_path_jsonl) or self.force:
                logging.info(f"Creating jsonl file {os.path.basename(output_path_jsonl)} in {self.paths['path-dir-corpora-instructions']}")
                write_jsonl(result, output_path_jsonl)
                        
            # Stats
            try: criteria_names = self.config['criteria-columns'][self.domain][self.lang]
            except: criteria_names = []
            stats = self.compute_stats(
                corpus = result, 
                criteria_columns = criteria_names,
                category_column = self.config['category-column'],
                stats_name=f"Complete Downsample Instruction Corpus ({suffix})"
            )
            path_file_stats = os.path.join(
                self.paths['path-dir-stats-instructions'],
                self.paths_config['path-file-stats-instructions'].format(
                    domain=self.domain,
                    lang=self.lang,
                    step="downsampling",
                    suffix=suffix
                )
            )
            write_csv(stats, path_file_stats)
            
            logging.info(f"Task completed: {result.shape[0]:,} instr, {result['tokens'].sum():,} tokens")
            logging.info("="*80)

            
