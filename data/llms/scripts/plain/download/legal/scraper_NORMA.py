"""Recolector del portal Normadoc (normativa pública española).

Este script automatiza la extracción de documentos normativos del portal `normadoc.gob.es`.
Recorre el listado de organismos del buscador, itera sobre las páginas de resultados de cada
organismo, descarga cada PDF referenciado y extrae el texto usando pdfplumber, PyMuPDF y
EasyOCR como fallbacks en cadena. Los resultados se guardan en un único Parquet.
Requiere acceso a red compartida mediante `win32net`.

Las credenciales de red se cargan desde un archivo `config.yaml` en el mismo directorio
que el script. No deben incluirse credenciales directamente en el código fuente.

Attributes:
    logger: Logger configurado con nivel INFO.
    normadoc_url (str): URL base del portal Normadoc.
    document_url (str): URL de búsqueda por organismo.
    path (str): Directorio raíz de salida.
"""

from bs4 import BeautifulSoup
import requests
import urllib.parse
import fitz
import os
from requests.exceptions import ChunkedEncodingError
import time
import polars as pl
import sys
from requests.compat import urljoin
import pdfplumber
import easyocr
import numpy as np
import logging
import datetime
from PyPDF2 import PdfReader
from tqdm import tqdm
from pdf2image import convert_from_path
import gc
import win32net
import yaml


def load_config(config_path: str = None) -> dict:
    """Carga la configuración desde un archivo YAML.

    Busca el archivo en la ruta indicada o, si no se especifica, en el mismo
    directorio que este script (config.yaml).

    Args:
        config_path (str, optional): Ruta al archivo de configuración.
            Si es None, se usa ``<directorio_del_script>/config.yaml``.

    Returns:
        dict: Diccionario con los valores de configuración.

    Raises:
        FileNotFoundError: Si el archivo no existe en la ruta indicada.
        KeyError: Si faltan claves obligatorias en el YAML.
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"No se encontró el archivo de configuración: {config_path}\n"
            "Crea un config.yaml con la sección 'red_compartida' (remote, user, password)."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Validar claves obligatorias
    required_keys = ("remote", "user", "password")
    missing = [k for k in required_keys if k not in config.get("red_compartida", {})]
    if missing:
        raise KeyError(f"Faltan claves en 'red_compartida' del config.yaml: {missing}")

    return config


# ── Cargar configuración y montar recurso de red ──────────────────────────────
_config = load_config()
_net = _config["red_compartida"]

netresource = {
    "remote": _net["remote"],
    "password": _net["password"],
    "user": _net["user"],
}
win32net.NetUseAdd(None, 2, netresource)
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def extract_text_direct(pdf_path, min_chars=1):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF local.
        min_chars (int, optional): Mínimo de caracteres para éxito. Default 1.

    Returns:
        tuple[str, bool]: Texto extraído y booleano de éxito.
    """
    try:
        direct_text = ""
        gc.collect()
        doc = fitz.open(pdf_path)
        for page in doc:
            direct_text += page.get_text()
        doc.close()
        gc.collect()
        
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        logger.error(f"Error al extraer texto directo de {os.path.basename(pdf_path)}: {e}")
        return f"{e}", False


def extract_text_and_tables(pdf_path):
    """Extrae texto e identificar tablas desde un PDF usando pdfplumber.

    Combina el texto anterior a cada tabla con el contenido de la tabla formateado
    para reconstruir el contexto completo del documento.

    Args:
        pdf_path (str): Ruta al PDF local.

    Returns:
        tuple[str, bool]: Texto completo extraído (con tablas) y booleano de éxito.
    """
    contenido = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.find_tables()
                tables = sorted(tables, key=lambda t: t.bbox[1])
                last_y = 0
                for table_num, table in enumerate(tables, 1):
                    # Texto antes de la tabla
                    upper_text = page.within_bbox((0, last_y, page.width, table.bbox[1])).extract_text()
                    if upper_text:
                        contenido.append(upper_text)
                    # Tabla
                    df_table = table.extract()
                    text_table = "\n".join(["\t".join(row) for row in df_table])
                    contenido.append(f"\n[TABLA {page_num}.{table_num}]\n{text_table}\n")
                    last_y = table.bbox[3]
                    # Liberar variables justo después de usarlas
                    del df_table, text_table, upper_text

                # Texto después de la última tabla
                lower_text = page.within_bbox((0, last_y, page.width, page.height)).extract_text()
                if lower_text:
                    contenido.append(lower_text)
                del lower_text, tables
                gc.collect()
 
        return "\n".join(contenido), True
    except Exception as e:
        logger.error(f"Error al extraer texto y tablas de {os.path.basename(pdf_path)}: {e}")
        return f"{e}", False


