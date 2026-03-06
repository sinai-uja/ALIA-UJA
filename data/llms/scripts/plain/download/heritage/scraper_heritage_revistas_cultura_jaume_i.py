"""Recolector de datos OAI-PMH para revistas académicas de la Universitat Jaume I.

Este módulo implementa un método que recolecta metadatos Dublin Core y PDFs
de revistas académicas mediante el protocolo OAI-PMH. Los datos se almacenan
en formato Parquet para su posterior análisis.

Fuentes de datos:
    - Cultura, Lenguaje y Representación (CLR)
    - Diferents
    - Kult-Ur
    - Millars
    - Potestas
    - Tiempos Americanos

Example:
    Para ejecutar el script directamente::

        $ python scraper_heritage_revistas_cultura_jaume_i.py

    Para usar la clase programáticamente::

        collector = DataCollector(
            config_path="config.yaml",
            folders=["ALIA", "Revistas_Cultura_Jaume_I"],
            urls=["https://www.e-revistes.uji.es/index.php/clr/oai"]
        )
        collector.execute()

Note:
    Requiere un archivo config.yaml con las credenciales de acceso al disco
    de red donde se almacenarán los datos.
"""

import asyncio
import logging
import os
import re
import time

import aiofiles
import polars as pl
import unicodedata
import win32net
import yaml


