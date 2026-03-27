"""Script de creación del dataset Wikipedia_Cultura_España
"""

import csv
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime

import json_repair
import polars as pl
import requests
from openai import OpenAI
from requests import Response

from typing import Any, Dict


class LLMApi:
    def __init__(self,
                 api_key: str = os.getenv("<API_KEY>"),
                 model: str = "<MODEL_NAME>"):
        """
        Inicializa la clase LLMApi con los parámetros necesarios para acceder al modelo remoto.

        :param api_key: Clave de acceso a la API (por defecto se toma de las variables de entorno).
        :param model: Ruta o identificador del modelo a usar.
        """

        self.url = "http://<URL_SERVER>/v1/chat/completions"
        if not api_key:
            raise ValueError("API Key is required. Set it using the 'api_key' argument or as an environment variable.")
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key
        }
        self.client = OpenAI(
            api_key=self.api_key,  
            base_url="http://<URL_SERVER>/v1" 
        )
        self.embedding_dim = self._get_embedding_dimension()

    def send_request(self,
                     chat: list = None,
                     response_format: Dict = None,
                     max_tokens: int = 256,
                     temperature: float = 0.2) -> Response:
        """
        Envía una solicitud POST al servidor para generar una respuesta del modelo.

        :param chat: Historial de mensajes de la conversación.
        :param response_format: Formato de respuesta esperado (JSON Schema, por ejemplo).
        :param max_tokens: Número máximo de tokens en la respuesta generada.
        :param temperature: Nivel de aleatoriedad en la generación de texto.
        :return: Objeto de respuesta HTTP.
        """
        payload = {
            "model": self.model,
            "messages": chat or [],
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        if response_format:
            payload["response_format"] = response_format

        response = requests.post(self.url, headers=self.headers, json=payload)
        response.raise_for_status()  # Lanza excepción si la respuesta es un error
        return response

    def invoke(self,
               chat: list = None,
               response_format: Dict = None,
               max_tokens: int = 256,
               temperature: float = 0.2) -> Any:
        """
        Método de invocación que devuelve directamente el contenido textual de la respuesta del modelo.

        :param chat: Historial de conversación.
        :param response_format: Formato de respuesta en JSON Schema, si se requiere.
        :param max_tokens: Límite de tokens en la respuesta.
        :param temperature: Temperatura para controlar la aleatoriedad de la salida.
        :return: Contenido textual de la respuesta del modelo.
        """
        response = self.send_request(chat=chat,
                                     response_format=response_format,
                                     max_tokens=max_tokens,
                                     temperature=temperature)
        return json_repair.loads(response.content.decode("utf-8"))['choices'][0]['message']['content']


class WikiCrawler:
    def __init__(self, folders: list[str], root_category: str) -> None:
        """Genera la instancia del scraper creando las carpetas necesarias, configurando un logger y
        declarando las variables compartidas principales.

        Args:
            folders: Lista de nombres de carpetas a crear recursivamente en el disco.
            root_category: Categoría raíz de Wikipedia desde la cual explorar.
        """
        self.dataset_folder = os.path.join(*folders)
        os.makedirs(self.dataset_folder, exist_ok=True)

        self.csv_path = os.path.join(self.dataset_folder, "output.csv")
        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")
        self.logger = self.setup_logger()
        self.root_category = root_category

        # Archivos de trabajo
        self.jsonl_filename = os.path.join(self.dataset_folder, f"{folders[-1]}.jsonl")
        self.rejected_filename = os.path.join(self.dataset_folder, f"{folders[-1]}_rejected.jsonl")
        self.pending_filename = os.path.join(self.dataset_folder, f"{folders[-1]}_pending.jsonl")

        self.headers = {"User-Agent": "WikipediaCategoryTree/1.0 (contacto@tudominio.com)"}

        # Configuración LLM
        self.llm_api = LLMApi(
            api_key="<API_KEY>",
            model="<MODEL_NAME>"
        )

        self.custom_response_format = {
            "type": "json_schema",
            "json_schema": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "cultural": {
                            "type": "boolean",
                            "description": "True si la categoría pertenece al dominio de Patrimonio Cultural de España, False en cualquier otro caso."
                        }
                    },
                    "required": ["cultural"],
                    "additionalProperties": False
                },
                "name": "customized_output",
                "description": "Clasificación de categorías de Wikipedia en el ámbito de Patrimonio Cultural de España",
                "strict": True,
            }
        }

        self.prompt_template = """
        Eres un clasificador experto en patrimonio cultural. Tu tarea es decidir si una subcategoría de Wikipedia pertenece al ámbito de **{category}**.

        **Incluye (acepta):**
        * Monumentos, edificios históricos, y sitios arqueológicos.
        * Artes escénicas (música, danza, teatro, ópera, flamenco).
        * Cine, fotografía y otras artes visuales.
        * Obras literarias y autores relevantes.
        * Pintura, escultura y otras expresiones artísticas.
        * Historia, tradiciones y patrimonio inmaterial de España.
        * Museos, archivos, bibliotecas y patrimonio documental.
        * Parques y paisajes naturales.
        * Religión.

        **Excluye (rechaza):**
        * Deporte y competiciones deportivas.
        * Ciencia y tecnología sin relación cultural.
        * Política y defensa.
        * Categorías no vinculadas a España.
        * Categorías generales que no se relacionen directamente con el patrimonio cultural.

        Responde únicamente con **True** o **False** según corresponda.
        """

        # DataFrame para artículos
        self.articles_df = pl.DataFrame(schema={
            "title": pl.Utf8,
            "text": pl.Utf8,
            "categories": pl.List(pl.Utf8)
        })

        # Palabras clave para filtrado manual
        self.accept_keywords = [
            "Nacidos en", "Fallecidos en"
        ]
        
        self.reject_keywords = [
            "deporte", "fútbol", "baloncesto", "deportivo", "deportista",
            "científico", "tecnología", "política", "militar", "geografía",
            "economía", "empresa"
        ]

    def append_article(self, title: str, content: str, category: str) -> None:
        """Agrega un artículo nuevo al DataFrame.
        
        Args:
            title: Título del artículo.
            content: Contenido del artículo.
            category: Categoría a la que pertenece.
        """
        self.logger.info(f"📄 Importando artículo: {title} | Categoría: {category}")
        new_row = pl.DataFrame([{
            "title": title,
            "text": content,
            "categories": [category]
        }])
        self.articles_df = pl.concat([self.articles_df, new_row], how="vertical")

    @staticmethod
    def append_to_jsonl(data: dict, filename: str) -> None:
        """Añade un nuevo registro a archivos JSONL.

        Args:
            data: Diccionario de datos a almacenar.
            filename: Nombre del archivo sobre el que se guardarán los datos.        
        """
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            f.flush()

    def append_record(self, record_data: dict) -> bool:
        """Añade una nueva fila al fichero CSV si el ID no existe ya.
        
        Args:
            record_data: Diccionario con el registro a añadir.
            
        Returns:
            bool: True si se añadió el registro, False si ya existía.
        """
        try:
            # Verificar si el ID ya existe
            if 'id' not in record_data:
                self.logger.warning("[CSV] El registro no contiene campo 'id'. Se añadirá sin verificación.")
            else:
                existing_ids = self.get_existing_ids()
                if record_data['id'] in existing_ids:
                    self.logger.info(f"[CSV] Registro con ID {record_data['id']} ya existe. Omitiendo...")
                    return False
            
            # Añadir el registro
            file_exists = os.path.exists(self.csv_path)
            with open(self.csv_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=record_data.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(record_data)
            
            self.logger.info(f"[CSV] Registro con ID {record_data['id']} guardado.")
            return True
            
        except IOError as e:
            self.logger.error(f"[CSV] No se pudo escribir en el CSV {self.csv_path}: {e}")
            return False
        
    def classify_category(self, subcategory: str) -> bool:
        """Clasifica la subcategoría actual según el prompt a un LLM que determina si pertenece a la categoría principal.
        
        Args:
            subcategory: Subcategoría a clasificar

        Returns:
            True si pertenece a la categoría principal, False en cualquier otro caso.
        """
        try:
            prompt = self.prompt_template.format(category=self.root_category)
            custom_chat = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": subcategory}
            ]
            response = json_repair.loads(
                self.llm_api.invoke(chat=custom_chat, response_format=self.custom_response_format)
            )
            return response.get("cultural", False)
        except Exception as e:
            self.logger.warning(f"⚠️ Error al clasificar '{subcategory}': {e}")
            return True  # Asumir relevante si hay error

    def execute(self) -> None:
        """Ejecuta el proceso de crawling completo.
        """
        self.logger.info(f"🚀 Iniciando exploración desde '{self.root_category}'...")

        start_time = datetime.now()
        
        # Fase 1: Explorar categorías
        self.explore_categories()

        # Fase 2: Procesar y refinar categorías
        self.process_categories()

        # Fase 3: Copia de seguridad
        self.save_articles()

        # Fase 4: Post-procesamiento
        self.postprocess()

        end_time = datetime.now()
        duration = end_time - start_time

        self.logger.info(f"\n✅ Proceso completado en {duration}")

    def explore_categories(self) -> None:
        """Explora las categorías de Wikipedia a partir de una inicial, almacenando todas las subcategorías válidas visitadas.
        """
        visited, pending = self.load_state()
        queue = deque(pending)

        self.logger.info(f"📊 Estado inicial: {len(visited)} visitadas, {len(queue)} pendientes")

        while queue:
            item = queue.popleft()
            category = item["name"]
            parent = item.get("parent")
            depth = item.get("depth", 0)

            if category in visited:
                continue

            self.logger.info(f"{'  ' * depth}🔍 Explorando: {category}")

            # Clasificar (salvo raíz)
            if parent is not None:
                if not self.classify_category(category):
                    self.logger.info(f"{'  ' * depth}❌ Rechazado: {category}")
                    self.append_to_jsonl({
                        "name": category,
                        "parent": parent,
                        "depth": depth,
                        "timestamp": datetime.now().isoformat(),
                        "reason": "No pertenece al dominio cultural"
                    }, self.rejected_filename)
                    visited.add(category)
                    self.remove_from_pending(category)
                    continue

            # Guardar como aceptado
            self.append_to_jsonl({
                "name": category,
                "parent": parent,
                "depth": depth,
                "timestamp": datetime.now().isoformat()
            }, self.jsonl_filename)
            self.logger.info(f"{'  ' * depth}✅ {category} [Guardado]")
            visited.add(category)
            self.remove_from_pending(category)

            # Buscar subcategorías y artículos
            try:
                url = "https://es.wikipedia.org/w/api.php"
                params = {
                    "action": "query",
                    "format": "json",
                    "list": "categorymembers",
                    "cmtitle": f"Categoría:{category}",
                    "cmlimit": "max"
                }
                r = requests.get(url, params=params, headers=self.headers, timeout=10)
                r.raise_for_status()
                members = r.json().get("query", {}).get("categorymembers", [])
                
                for member in members:
                    title = member["title"]
                    ns = member["ns"]

                    if ns == 0:  # Artículo
                        if title in self.articles_df["title"].to_list():
                            self.update_article(title, category)
                        else:
                            article = self.fetch_article(title)
                            if article:
                                self.append_article(article["title"], article["text"], category)
                    
                    elif ns == 14:  # Subcategoría
                        sc = title.replace("Categoría:", "")
                        if sc not in visited:
                            child = {"name": sc, "parent": category, "depth": depth + 1}
                            queue.append(child)
                            self.save_pending_item(child)
                
                time.sleep(0.1)  # Rate limiting
                
            except requests.RequestException as e:
                self.logger.warning(f"{'  ' * depth}⚠️ Error en '{category}': {e}")
                time.sleep(2)
                queue.append(item)  # Reintentar

        self.logger.info(f"✅ Exploración completada: {len(visited)} categorías procesadas")

    def fetch_article(self, title: str, retries: int = 3) -> dict:
        """Descarga el contenido plano de un artículo desde Wikipedia.

        Args:
            title: Título del artículo en Wikipedia
            retries: Máximo número de intentos, por defecto 3.

        Returns:
            Diccionario con título y contenido del artículo, None en otro caso.
        """
        url = "https://es.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": True,
            "titles": title
        }
        
        for attempt in range(retries):
            try:
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                response.raise_for_status()
                data = response.json()
                pages = data.get('query', {}).get('pages', {})
                
                for page_id, page_content in pages.items():
                    if "extract" in page_content and page_content["extract"].strip():
                        self.logger.info(f"📥 Artículo descargado: {page_content['title']}")
                        return {
                            "title": page_content["title"],
                            "text": page_content["extract"]
                        }
                    else:
                        self.logger.warning(f"⚠️ El artículo '{title}' no tiene contenido.")
                        return None
                        
            except requests.RequestException as e:
                self.logger.error(f"❌ Error al descargar '{title}' (intento {attempt+1}/{retries}): {e}")
                time.sleep(2)
        
        return None

    def get_existing_ids(self) -> set:
        """Obtiene los IDs que ya existen en el CSV.
        
        Returns:
            Set con los IDs existentes en el CSV.
        """
        existing_ids = set()
        if os.path.exists(self.csv_path):
            try:
                with open(self.csv_path, mode='r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'id' in row and row['id']:
                            existing_ids.add(row['id'])
            except (IOError, csv.Error) as e:
                self.logger.warning(f"[CSV] Error al leer IDs existentes: {e}")
        return existing_ids
    
    def load_state(self) -> tuple[set, list]:
        """Restaura el estado de la exploración de categorías en caso de interrupción o fallo.
        
        Returns:
            Tupla con (categorías visitadas, categorías pendientes).
        """
        visited = set()
        cat_info = {}
        parent_map = {}
        pending = []

        # Leer categorías aceptadas y rechazadas
        for fname in [self.jsonl_filename, self.rejected_filename]:
            if not os.path.exists(fname):
                continue
            with open(fname, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                        name = d.get("name")
                        if not name:
                            continue
                        visited.add(name)
                        cat_info[name] = {"parent": d.get("parent"), "depth": d.get("depth", 0)}
                        if d.get("parent") is not None:
                            parent_map.setdefault(d["parent"], []).append(name)
                    except json.JSONDecodeError:
                        continue

        # Leer categorías pendientes
        if os.path.exists(self.pending_filename):
            with open(self.pending_filename, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                        if item.get("name") and item["name"] not in visited:
                            pending.append(item)
                    except json.JSONDecodeError:
                        continue
            return visited, pending

        # Reconstruir pendientes si no existe archivo
        to_check = list(cat_info.keys())
        if self.root_category not in visited:
            to_check.append(self.root_category)

        url = "https://es.wikipedia.org/w/api.php"

        for name in to_check:
            if name in parent_map:
                continue
            params = {
                "action": "query",
                "format": "json",
                "list": "categorymembers",
                "cmtitle": f"Categoría:{name}",
                "cmlimit": "max"
            }
            try:
                r = requests.get(url, params=params, headers=self.headers, timeout=10)
                r.raise_for_status()
                members = r.json().get("query", {}).get("categorymembers", [])
                subcats = [m for m in members if m.get("ns") == 14]
                parent_depth = cat_info.get(name, {}).get("depth", 0)
                
                for m in subcats:
                    sc = m.get("title", "").replace("Categoría:", "")
                    if sc and sc not in visited:
                        item = {"name": sc, "parent": name, "depth": parent_depth + 1}
                        pending.append(item)
                        self.save_pending_item(item)
                
                time.sleep(0.1)
            except Exception as e:
                self.logger.warning(f"⚠️ Error al reconstruir pendientes para '{name}': {e}")
                time.sleep(1)

        # Si no hay pendientes y la raíz no está visitada, añadirla
        if not pending and self.root_category not in visited:
            item = {"name": self.root_category, "parent": None, "depth": 0}
            pending.append(item)
            self.save_pending_item(item)

        return visited, pending

    def postprocess(self) -> None:
        """Realiza el postprocesado del CSV generado, eliminando duplicados y filas sin texto.
        """
        try:
            if not os.path.exists(self.csv_path):
                self.logger.warning("[POSTPROCESS] No se encontró archivo CSV para postprocesar.")
                return
                
            df = pl.read_csv(self.csv_path, encoding="utf-8")
            initial_rows = df.height

            # Limpiar secciones innecesarias del texto
            df = df.with_columns(
                pl.col("text").map_elements(self.remove_irrelevant_sections, return_dtype=pl.Utf8).alias("text")
            )
            
            # Eliminar filas sin texto
            df = df.filter(pl.col("text").is_not_null() & (pl.col("text") != ""))
            
            # Eliminar duplicados por texto
            df = df.unique(subset=["text"], keep="first")
            
            # Asignar columna ID
            df = df.with_columns(pl.arange(1, df.height + 1).alias("id").cast(pl.Utf8))
            
            # Rellenar nulos
            df = df.fill_null("")

            # Reordenar columnas
            df = df.select(["id", "title", "categories", "text"])

            # Guardar resultados finales
            df.write_parquet(self.parquet_path)
            df.write_csv(self.csv_path.replace("output", "output_final"))
            
            self.logger.info(f"[POSTPROCESS] Registros iniciales: {initial_rows} | Finales: {df.height}")
            self.logger.info(f"[POSTPROCESS] Archivo guardado: {self.parquet_path}")
            
        except Exception as e:
            self.logger.error(f"[POSTPROCESS] Error en el postprocesamiento: {e}")

    def process_categories(self) -> None:
        """Revisa y reclasifica categorías según palabras clave, moviendo entre aceptadas y rechazadas."""
        self.logger.info("🔄 Procesando categorías con palabras clave...")
        
        # Cargar categorías aceptadas
        accepted = []
        if os.path.exists(self.jsonl_filename):
            with open(self.jsonl_filename, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            accepted.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

        # Cargar categorías rechazadas
        rejected = []
        if os.path.exists(self.rejected_filename):
            with open(self.rejected_filename, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            rejected.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

        # Revisar aceptadas que deberían ser rechazadas
        to_reject = []
        for cat in accepted:
            name_lower = cat["name"].lower()
            if any(keyword in name_lower for keyword in self.reject_keywords):
                to_reject.append(cat)
                self.logger.info(f"❌ Moviendo a rechazadas: {cat['name']}")

        # Revisar rechazadas que deberían ser aceptadas
        to_accept = []
        for cat in rejected:
            name_lower = cat["name"].lower()
            if any(keyword in name_lower for keyword in self.accept_keywords):
                to_accept.append(cat)
                self.logger.info(f"✅ Moviendo a aceptadas: {cat['name']}")

        # Actualizar archivos si hay cambios
        if to_reject or to_accept:
            # Reescribir aceptadas
            with open(self.jsonl_filename, "w", encoding="utf-8") as f:
                for cat in accepted:
                    if cat not in to_reject:
                        f.write(json.dumps(cat, ensure_ascii=False) + "\n")
                for cat in to_accept:
                    f.write(json.dumps(cat, ensure_ascii=False) + "\n")

            # Reescribir rechazadas
            with open(self.rejected_filename, "w", encoding="utf-8") as f:
                for cat in rejected:
                    if cat not in to_accept:
                        f.write(json.dumps(cat, ensure_ascii=False) + "\n")
                for cat in to_reject:
                    cat["reason"] = "Contiene palabra clave rechazada"
                    f.write(json.dumps(cat, ensure_ascii=False) + "\n")

            self.logger.info(f"✅ Procesamiento completado: {len(to_accept)} aceptadas, {len(to_reject)} rechazadas")
        else:
            self.logger.info("✅ No se encontraron categorías para reclasificar")

    def remove_from_pending(self, category: str) -> None:
        """Elimina una categoría del archivo de pendientes.
        
        Args:
            category: Nombre de la categoría a eliminar.
        """
        if not os.path.exists(self.pending_filename):
            return
            
        try:
            with open(self.pending_filename, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            with open(self.pending_filename, "w", encoding="utf-8") as f:
                for line in lines:
                    try:
                        item = json.loads(line)
                        if item.get("name") != category:
                            f.write(line)
                    except json.JSONDecodeError:
                        f.write(line)  # Mantener líneas inválidas
        except Exception as e:
            self.logger.warning(f"⚠️ Error al eliminar '{category}' de pendientes: {e}")

    @staticmethod
    def remove_irrelevant_sections(text: str) -> str:
        """Elimina secciones no útiles como referencias o enlaces externos.
        
        Args:
            text: Texto del artículo a limpiar.
        
        Returns:
            Texto limpio sin secciones irrelevantes.
        """
        # Eliminar referencias numéricas tipo [1], [2], etc.
        text = re.sub(r'\[\d+\]', '', text)
        
        # Eliminar secciones completas (solo hasta la siguiente sección ==)
        # El patrón captura desde == Título == hasta justo antes del siguiente ==
        text = re.sub(r'== Véase también ==.*?(?=\n==|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'== Referencias ==.*?(?=\n==|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'== Enlaces externos ==.*?(?=\n==|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'== Bibliografía ==.*?(?=\n==|$)', '', text, flags=re.DOTALL)
        text = re.sub(r'== Notas ==.*?(?=\n==|$)', '', text, flags=re.DOTALL)
        
        return text.strip()

    def save_articles(self) -> None:
        """Guarda todos los artículos recopilados en CSV y Parquet."""
        if self.articles_df.height == 0:
            self.logger.warning("⚠️ No hay artículos para guardar.")
            return

        try:
            # ✅ Convertir listas a JSON string solo para CSV
            def list_to_json(x):
                if isinstance(x, list):
                    return json.dumps(x, ensure_ascii=False)
                elif hasattr(x, "to_list"):  # Puede ser una Series o Expr
                    return json.dumps(x.to_list(), ensure_ascii=False)
                else:
                    return json.dumps([str(x)], ensure_ascii=False)

            df_csv = self.articles_df.with_columns(
                pl.col("categories").map_elements(list_to_json, return_dtype=pl.Utf8)
            )

            # Guardar CSV (legible, sin nested data)
            df_csv.write_csv(self.csv_path)
            self.logger.info(f"✅ Copia de seguridad en CSV: {self.csv_path}")

            self.logger.info(f"📊 Total de artículos: {self.articles_df.height}")

        except Exception as e:
            self.logger.error(f"❌ Error al guardar artículos: {e}")

    def save_pending_item(self, item: dict) -> None:
        """Guarda una categoría pendiente de explorar en caso de que el proceso sea interrumpido.

        Args:
            item: Diccionario asociado a la categoría pendiente.
        """
        with open(self.pending_filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()

    def setup_logger(self) -> logging.Logger:
        """Configura el logger para registrar la ejecución del script.
        
        Returns:
            Logger configurado.
        """
        logger = logging.getLogger(os.path.basename(self.dataset_folder))
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            # Handler de archivo
            log_path = os.path.join(self.dataset_folder, f"{os.path.basename(self.dataset_folder)}.log")
            file_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            
            # Handler de consola
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formato
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger

    def update_article(self, title: str, category: str) -> None:
        """Actualiza las categorías asociadas a un artículo ya incluido.

        Args:
            title: Título del artículo.
            category: Categoría a agregar.
        """
        mask = self.articles_df["title"] == title
        if not mask.any():
            self.logger.warning(f"⚠️ Artículo '{title}' no encontrado para actualizar")
            return

        idx = mask.arg_true()[0]
        current_categories = self.articles_df[idx, "categories"].to_list()[0]

        # 🔧 Conversión defensiva: si es str, intentar parsear como lista JSON
        if isinstance(current_categories, str):
            try:
                current_categories = json.loads(current_categories)
                if not isinstance(current_categories, list):
                    current_categories = [current_categories]
            except json.JSONDecodeError:
                current_categories = [current_categories]

        # Evitar duplicados
        if category not in current_categories:
            current_categories.append(category)

            # 🔄 Actualizar DataFrame correctamente sin listas anidadas
            self.articles_df = self.articles_df.with_columns([
                pl.when(pl.col("title") == title)
                .then(pl.lit(current_categories))
                .otherwise(pl.col("categories"))
                .alias("categories")
            ])

            self.logger.info(f"🔄 Categorías actualizadas para '{title}': {current_categories}")


if __name__ == "__main__":
    # Crear instancia de WikiCrawler
    crawler = WikiCrawler(
        folders=["ALIA", "Wikipedia_Cultura_España"],
        root_category="Cultura de España"
    )

    # Ejecutar proceso de crawling
    crawler.execute()