def extract_text_ocr_easyocr(pdf_path, reader):
    """Extrae texto de un PDF escaneado usando EasyOCR procesando página a página para optimizar RAM.

    Args:
        pdf_path (str): Ruta al PDF local.
        reader (easyocr.Reader): Instancia de EasyOCR inicializada.

    Returns:
        str: Texto extraído vía OCR o mensaje de error.
    """
    try:
        full_text = ""
        
        # Obtén el número total de páginas del PDF
        pdf_reader = PdfReader(pdf_path)
        num_pages = len(pdf_reader.pages)
        
        for page_number in tqdm(range(1, num_pages + 1), desc=f"OCR páginas de {os.path.basename(pdf_path)}", leave=False):
            # Convierte solo una página a imagen para OCR
            pages = convert_from_path(pdf_path, dpi=300, first_page=page_number, last_page=page_number)
            page_image = np.array(pages[0])
            
            # Extrae texto de la imagen
            result = reader.readtext(page_image, detail=0, paragraph=True)
            text = " ".join(result)
            full_text += text + "\n\n"
            
            # Limpieza para liberar memoria
            del pages, page_image, result, text
            gc.collect()
        
        return full_text
    except Exception as e:
        print(f"Error en OCR EasyOCR de {os.path.basename(pdf_path)}: {e}")
        return str(e)


def process_pdf(pdf_file, reader):
    """Procesa un PDF con extracción en cadena: pdfplumber, PyMuPDF y EasyOCR como último recurso.

    Args:
        pdf_file (str): Ruta al PDF local.
        reader (easyocr.Reader): Instancia de EasyOCR para fallback OCR.

    Returns:
        tuple[str, str]: Nombre del archivo (sin extensión) y texto extraído.
    """
    filename = os.path.basename(pdf_file)
    try:
        text, success = extract_text_and_tables(pdf_file)
        if not success:
            logger.warning(f"Texto directo insuficiente en {filename}, intentando PyMuPDF...")
            text, success = extract_text_direct(pdf_file)
            if not success:
                logger.warning(f"Texto directo insuficiente en {filename}, intentando OCR...")
                text = extract_text_ocr_easyocr(pdf_file, reader)
                if text == 'EOF marker not found':
                    logger.error(f"Error al procesar {filename}: EOF marker not found")
                    text = ''
    except:
        with open("error_log.txt", "a") as f:
            logger.error(f"Error al procesar {filename}: {sys.exc_info()[0]}")
            f.write(f"Error en {filename}: {sys.exc_info()[0]} - {datetime.datetime.now()}\n")

    if '.pdf' in filename:
        filename = filename.replace('.pdf', '')
    return filename, text