class DataCollector:
    """Recolector de datos OAI-PMH con descarga concurrente de PDFs.

    Esta clase gestiona el proceso completo de recolección de metadatos
    desde repositorios OAI-PMH, incluyendo la descarga de PDFs asociados
    y el almacenamiento en formato Parquet.

    Attributes:
        dataset_folder: Ruta a la carpeta principal del dataset.
        pdf_folder: Ruta a la carpeta donde se almacenan los PDFs.
        parquet_path: Ruta al archivo Parquet con los metadatos.
        logger: Logger configurado para registrar la ejecución.
        urls: Lista de URLs OAI-PMH a procesar.
        existing_ids: Set de IDs ya existentes en el Parquet.
        records_buffer: Buffer temporal de registros antes de guardar.
    """

    def __init__(self, config_path: str, folders: list[str], urls: list[str]) -> None:
        """Inicializa el recolector de datos.

        Crea las carpetas necesarias, monta el disco de red, configura el
        logger y carga los IDs existentes del archivo Parquet.

        Args:
            config_path: Ruta al archivo de configuración YAML con las
                credenciales de acceso (disk_path, user, password).
            folders: Lista de nombres de carpetas a crear recursivamente
                en el disco de red. El último elemento se usa como nombre
                de la subcarpeta para PDFs.
            urls: Lista de URLs OAI-PMH de las revistas a procesar.

        Raises:
            RuntimeError: Si no se puede cargar el archivo de configuración.
            win32net.error: Si falla la conexión al disco de red.
        """
        with open(config_path, 'r') as f:
            try:
                config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                raise RuntimeError(
                    f"No se pudo cargar el archivo de configuración {config_path}: {e}"
                )

        netresource = {
            'remote': config["disk_path"],
            'user': config["user"],
            'password': config["password"],
        }
        win32net.NetUseAdd(None, 2, netresource)

        self.dataset_folder = os.path.join(config["disk_path"], *folders)
        os.makedirs(self.dataset_folder, exist_ok=True)
        self.pdf_folder = os.path.join(self.dataset_folder, folders[-1])
        os.makedirs(self.pdf_folder, exist_ok=True)

        self.parquet_path = os.path.join(self.dataset_folder, "output.parquet")
        self.logger = self.setup_logger()
        self.urls = urls
        self.existing_ids = self.get_existing_ids(self.parquet_path)
        self.records_buffer = []

    def append_record(self, record_data: dict) -> None:
        """Añade un nuevo registro al buffer en memoria.

        El registro se almacena temporalmente hasta que se llame a
        ``save_to_parquet()`` para persistir los datos.

        Args:
            record_data: Diccionario con los campos del registro. Debe
                contener al menos la clave 'id' como identificador único.
        """
        self.records_buffer.append(record_data)
        self.logger.info(f"Registro con ID {record_data['id']} añadido al buffer.")

    def save_to_parquet(self) -> None:
        """Persiste los registros del buffer en el archivo Parquet.

        Si el archivo Parquet ya existe, concatena los nuevos registros
        al DataFrame existente. Después de guardar, limpia el buffer.

        Note:
            Este método es idempotente respecto a los datos: si el buffer
            está vacío, no realiza ninguna operación.
        """
        if not self.records_buffer:
            self.logger.info("No hay registros nuevos para guardar.")
            return

        try:
            new_df = pl.DataFrame(self.records_buffer)

            if os.path.exists(self.parquet_path):
                existing_df = pl.read_parquet(self.parquet_path)
                combined_df = pl.concat([existing_df, new_df])
            else:
                combined_df = new_df

            combined_df.write_parquet(self.parquet_path)
            self.logger.info(
                f"Se guardaron {len(self.records_buffer)} registros en {self.parquet_path}"
            )
            self.records_buffer.clear()

        except Exception as e:
            self.logger.error(
                f"No se pudo escribir en el archivo Parquet {self.parquet_path}: {e}"
            )

    @staticmethod
    def clean_filename(string: str, replacement: str = "_") -> str:
        """Convierte una cadena en un nombre de archivo válido para Windows.

        Normaliza la cadena Unicode a ASCII, elimina caracteres no permitidos
        en nombres de archivo de Windows y limpia duplicados del carácter
        de reemplazo.

        Args:
            string: Cadena de texto a limpiar.
            replacement: Carácter para sustituir caracteres inválidos.
                Por defecto es '_'.

        Returns:
            Cadena de texto válida como nombre de archivo.

        Example:
            >>> DataCollector.clean_filename("oai:repo:article/123")
            'oai_repo_article_123'
        """
        clean_string = unicodedata.normalize('NFKD', string)
        clean_string = clean_string.encode('ascii', 'ignore').decode('ascii')
        clean_string = re.sub(r'[\\/*?:"<>|]', replacement, clean_string)
        clean_string = re.sub(f'{replacement}+', replacement, clean_string)
        clean_string = clean_string.strip(replacement)
        return clean_string

    async def doc_compilation(
        self,
        journal_url: str,
        max_retries: int = 3,
        delay_between_retries: int = 5
    ) -> dict:
        """Recopila metadatos y PDFs de una revista OAI-PMH.

        Conecta al endpoint OAI-PMH especificado, itera sobre todos los
        registros disponibles, descarga los PDFs asociados de forma
        concurrente y almacena los metadatos Dublin Core en el buffer.

        El proceso incluye:
            1. Conexión al servidor OAI-PMH con reintentos automáticos.
            2. Filtrado de registros borrados y ya existentes.
            3. Descarga concurrente de PDFs en lotes de 3.
            4. Extracción de metadatos Dublin Core.

        Args:
            journal_url: URL del endpoint OAI-PMH de la revista.
            max_retries: Número máximo de reintentos para operaciones OAI
                en caso de fallo de conexión. Por defecto 3.
            delay_between_retries: Segundos de espera entre reintentos.
                Por defecto 5.

        Returns:
            Diccionario con los identificadores como claves y las rutas
            de los PDFs descargados como valores.

        Raises:
            NoRecordsMatchError: Si el servidor no tiene registros.
            BadVerbError: Si el servidor rechaza la petición OAI.
        """
        from oaipmh.client import Client
        from oaipmh.metadata import MetadataRegistry, oai_dc_reader
        from oaipmh.error import NoRecordsMatchError, BadVerbError
        
        registry = MetadataRegistry()
        registry.registerReader('oai_dc', oai_dc_reader)
        
        # Configurar timeout más largo para el cliente OAI
        import socket
        original_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(60)  # 60 segundos timeout
        
        try:
            client = Client(journal_url, registry)
            
            self.logger.info(f"[OAI] Iniciando extracción de registros desde {journal_url}")
            
            # Recopilar todos los registros primero con reintentos
            records_to_process = []
            deleted_count = 0
            error_count = 0
            
            for attempt in range(1, max_retries + 1):
                try:
                    self.logger.info(f"[OAI] Intento {attempt}/{max_retries} de listar registros")
                    
                    for record in client.listRecords(metadataPrefix='oai_dc'):
                        try:
                            header, metadata = record[0], record[1]
                            
                            # Saltar registros borrados
                            if header.isDeleted():
                                deleted_count += 1
                                self.logger.debug(f"[OAI] Registro {header.identifier()} está borrado. Omitiendo...")
                                continue
                            
                            identifier = self.clean_filename(header.identifier())
                            
                            # Saltar si ya existe
                            if identifier in self.existing_ids:
                                self.logger.debug(f"[OAI] Registro {identifier} ya existe. Omitiendo...")
                                continue
                            
                            records_to_process.append((identifier, header, metadata))
                            
                        except Exception as e:
                            error_count += 1
                            self.logger.warning(f"[OAI] Error procesando registro individual: {e}")
                            continue
                    
                    # Si llegamos aquí, la operación fue exitosa
                    break
                    
                except NoRecordsMatchError:
                    self.logger.warning(f"[OAI] No hay registros disponibles en {journal_url}")
                    return {}
                    
                except BadVerbError as e:
                    self.logger.error(f"[OAI] El servidor rechazó la petición (BadVerb): {e}")
                    return {}
                    
                except Exception as e:
                    self.logger.warning(f"[OAI] Intento {attempt}/{max_retries} falló: {e}")
                    if attempt < max_retries:
                        self.logger.info(f"[OAI] Esperando {delay_between_retries} segundos antes de reintentar...")
                        await asyncio.sleep(delay_between_retries)
                    else:
                        self.logger.error(f"[OAI] No se pudieron obtener registros tras {max_retries} intentos")
                        return {}
            
            self.logger.info(f"[OAI] {deleted_count} registros borrados omitidos")
            self.logger.info(f"[OAI] {error_count} errores al procesar registros individuales")
            self.logger.info(f"[OAI] {len(records_to_process)} registros nuevos por procesar")
            
            if not records_to_process:
                self.logger.info("[OAI] No hay registros nuevos para procesar")
                return {}
            
            # Descargar PDFs de forma concurrente (lotes de 3 para evitar sobrecarga)
            raw_docs = {}
            batch_size = 3
            
            for i in range(0, len(records_to_process), batch_size):
                batch = records_to_process[i:i + batch_size]
                
                # Crear tareas de descarga
                download_tasks = []
                for identifier, header, metadata in batch:
                    relation = metadata.getField('relation') if metadata else []
                    url = relation[0] if relation else ""
                    if url and '/article/view/' in url:
                        url = url.replace('/view/', '/download/')
                    download_tasks.append(self.download_pdf(identifier, url))
                
                # Ejecutar descargas en paralelo
                filepaths = await asyncio.gather(*download_tasks, return_exceptions=True)
                
                # Procesar resultados
                for (identifier, header, metadata), filepath in zip(batch, filepaths):
                    if isinstance(filepath, Exception):
                        self.logger.error(f"[OAI] Error descargando {identifier}: {filepath}")
                        continue
                    else:
                        raw_docs[identifier] = filepath
                        
                        relation = metadata.getField('relation') if metadata else []
                        url = relation[0] if relation else ""

                        # Extraer y recopilar metadatos (Dublin Core) como un diccionario con listas
                        self.append_record({
                            "id": identifier,
                            "url": url,
                            "title": metadata.getField('title') if metadata else [],
                            "creator": metadata.getField('creator') if metadata else [],
                            "subject": metadata.getField('subject') if metadata else [],
                            "description": metadata.getField('description') if metadata else [],
                            "date": metadata.getField('date') if metadata else [],
                            "identifier_doc": metadata.getField('identifier') if metadata else [],
                            "source": metadata.getField('source') if metadata else [],
                            "language": metadata.getField('language') if metadata else [],
                            "text": ""
                        })
                        self.logger.info(f"[OAI] Registro {identifier} añadido")
                
                # Pequeña pausa entre lotes para no sobrecargar el servidor
                if i + batch_size < len(records_to_process):
                    await asyncio.sleep(2)
            
            return raw_docs
            
        finally:
            # Restaurar timeout original
            socket.setdefaulttimeout(original_timeout)

    async def download_pdf(
        self,
        filename: str,
        url: str,
        max_retries: int = 3
    ) -> str:
        """Descarga un archivo PDF de forma asíncrona.

        Utiliza aiohttp para realizar la descarga con soporte para:
            - Reintentos automáticos con backoff exponencial.
            - Manejo de rate limiting (HTTP 429).
            - Verificación del tipo de contenido.
            - Omisión de archivos ya descargados.

        Args:
            filename: Nombre del archivo destino. Se añade extensión
                .pdf automáticamente si no la tiene.
            url: URL directa al archivo PDF.
            max_retries: Número máximo de reintentos en caso de error.
                Por defecto 3.

        Returns:
            Ruta absoluta al archivo PDF descargado.

        Raises:
            aiohttp.ClientError: Si la descarga falla tras todos los reintentos.
            ValueError: Si la URL no devuelve un archivo PDF válido.
        """
        import aiohttp
        from aiohttp import ClientTimeout
        
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        
        path = os.path.join(self.pdf_folder, filename)
        
        if os.path.exists(path):
            self.logger.info(f"[PDF] Archivo {filename} ya existe. Omitiendo...")
            return path
        
        timeout = ClientTimeout(total=60, connect=30)  # Timeouts más largos
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        for attempt in range(1, max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(url) as response:
                        if response.status == 429:
                            wait_time = 2 ** attempt  # Backoff exponencial
                            self.logger.warning(f"[PDF] 429 Too Many Requests. Esperando {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                        
                        response.raise_for_status()
                        
                        # Verificar que es PDF
                        content_type = response.headers.get('Content-Type', '').lower()
                        content = await response.read()
                        
                        if 'pdf' not in content_type and not content.startswith(b'%PDF'):
                            raise ValueError(f"[PDF] URL no devuelve PDF: {content_type}")
                        
                        # Guardar archivo
                        async with aiofiles.open(path, 'wb') as f:
                            await f.write(content)
                        
                        self.logger.info(f"[PDF] ✓ {filename} descargado ({len(content)} bytes)")
                        return path
                        
            except aiohttp.ClientError as e:
                self.logger.warning(f"[PDF] Intento {attempt}/{max_retries} falló: {e}")
                if attempt == max_retries:
                    self.logger.error(f"[PDF] ✗ No se pudo descargar {filename} tras {max_retries} intentos")
                    raise
                await asyncio.sleep(2)
        
        return path

    def execute(self) -> None:
        """Ejecuta el proceso completo de recolección de datos.

        Itera sobre todas las URLs configuradas, procesando cada revista
        de forma secuencial. Para cada URL:
            1. Ejecuta la recopilación de metadatos y PDFs.
            2. Guarda los datos en el archivo Parquet.
            3. Registra el estado de la operación.

        El proceso es tolerante a fallos: si una URL falla, continúa
        con la siguiente e intenta guardar los datos recopilados.

        Al finalizar, muestra un resumen con:
            - Número de URLs procesadas exitosamente.
            - URLs fallidas con sus errores.
            - Total de registros en el dataset.
        """
        successful_urls = []
        failed_urls = []
        
        for idx, journal_url in enumerate(self.urls, 1):
            try:
                self.logger.info(f"\n{'='*80}")
                self.logger.info(f"[PROCESO] URL {idx}/{len(self.urls)}: {journal_url}")
                self.logger.info(f"{'='*80}\n")
                
                # Ejecutar recopilación
                asyncio.run(self.doc_compilation(journal_url))
                successful_urls.append(journal_url)
                
                # Guardar después de cada URL exitosa (por seguridad)
                self.save_to_parquet()
                
                # Pausa entre URLs para evitar sobrecarga del servidor
                if idx < len(self.urls):
                    self.logger.info("[PROCESO] Esperando 5 segundos antes de la siguiente URL...")
                    time.sleep(5)
                
            except Exception as e:
                self.logger.error(f"[PROCESO] Error crítico procesando {journal_url}: {e}", exc_info=True)
                failed_urls.append((journal_url, str(e)))
                
                # Intentar guardar lo que tengamos hasta ahora
                try:
                    self.save_to_parquet()
                except Exception as save_error:
                    self.logger.error(f"[PROCESO] Error guardando datos tras fallo: {save_error}")
                
                continue
        
        # Resumen final
        self.logger.info(f"\n{'='*80}")
        self.logger.info("[RESUMEN FINAL]")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"URLs procesadas exitosamente: {len(successful_urls)}/{len(self.urls)}")
        self.logger.info(f"URLs fallidas: {len(failed_urls)}/{len(self.urls)}")
        
        if successful_urls:
            self.logger.info("\n✓ URLs exitosas:")
            for url in successful_urls:
                self.logger.info(f"  - {url}")
        
        if failed_urls:
            self.logger.warning("\n✗ URLs fallidas:")
            for url, error in failed_urls:
                self.logger.warning(f"  - {url}")
                self.logger.warning(f"    Error: {error}")
        
        df = pl.read_parquet(self.parquet_path)
        self.logger.info(f"\nTotal de registros recolectados en esta ejecución: {len(df)}")
    
    def get_existing_ids(self, parquet_path: str = None) -> set:
        """Obtiene los IDs de registros ya existentes en el Parquet.

        Carga el archivo Parquet y extrae la columna 'id' para crear
        un conjunto de identificadores. Se usa para evitar duplicados
        durante la recolección.

        Args:
            parquet_path: Ruta al archivo Parquet. Si es None, usa
                ``self.parquet_path``.

        Returns:
            Conjunto (set) con los IDs existentes. Retorna conjunto
            vacío si el archivo no existe o hay error de lectura.
        """
        if parquet_path is None:
            parquet_path = self.parquet_path
            
        existing_ids = set()
        if os.path.exists(parquet_path):
            try:
                df = pl.read_parquet(parquet_path)
                if 'id' in df.columns:
                    existing_ids = set(df['id'].to_list())
                    self.logger.info(f"[Parquet] {len(existing_ids)} IDs existentes cargados")
            except Exception as e:
                self.logger.warning(f"[Parquet] Error al leer IDs existentes del archivo Parquet: {e}")
        return existing_ids

    def setup_logger(self) -> logging.Logger:
        """Configura el sistema de logging para el recolector.

        Crea un logger con dos handlers:
            - FileHandler: Escribe en archivo .log en la carpeta del dataset.
            - StreamHandler: Muestra mensajes en consola.

        El archivo de log usa modo 'append' para preservar logs de
        ejecuciones anteriores.

        Returns:
            Logger configurado con nivel INFO y formato de timestamp.
        """
        logger = logging.getLogger(os.path.basename(self.dataset_folder))
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            file_handler = logging.FileHandler(
                os.path.join(self.dataset_folder, f"{os.path.basename(self.dataset_folder)}.log"), 
                mode='a',  # Modo append para no perder logs anteriores
                encoding='utf-8'
            )
            file_handler.setLevel(logging.INFO)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)
        
        return logger


if __name__ == "__main__":
    # Crear instancia del recolector de datos
    collector = DataCollector(
        config_path="config.yaml",
        folders=["ALIA", "Revistas_Cultura_Jaume_I"],
        urls=[
            "https://www.e-revistes.uji.es/index.php/clr/oai",  # Cultura, Lenguaje y Representación
            "https://www.e-revistes.uji.es/index.php/diferents/oai",  # Diferents
            "https://www.e-revistes.uji.es/index.php/kult-ur/oai",  # Kult-Ur
            "http://www.e-revistes.uji.es/index.php/millars/oai",  # Millars
            "https://www.e-revistes.uji.es/index.php/potestas/oai",  # Potestas
            "https://www.e-revistes.uji.es/index.php/tiemposamerica/oai"  # Tiempos Americanos
        ]
    )

    # Ejecutar proceso de recolección de datos
    collector.execute()