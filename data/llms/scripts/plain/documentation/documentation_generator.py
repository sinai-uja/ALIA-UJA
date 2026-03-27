import os, sys, yaml, json
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import polars as pl
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import ALIADataUtils as autils
from datetime import datetime
import stat

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class DocumentationGenerator():
    
    def __init__(self):
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing DocumentationGenerator")
        
        self.config = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )
    
    # YAML of the resources list
    
    def _get_yaml_datasets(self, path):
        dir = "/".join(path.split('/')[-1:])
        md = {}
        # comprobar si estamos a nivel de dataset o de subdominio
        subdirs = [sd for sd in os.listdir(path) if os.path.isdir(os.path.join(path, sd))]
        if not subdirs:
            # A. Nivel de dataset
            md[dir] = os.path.realpath(path)
        else:
            # B. Nivel de subdominio
            for sub in subdirs:
                if not sub.isdigit() and "pdf" not in sub.lower():
                    md.update(self._get_yaml_datasets(os.path.join(path, sub)))
        return md

    def generate_yaml_resources(self) -> dict:

        """
        Genera un archivo YAML listando los datasets obtenidos mediante self._get_datasets_yaml(),
        organizados por dominios según la configuración en self.config.
        """
        try:
            file = self.config['paths']['list-datasets-yaml']  # Ruta de salida YAML, definida en el config
            ruta = self.config['paths']['root']
        except Exception as e:
            raise Exception(f"Error leyendo configuración: {e}")
        
        # Contenedor principal
        resources = {}
        domains = sorted([os.path.join(ruta, d) for d in os.listdir(ruta) if os.path.isdir(os.path.join(ruta, d))])
            
        for j, dom in enumerate(domains):
            dirs = sorted([os.path.join(dom, d) for d in os.listdir(dom) if os.path.isdir(os.path.join(dom, d))])
            for dir in dirs:
                if os.path.isdir(dir):
                    try:
                        datasets = self._get_yaml_datasets(dir)
                        resources.update(datasets)
                    except Exception as e:
                        self.logger.warning(f"Error procesando {dir}: {e}")
                        continue

        os.remove(file) if os.path.exists(file) else None  # Eliminar archivo existente si existe
        
        # Guardar archivo YAML
        with open(file, "w", encoding="utf-8") as f:
            yaml.dump(resources, f, allow_unicode=True, sort_keys=False)

        try: os.chmod(file, 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos del archivo {file}: {e}")

        return resources
    
    def read_yaml_resources(self, mode: str) -> dict:
        """
        Reads the YAML file containing the resources and returns its content as a dictionary.
        """
        
        file = self.config['paths']['list-datasets-yaml']
        
        if not os.path.exists(file):
            self.logger.error(f"El archivo YAML '{file}' no existe. Generando uno nuevo...")
            yaml.safe_dump({}, open(file, "w"), allow_unicode=True, sort_keys=False)
            return {}

        with open(file, "r", encoding="utf-8") as f:
            resources = yaml.safe_load(f)

        return resources  
    
    # Datasheet report
    
    def _get_external_resources_description(self, choice):
        opts = self.config['dataset-report']['report-external-resources']
        return opts.get(choice, "")
    
    def _get_toc_anchor(self, section):
        """
        Generate a markdown anchor from a section title.
        """
        return section.lower().replace("# ", "").replace(",", "").replace("(", "").replace(")", "").replace(" ", "-").replace("-–-", "--")

    def _load_structure_config(self, dossier_mode: bool = False):
        """
        Returns metadata structure: each entry has section, key, title, and optional description.
        """
        # Translations for question titles and descriptions
        entries: dict = self.config['dataset-report']['datasheet']
        if dossier_mode: entries: dict = self.config['dataset-report']['dossier']

        structure = []
        for key, entry in entries.items():
            if isinstance(entry, str):
                # Section header
                section = entry
                structure.append({"section": section, "is_header": True})
            else:
                title = entry['name']
                desc = entry['desc']
                # Determine section (previous header)
                section = structure[-1]["section"] if structure else ""
                item = {"section": section, "key": key, "title": title}
                if desc:
                    item["description"] = desc
                structure.append(item)
        
        return structure
    
    def generate_report(self, dataset_id: str, lang="en") -> str:

        dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
        try:
            df_row = pl.read_csv(f"{dataset_dir}/datasheet.csv").to_dicts()[0]
        except Exception as e:
            raise Exception(f"Error reading datasheet.csv for dataset '{dataset_id}': {e}")

        structure = self._load_structure_config()
        
        # Header
        name_key = "Dataset name"
        dataset_name = df_row.get(name_key, "Unnamed Dataset")
        author_email = df_row.get("Dirección de correo electrónico", "unknown@example.com")
        author_name = author_email.split("@")[0]
        report_title = f"# {dataset_name} - Dataset Report"
        generation = f"_Generated by {author_name} ({author_email})_" if lang == "en" else f"_Generado por {author_name} ({author_email})_"
        md = [report_title, generation, "---"]

        # Table of Contents
        sections = [item["section"] for item in structure if not item.get("is_header")]
        toc = []
        seen = set()
        for sec in sections:
            if sec not in seen:
                seen.add(sec)
                anchor = self._get_toc_anchor(sec)
                toc.append(f"- [{sec}](#{anchor})")
        md.append(f"## {'Table of Contents' if lang=='en' else 'Tabla de Contenidos'}")
        md.extend(toc)
        md.append("---")

        # Content sections
        for item in structure:
            if item.get("is_header"):
                # Section header
                md.append(f"## {item['section']}")
                continue
            key = item["key"]
            answer = df_row.get(key, "")
            if not isinstance(answer, str):
                answer = str(answer[0])
            answer = answer.strip()
            if not answer or answer == "None" or answer.lower() == "no":
                # Skip questions without answers
                continue
            title = item["title"]
            desc = item.get("description")
            md.append(f"### {title}")
            if desc and desc != "None":
                md.append(f"*{desc}*")
            md.append(answer)
            # External Resources extra description
            if key == "Dataset external resources":
                extra = self._get_external_resources_description(answer)
                if extra:
                    md.append(f"*{extra}*")
            md.append("")

        md.append("---")
        final_md = "\n".join(md)
        
        md_path = os.path.join(dataset_dir, "datasheet_report.md")
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(final_md)
            try: os.chmod(md_path, 0o777)  # Cambiar permisos del archivo a 777
            except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{md_path}': {e}")

        except Exception as e:
            raise Exception(f"Error writing {md_path} for dataset '{dataset_id}': {e}")
        
        try:
            os.chmod(md_path, stat.S_IRWXG + stat.S_IRWXU + stat.S_IROTH + stat.S_IXOTH)
        except Exception as e:
            self.logger.warning(f"No se han podido cambiar los permisos del archivo {md_path}: {e}")

    def generate_dossier(self, dataset_id: str):
        
        self.logger.info(f"Generating dossier entry for dataset '{dataset_id}'")
        
        # Create dataset entry
        dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
        try:
            df_row = pl.read_csv(f"{dataset_dir}/datasheet.csv").to_dicts()[0]
        except Exception as e:
            raise Exception(f"Error reading datasheet.csv for dataset '{dataset_id}': {e}")

        # Select domain
        dossier_domain = self.config['dataset-report']['dossier-domain-map'][df_row['Domain']]

        # Check if the dossier already exists
        dossier_path = self.config['paths']['dossier']
        if os.path.exists(dossier_path):
            with open(dossier_path, "r", encoding="utf-8") as f:
                dossier_text = f.read()
        else:
            dossier = [
                # dossier introduction
                f"# VANDELVIRA-DATA dossier",
                f"*Última actualización: {datetime.now().strftime('%d-%m-%Y')}*\n",
                # dossier table content
                "## Tabla de contenidos",
                "- [Biomédico](#biomédico)",
                "- [Legal y Administrativo](#legal-y-administrativo)",
                "- [Patrimonio](#patrimonio)\n",
                "---\n",
                # info de tokens
                self.config['dataset-report']['dossier-tokens'],
                # dossier sections
                "## Biomédico\n"
                "## Legal y Administrativo\n"
                "## Patrimonio\n"
            ]
            dossier_text = "\n".join(dossier)
        
        # Sustituir sección si ya existe
        if f"### {dataset_id}\n" in dossier_text:
            self.logger.info("El dossier ya existe. Se va a actualizar la entrada correspondiente.")
            dataset_section = dossier_text.split(f"### {dataset_id}\n")[1]
            dataset_section = dataset_section.split("\n## ")[0]
            dataset_section = dataset_section.split("\n### ")[0]
            new_dossier = dossier_text.replace(f"\n### {dataset_id}\n" + dataset_section, "<place-holder>")
        else:
            # Get section
            _dossier = dossier_text.split("\n\n---\n")[2]
            dossier_section = "## " + _dossier.split("\n## ")[dossier_domain[1]]
            new_dossier = dossier_text.replace(dossier_section, dossier_section + "\n<place-holder>")
                        
        # Content entry
        structure = self._load_structure_config(dossier_mode=True)
        md_entry = []
        md_entry.append(f"\n### {dataset_id}\n")
        for item in structure:
            # Load info
            key = item["key"]
            answer = df_row.get(key, "")
            if not isinstance(answer, str):
                answer = str(answer[0])
            answer = answer.strip()
            if not answer or answer == "None" or answer.lower() == "no":
                # Skip questions without answers
                continue
            title = item["title"]
            # Write info
            md_entry.append(f"**{title}**")
            md_entry.append(answer)
            md_entry.append("")
        
        # Additional token information
        try:
            tokens = json.load(open(f"{dataset_dir}/metadata.json", "r"))['tokens']['token-total']
            md_entry.append(f"**Token Information**\n- Number of tokens: {tokens}\n- Millons of tokens: {(tokens / 1_000_000).__round__(4)}\n- Billons of tokens: {(tokens / 1_000_000_000).__round__(4)}")
            md_entry.append("")
        except Exception as e:
            self.logger.warning(f"Error reading metadata.json for dataset '{dataset_id}': {e}")
        
        # Write final dossier
        # _final_md = dossier_section +  "\n".join(md_entry)
        final_md = new_dossier.replace("<place-holder>", "\n".join(md_entry))
        
        # Guardar archivo
        with open(dossier_path, "w", encoding="utf-8") as f:
            f.write(final_md)
        try: 
            os.chmod(dossier_path, 0o777)
        except Exception as e: 
            self.logger.warning(f"No se han podido cambiar los permisos del archivo {dossier_path}")
        

    # Update documentation of dataset
    
    def update_resources_yaml(self, dataset_id: str):
        
        dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
        
        resources = self.read_yaml_resources('processed')
        
        if not dataset_id in resources:
            resources[dataset_id] = dataset_dir
        
        yaml.safe_dump(
            resources, 
            open(self.config['paths']['list-datasets-yaml'], "w"), 
            allow_unicode=True, 
            sort_keys=False
        )

    def update_resources_csv(self, dataset_id: str):
        
        try:
            dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
        except Exception as e:
            raise Exception(f"Dataset directory does't exists for '{dataset_id}'")
        
        info = json.load(open(f"{dataset_dir}/metadata.json", "r"))
        domain = info['domain']
        
        all_info = pl.read_csv(os.path.join(self.config['paths']['root'], domain, 'all_info_datasets.csv'))
        all_info = all_info.filter(pl.col("dataset") == dataset_id).to_dicts()[0]
        datasheet = pl.read_csv(f"{dataset_dir}/datasheet.csv")
        
        df_entry = []
        
        type_map = {
            "Utf8": pl.Utf8,
            "Int64": pl.Int64,
            "Float64": pl.Float64
        }

        df_entry.append({
            "Dataset": dataset_id,
            "Date": datasheet['Marca temporal'][0].split(" ")[0],
            "Domain": domain,
            "Tokens": all_info['tokens'],
            "Size (MB)": all_info['size-mb'],
            "RAM Size (MB)": all_info['size-ram-mb'],
        })
        
        schema_dict = {k: type_map[v] for k, v in self.config['resources']['schema'].items()}
        
        if os.path.exists(self.config['paths']['resources']):
            resources = pl.read_csv(self.config['paths']['resources'])
            resources = resources.filter(pl.col("Dataset") != dataset_id)
            resources = pl.concat([resources, pl.DataFrame(df_entry, schema=schema_dict)])
        else:
            resources = pl.DataFrame(df_entry, schema=schema_dict)
        
        resources.write_csv(self.config['paths']['resources'])
        try: os.chmod(self.config['paths']['resources'], 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{self.config['paths']['resources']}': {e}")
                
    def generate_resources_per_domain_csv(self, dataset_id: str):
        
        try:
            resources = pl.read_csv(self.config['paths']['resources'])
        except Exception as e:
            raise Exception(f"Error reading {self.config['paths']['resources']}: {e}")
        
        # -- resources per domain
        per_domain_path = self.config['paths']['resources-per-domain']
        df_entries = []
        
        # load old dates
        if os.path.exists(per_domain_path):
            old_df_dates = sorted(pl.read_csv(per_domain_path)['Date'].to_list())
            dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
            try:
                domain = pl.read_csv(f"{dataset_dir}/datasheet.csv").to_dicts()[0]['Domain']
            except Exception as e:
                raise Exception(f"Error reading datasheet.csv for dataset '{dataset_id}': {e}")
        else:
            domain = ""
            old_df_dates = None
                                
        # generate from scratch
        type_map = {
            "Utf8": pl.Utf8,
            "Int64": pl.Int64,
            "Float64": pl.Float64
        }
        domains = sorted(os.listdir(self.config['paths']['root']))
        domains.remove('other') if 'other' in domains else None
        for i, d in enumerate(domains):
            resources_domain = resources.filter(pl.col("Domain") == d)
            df_entries.append({                   
                "Domain": d,
                "Date": datetime.now().strftime("%Y-%m-%d") if d == domain and not old_df_dates else old_df_dates[i],
                "N Datasets": resources_domain.shape[0],
                "Tam (MB)": resources_domain['Size (MB)'].sum(),
                "Tam in RAM (MB)": resources_domain['RAM Size (MB)'].sum(),
                "Tokens": resources_domain['Tokens'].sum(),
                "Million Tokens": (resources_domain['Tokens'].sum() / 1_000_000).__round__(4),
                "Billion Tokens": (resources_domain['Tokens'].sum() / 1_000_000_000).__round__(4),
                # "Progress until objective": ((resources_domain['Tokens'].sum() / 1_000_000_000) / self.config['resources-per-domain']['token-objective'] * 100).__round__(2)
            })
            schema_dict = {k: type_map[v] for k, v in self.config['resources-per-domain']['schema'].items()}
            df = pl.DataFrame(df_entries, schema=schema_dict)
        
        try:
            os.remove(per_domain_path)
        except Exception as e:
            self.logger.warning(f"Error removing old '{per_domain_path}': {e}")
        df.write_csv(per_domain_path)
        try: os.chmod(per_domain_path, 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{per_domain_path}': {e}")
        
    # checkers
    
    def check_curation(self, dataset_id: str) -> bool:
        """
        Check if the dataset has been curated by looking for 'parquet' file.
        """
        try:
            dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
            if not dataset_dir: return False
            curated_path = os.path.join(dataset_dir, "dataset.parquet")
            return os.path.exists(curated_path)
        except Exception as e:
            self.logger.error(f"Dataset directory doesn't exists for '{dataset_id}': {e}")
            return False
        
    def check_documentation(self, dataset_id: str) -> bool:
        """
        Check if the dataset has been curated by looking for 'metadata's files.
        """
        try:
            dataset_dir = autils.search_dataset_dir(root=self.config['paths']['root'], id=dataset_id)
            if 'interim' in dataset_dir: return False
        except Exception as e:
            self.logger.error(f"Dataset directory does't exists for '{dataset_id}'")
            return False
        metadata_yaml = os.path.join(dataset_dir, "metadata.yaml")
        metadata_json = os.path.join(dataset_dir, "metadata.json")
        datasheet_report = os.path.join(dataset_dir, "datasheet_report.md")
        return os.path.exists(metadata_yaml), os.path.exists(metadata_json), os.path.exists(datasheet_report)
                
if __name__ == "__main__":
    dg = DocumentationGenerator()