def error_log(error_path, search_url):
    """Registra una URL fallida en un archivo de log.

    Args:
        error_path (str): Ruta del archivo de log (sin extensión `.txt`).
        search_url (str): URL que produjo el error.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")


def try_pet(search_url, error_path):
    """Ejecuta una petición GET protegida con reintentos ante caídas HTTP.

    Args:
        search_url (str): URL a consultar.
        error_path (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
    """
    i = 0 
    response_find = 0
    response = None
    try:
        response = requests.get(search_url, stream=True)
        if response and response.status_code == 200:
            response_find = 1
            return response, response_find

        elif response.status_code == 404:
            response_find = 1
            return response, response_find
        else:
            find = False
            for i in range(5):
                print(f"No se pudo acceder a {search_url}: reintentamos")
                time.sleep(i+1)
                response = requests.get(search_url) 
                if response and response.status_code == 200:
                    print("Se ha aceptado el reintento de conexion")
                    find = True
                    break
            if find == False:
                error_log(error_path, search_url)
            response_find = 1
            return response, response_find
        
    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos.")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find
        
    except requests.exceptions.RequestException as e:
        print(f"Intento {i+1}: error al acceder a {search_url}: {e}")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find


def main():
    """Orquestador del scraping de Normadoc.

    Accede al portal Normadoc y obtiene el listado de organismos del select de búsqueda.
    Por cada organismo itera página a página sobre sus resultados, descarga cada PDF
    encontrado, extrae su texto con pdfplumber + PyMuPDF + EasyOCR en cadena y acumula
    los datos en una lista de diccionarios. Al finalizar genera un Parquet único.
    Omite organismos ya procesados (si existe el Parquet de salida).
    """
    # Fetch the web page
    normadoc_url = "https://www.normadoc.gob.es/es-es/"
    document_url = "https://www.normadoc.gob.es/es-es/BusquedaNormativa/ConsultasResultados.aspx?org="
    path = r""
    docs_path = f"{path}/docs"
    error_path = f"{path}/errors"
    response = requests.get(normadoc_url)
    data = response.text
    
    reader = easyocr.Reader(['es', 'en', 'fr', 'de', 'pt'], gpu=False)
    if not os.path.exists(docs_path):
        os.makedirs(docs_path, exist_ok=True)
    if not os.path.exists(error_path):
        os.makedirs(error_path, exist_ok=True)

    # Parse the HTML content
    soup = BeautifulSoup(data, 'html.parser')
    dict_txt = []

    # Extract specific elements
    for link in soup.find_all('select'):
        if '-- Seleccione un organismo --' in link.text:
            for option in link.find_all('option'):
                if option['value'] != '' and option.text != '-- Seleccione un organismo --':
                    finished = False
                    pages = 1
                    print(f"Organismo: {option.text}")
                    org = urllib.parse.quote(option.text)
                    
                    id_txt = 1

                    if os.path.exists(f"{docs_path}/{org}/output.parquet"):
                        finished = True
                        continue

                    while finished == False:
                        print(f"Pagina: {pages}")
                        if pages > 1:
                            new_url = f"{document_url}{option['value']}&pagina={pages}"
                        else:
                            new_url = f"{document_url}{option['value']}"
                        print(new_url)
                        response_page = requests.get(new_url)
                        data_page = response_page.text
                        soup_page = BeautifulSoup(data_page, 'html.parser')

                        last_page_ = soup_page.find("div", class_="last")

                        results_list = soup_page.find("ul", class_="listadoResultados")

                        if results_list and last_page_:
                            results = results_list.find_all("li", class_="resultado")
                            for result in results:
                                link = result.find("a", href=True)
                                if link:
                                    print(link['href'])
                                    title = link.text
                                    summary = result.text.split("\n")[4].split('                        ')[1]
                                    
                                    if link['href'].startswith("http://"):
                                        link['href'] = "https://" + link['href'][len("http://"):]

                                    web_pdf, encontrado = try_pet(link['href'], error_path)

                                    pdf_path = f"{docs_path}/{org}_{link['href'].split('/')[-2]}_{link['href'].split('/')[-1]}"
                                    print(f"Descargando PDF: {pdf_path}")
                                    if 'www.minhafp.gob.es' in link['href'] or '2004_7466' in pdf_path or 'www.meh.age' in link['href']:
                                        continue
                                      # For debugging purposes, remove in production
                                    
                                    doc_id = f"{org}_{link['href'].split('/')[-2]}_{link['href'].split('/')[-1]}"

                                    with open(pdf_path, 'wb') as file:
                                        file.write(web_pdf.content)
                                        
                                    filename, text = process_pdf(pdf_path, reader)

                                    try:
                                        dict_txt.append({
                                            "id": doc_id,
                                            "text": text,
                                            "url": link['href'],
                                            "title": title,
                                            "summary": summary,
                                            "year": link['href'].split('/')[-2],
                                            "org": org
                                        })                   
                                    except Exception as e:
                                        print(f"Error al añadir el texto a la lista: {e}")
                                        continue
                                    id_txt += 1
                            pages += 1

                        else:
                            finished = True
    
    df = pl.DataFrame(dict_txt)
    df.write_parquet(f"{path}/output.parquet")


if __name__ == "__main__":
    main()
