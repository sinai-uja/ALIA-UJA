# imports
import os, sys, json, yaml
sys.path.append(f"{os.path.dirname(os.path.realpath(__file__))}/")
import logging
from pathlib import Path
import polars as pl
from typing import List, Dict
import copy
import rdflib
from rdflib import RDF
from lxml import etree

sys.path.append(os.path.realpath("./"))
from utils.utils_alia import ALIADataUtils as autils
from utils.utils_alia import TokenManager

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class MetadataGenerator():
    
    def __init__(self):
        # logging
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing MetadataGenerator")
        
        self.config = yaml.safe_load(
            open(f"{os.path.dirname(os.path.realpath(__file__))}/config.yaml", "r")
        )
        
        self.token_manager = TokenManager()
        
        # METADATOS
        # plantilla de metadatos
        self.template = yaml.safe_load(open(self.config['metadata']['template-yaml'], "r"))
        # plantillas de 'features' y 'splits'
        self.feature_format = copy.deepcopy(self.template["alia:dataset"]["alia:features"][0])
        # namespaces
        self.namespaces = {
            "dc": "http://purl.org/dc/elements/1.1/",
            "dcterms": "http://purl.org/dc/terms/",
            "alia": "http://sinai.org/ALIA/terms/",
        }
        # plantilla de info
        self.info_template = json.load(open(self.config['metadata']['template-json'], "r"))
    
    def _search_dataset_data(self, ruta_carpeta):
        carpeta = Path(ruta_carpeta)
        return [str(f) for f in carpeta.glob('*.parquet') if f.is_file()]

    def _get_divisors(self, column: pl.Series) -> List[str]:
        """
        Obtiene los divisores de una columna de un DataFrame de Polars,
        ignorando los valores que sean cadenas vacías.
        """
        if column.dtype == pl.String:
            # Filtra las cadenas vacías
            return list(set([v for v in column.to_list() if v != ""]))
        elif column.dtype == pl.Int64 or column.dtype == pl.Float64:
            return list(map(str, sorted(set(column.to_list()))))
        elif column.dtype == pl.List:
            # Extrae los valores únicos de las listas, ignorando cadenas vacías
            return list(set([item for sublist in column.to_list() for item in sublist if item != ""]))
        else:
            return []

    def _extract_instances_and_features(self, path: str, divisors: list, datasheet: pl.DataFrame) -> List[Dict]:
        entries = []
        # Cargar el fichero parquet
        try:
            # Comprobar que no es muy grande para cargar
            df = pl.read_parquet(path)
            feature_names = df.columns
            feature_types = df.dtypes
            instances = df.shape[0]
        except Exception as e:
            self.logger.error(f"Error al leer el fichero {path}: {e}")
            return []
        
        descs = {} # i.e.: {'id': '...', 'titulo': 'Título de la guía médica', 'text': 'Texto del documento', 'seccion_clinica': 'Sección médica a la que pertenece la guía.'}
        for line in datasheet['Dataset Features'][0].split('\n'):
            if line != "": 
                descs[line.split(':')[0].strip()] = line.split(':')[1].strip()
        
        try:
            for i, name in enumerate(feature_names):
                if name and not name == "tokens":
                    if name in divisors: 
                        desc = " - Divisor feature. Possible values: " + ", ".join(list(set(self._get_divisors(df[name]))))
                    else:
                        desc = ""
                    feature_entry = copy.deepcopy(self.feature_format)
                    feature_entry["alia:feature"]["dc:identifier"] = name
                    # _desc = descs.get(name, '')
                    # if _desc: feature_entry["alia:feature"]["dc:description"] = f"{descs.get(name, '')}{desc}".strip()
                    feature_entry["alia:feature"]["dc:description"] = f"{descs.get(name, '')}{desc}".strip()
                    feature_entry["alia:feature"]["dc:type"] = str(feature_types[i])
                    entries.append(copy.deepcopy(feature_entry))
        except Exception as e:
            feature_entry = copy.deepcopy(self.feature_format)
            feature_entry["alia:feature"]["dc:identifier"] = f"Error in {name}",
            feature_entry["alia:feature"]["dc:description"] = str(e),
            feature_entry["alia:feature"]["dc:type"] = ""
            entries.append(copy.deepcopy(feature_entry))
        return entries, instances
   
    # save metadata files
    def _generate_yaml(self, metadata: dict, output_path: str) -> None:
        _formats = metadata['alia:dataset']['dc:format']
        _formats.append('Metadata: YAML')
        metadata['alia:dataset']['dc:format'] = _formats

        # Save metadata.yaml file
        if os.path.exists(output_path):
            os.remove(output_path)
        with open(output_path, 'w', encoding='utf-8') as outfile:
            yaml.dump(metadata, outfile, default_flow_style=False, sort_keys=False)

        # Writing and reading permissions
        try: os.chmod(output_path, 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{output_path}': {e}")

    def _generate_rdf(self, yaml_file: str) -> None:
        with open(yaml_file, "r") as file:
            metadata = yaml.safe_load(file)

        # Update metadata
        _formats = metadata['alia:dataset']['dc:format']
        _formats.append('Metadata: RDF (TTL)')
        metadata['alia:dataset']['dc:format'] = _formats

        # NAMESPACES ============================================================================================
        g = rdflib.Graph()
        ALIA = rdflib.Namespace(self.namespaces['alia'])
        DC = rdflib.Namespace(self.namespaces['dc'])
        DCTERMS = rdflib.Namespace(self.namespaces['dcterms'])

        g.bind("alia", ALIA)
        g.bind("dc", DC)
        g.bind("dcterms", DCTERMS)

        # Get URI of the dataset
        dataset_uri = rdflib.URIRef(metadata['alia:dataset'].get("dc:source", "http://example.org/corpus"))
        g.add((dataset_uri, RDF.type, ALIA.metadata))

        # Namespaces mapping
        namespaces = {
            'dc': DC,
            'dcterms': DCTERMS,
            'alia': ALIA
        }

        # PROPERTIES RDF ============================================================================================
        # Process top-level properties
        for qname in list(metadata['alia:dataset'].keys()):
            if qname in ["alia:processing", "alia:features", "alia:splits"]:
                continue

            if ':' not in qname:
                continue

            prefix, local_key = qname.split(':', 1)
            namespace = namespaces.get(prefix)
            if namespace:
                continue

            prop = namespace[local_key]
            value = metadata['alia:dataset'][qname]

            g.add((dataset_uri, prop, rdflib.Literal(value)))

        # Process - alia:processing
        if "alia:processing" in metadata['alia:dataset']:
            processing = metadata['alia:dataset']["alia:processing"]
            processing_uri = rdflib.BNode()
            g.add((dataset_uri, ALIA.processing, processing_uri))

            filtering = processing.get("alia:filtering", "")
            g.add((processing_uri, ALIA.filtering, rdflib.Literal(filtering)))

            cleaning = processing.get("alia:cleaning", "")
            g.add((processing_uri, ALIA.cleaning, rdflib.Literal(cleaning)))

        # Process - features
        for feature in metadata['alia:dataset'].get("alia:features", []):
            feature_data = feature.get("alia:feature", {})
            feature_uri = rdflib.BNode()
            g.add((dataset_uri, ALIA.features, feature_uri))

            for qname in feature_data:
                prefix, local_key = qname.split(':', 1)
                namespace = namespaces.get(prefix)
                if namespace:
                    prop = namespace[local_key]
                    value = feature_data[qname]
                    g.add((feature_uri, prop, rdflib.Literal(value)))

        # Process - splits
        for split in metadata['alia:dataset'].get("alia:splits", []):
            split_data = split.get("alia:split", {})
            split_uri = rdflib.BNode()
            g.add((dataset_uri, ALIA.splits, split_uri))

            for qname in split_data:
                prefix, local_key = qname.split(':', 1)
                namespace = namespaces.get(prefix)
                if namespace:
                    prop = namespace[local_key]
                    value = split_data[qname]
                    g.add((split_uri, prop, rdflib.Literal(value)))

        # Save metadata.ttl file
        rdf_output = yaml_file.replace(".yaml", ".ttl")
        g.serialize(destination=rdf_output, format="turtle")
        try: os.chmod(rdf_output, 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{rdf_output}': {e}")
        self.logger.info(f"Metadatos RDF guardados en {rdf_output}")

    def _generate_xml(self, yaml_file: str) -> None:

        def dict_to_xml(data, parent):
            for key, value in data.items():
                key_parts = key.split(":")
                if len(key_parts) == 2:
                    prefix, label = key_parts
                    namespace = self.namespaces.get(prefix, "http://sinai.org/ALIA/terms/")
                    tag = f"{{{namespace}}}{label}"

                    if isinstance(value, dict):
                        element = etree.SubElement(parent, tag)
                        dict_to_xml(value, element)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                element = etree.SubElement(parent, tag)
                                dict_to_xml(item, element)
                            else:
                                element = etree.SubElement(parent, tag)
                                element.text = str(item)
                    else:
                        element = etree.SubElement(parent, tag)
                        element.text = str(value)

        try:
            with open(yaml_file, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)

            if "alia:dataset" not in data:
                raise ValueError("El YAML debe contener una clave 'alia:dataset' como raíz.")

            # Actualizar metadatos
            _formats: list = data['alia:dataset']['dc:format']
            _formats.append('Metadata: XML')
            data['alia:dataset']['dc:format'] = _formats
            self._generate_yaml(data, yaml_file)

            metadata_data = data["alia:dataset"]

            root = etree.Element(
                "{http://sinai.org/ALIA/}corpus",
                nsmap={
                    None: "http://sinai.org/ALIA/",
                    "dc": self.namespaces["dc"],
                    "dcterms": self.namespaces["dcterms"],
                    "alia": self.namespaces["alia"],
                }
            )

            dict_to_xml(metadata_data, root)
            tree = etree.ElementTree(root)
            xml_output = yaml_file.replace(".yaml", ".xml")
            tree.write(xml_output, pretty_print=True, xml_declaration=True, encoding="utf-8")
            try: os.chmod(xml_output, 0o777)  # Cambiar permisos del archivo a 777
            except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{xml_output}': {e}")

            self.logger.info(f"Metadatos XML guardados en {xml_output}")
        except Exception as e:
            self.logger.error(f"Error al generar el archivo XML: {e}")

    def __generate_info(self, metadata: dict, output_path: str) -> None:
        # logging
        self.logger.info(F"Generando 'metadata.json' para {metadata['alia:dataset']['dc:identifier']} ...")
        parquet_path: str = output_path.replace("metadata.json", "dataset.parquet")

        template = copy.deepcopy(self.info_template['template'])
        # identifier
        template['id'] = metadata['alia:dataset']['dc:identifier']
        # name, description, domain
        template['name'] = metadata['alia:dataset']['dc:title']
        template['description'] = metadata['alia:dataset']['dc:description']
        template['domain'] = metadata['alia:dataset']['dcterms:subject']
        template['license'] = metadata['alia:dataset']['dcterms:license']
        # features & divisors
        features = []
        divisors = []
        divisors_titles = []
        for feature in metadata['alia:dataset']['alia:features']:
            f = feature['alia:feature']
            features.append(f['dc:identifier'])
            if "Divisor feature" in f['dc:description']: 
                divisors.append(f['dc:identifier'])
                divisors_titles.append(f['dc:description'].split('Possible values: ')[1].split(', '))
        # - features
        template['features'] = features
        # - divisors
        divisions = {}
        for i, div in enumerate(divisors):
            divisor_template_i = copy.deepcopy(self.info_template['divisor'])
            divisor_template_i['titles'] = list(set(divisors_titles[i]))
            for title in list(set(divisors_titles[i])):
                divisor_template_i['subsets'][title] = self.token_manager.get_tokens_in_dataset_subset(
                    _dataset=parquet_path,
                    divisor=div,
                    subset=title
                )
            # divisor_template_i['tokens'] = 0
            divisions[div] = divisor_template_i
        template['divisions'] = divisions
        template['tokens']['token-total'] = metadata['alia:dataset']['alia:tokens']

        _average, _stdev = self.token_manager.get_token_statistics_in_dataset(template)
        template['tokens']['token-average'] = copy.deepcopy(_average)
        template['tokens']['token-stdev'] = copy.deepcopy(_stdev)

        # save json
        json.dump(template, open(output_path, 'w', encoding='utf-8'), indent=4, ensure_ascii=False)
        self.logger.info(f"metadata.json generado correctamente en {output_path}")

        # Writing and reading permissions
        try: os.chmod(output_path, 0o777)  # Cambiar permisos del archivo a 777
        except Exception as e: self.logger.warning(f"No se han podido cambiar los permisos de '{output_path}': {e}")


    def _generate_info(self, id: str) -> None:
         
        # 1. Conseguir la ruta al dataset (directorio): Buscar carpeta(s) con el nombre id en 'data/raw'
        dataset_path: str = autils.search_dataset_dir(self.config['paths']['root'], id)

        # 2. Conseguir el fichero de metadatos generado
        metadata_path: str = os.path.join(dataset_path, "metadata.yaml")
        with open(metadata_path, 'r', encoding='utf-8') as file:
            metadata = yaml.load(file, Loader=yaml.FullLoader)

        output_path: str = os.path.join(dataset_path, "metadata.json")
        if os.path.exists(os.path.join(dataset_path, "info.json")):
            os.remove(os.path.join(dataset_path, "info.json"))
        self.__generate_info(metadata, output_path)

    # main
    def generate_metadata(self, id: str = "None"):

        # logging
        self.logger.info(F"Creando metadatos para {id} ...")

        # 1. Conseguir la ruta al dataset (directorio): Buscar carpeta(s) con el nombre id en 'data/processed'
        dataset_path: str = autils.search_dataset_dir(self.config['paths']['root'], id)
        # 1.1. Conseguir el estado o estados del dataset
        provenance = dataset_path.split(os.sep)[-3]
        # 1.2. Conseguir el dominio principal del dataset
        subject = dataset_path.split(os.sep)[-2]

        # 2. Conseguir los ficheros de datos del dataset
        dataset_data_paths: List[str] = self._search_dataset_data(dataset_path)
        parquet_path: str = os.path.join(dataset_path, "dataset.parquet")

        self.logger.info(f"Ruta del dataset: {dataset_path}")
        self.logger.info(f"> Estado del dataset: {provenance}")
        self.logger.info(f"> Dominio del dataset: {subject}")
        self.logger.info(f"> Número de ficheros de datos: {len(dataset_data_paths)}")

        # 3. Conseguir el pl.DataFrame de las respuestas del formulario
        datasheet_path: str = os.path.join(dataset_path, "datasheet.csv")
        df: pl.DataFrame = pl.read_csv(datasheet_path)

        # ==============================================================================================================

        # 4. Generación del fichero de metadatos
        metadata_path: str = os.path.join(dataset_path, "metadata.yaml")
        metadata = copy.deepcopy(self.template)

        # 4.1. Datos previos
        # dominio
        metadata['alia:dataset']['dcterms:subject'] = subject
        # estado
        metadata['alia:dataset']['dcterms:provenance'] = provenance
        # vresion
        version = None
        metadata['alia:dataset']['dcterms:hasVersion'] = "v1" if not version else f"v{version + 1}"
        # tamaño de fichero
        metadata['alia:dataset']['dcterms:extent'] = os.path.getsize(parquet_path) / (1024*1024)

        # 4.2. Atributos (features)
        divisors = df['Dataset Features: Feature for subdivision'][0].split(', ')
        if divisors == ['no'] or divisors == ['No']: divisors = ['']
        features, instances = self._extract_instances_and_features(parquet_path, divisors, df)
        metadata['alia:dataset']['alia:features'] = features
        metadata['alia:dataset']['alia:instances'] = instances

        # 4.3. Formulario
        # identifier
        metadata['alia:dataset']['dc:identifier'] = df['Dataset ID'][0]
        # name
        metadata['alia:dataset']['dc:title'] = df['Dataset name'][0]
        # description
        metadata['alia:dataset']['dc:description'] = df['Dataset description'][0]
        # external resources
        _external = df['Dataset external resources'][0]
        if _external == "Self-contained": 
            metadata['alia:dataset']['dc:relation'] = self.config['metadata']['external-resources']['Self-contained']
        else:
            metadata['alia:dataset']['dc:relation'] = df['Dataset external resources: Links'][0].split(',')
        # souce
        metadata['alia:dataset']['dc:source'] = df['Original corpus'][0]
        # date
        metadata['alia:dataset']['dc:date'] = df['Date of publication of the original data'][0]
        metadata['alia:dataset']['dcterms:coverage'] = df['Date of publication of the original data: Time period '][0]
        # license, copyright, bibliographic reference
        metadata['alia:dataset']['dcterms:license'] = df['License'][0]
        metadata['alia:dataset']['dc:rights'] = df['Copyright'][0]
        metadata['alia:dataset']['dcterms:bibliographicCitation'] = df['Bibliographic reference'][0]
        # processing
        # - collection
        metadata['alia:dataset']['alia:processing']['alia:downloading'] = df['Download process'][0]
        # - filtering
        metadata['alia:dataset']['alia:processing']['alia:filtering'] = df['Filtering: Description'][0]
        # language
        metadata['alia:dataset']['dc:language'] = df['Language'][0].split(',')
        # granularity level
        metadata['alia:dataset']['alia:level'] = df['Dataset instances: Granularity level'][0]

        # 4.4. Otros
        _df_all_info = pl.read_csv(os.path.join("/".join(parquet_path.split('/')[0:-2]), "all_info_datasets.csv"))
        tokens = _df_all_info.filter(pl.col('dataset') == id).to_dicts()[0]['tokens']
        metadata['alia:dataset']['alia:tokens'] = tokens

        # self.logger.info(json.dumps(metadata['alia:dataset'], indent=4, ensure_ascii=False, default=vars))
        self.logger.info(f"Metadatos extraídos correctamente en {metadata_path}")

        # SAVE PROGRESS ==============================================================================================================
        # Save metadata.yaml, metadata.rdf and metadata.xml files
        self._generate_yaml(metadata=copy.deepcopy(metadata), output_path=metadata_path)
        self._generate_info(id=id)

        return None
