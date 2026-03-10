"""Recolector histórico del Boletin Oficial de la Provincia de Córdoba (BOCOR) - Archivo.

Este script extrae documentos históricos del BOP Córdoba accediendo al catálogo digital del
Archivo Provincial (`catalogodelarchivo.dipucordoba.es`). Itera sobre el catálogo paginado
por número de página, navega con Selenium a la página de cada boletin, localiza el botón
de descarga PDF y extrae el texto con pdfplumber + EasyOCR. Los datos se guardan en CSV
por año y al finalizar genera un Parquet + ZIP.

Attributes:
    anio_scrappeo (int): Año de referencia.
    script_dir (str): Directorio raíz del script.
    calendario (dict): Formato referencial de días por mes.
    meses (dict): Mapa de nombres de mes en español a número.
"""

import os
from bs4 import BeautifulSoup
import requests
from datasets import Dataset
import csv
from io import BytesIO
from urllib.parse import urljoin
import re
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
import pandas as pd
import pytesseract
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
from requests.exceptions import ChunkedEncodingError
import polars as pl
import pytesseract
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import clize
import zipfile
from PyPDF2 import PdfReader
import random
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import pdfplumber
import easyocr
import numpy as np
import torch
from datetime import datetime
import shutil

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))
pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

calendario = {    #Calendario para poder recorrer todos los dias del año
    1: list(range(1, 32)),
    2: list(range(1, 30)),
    3: list(range(1, 32)),
    4: list(range(1, 31)), 
    5: list(range(1, 32)), 
    6: list(range(1, 31)),  
    7: list(range(1, 32)), 
    8: list(range(1, 32)),  
    9: list(range(1, 31)),  
    10: list(range(1, 32)), 
    11: list(range(1, 31)), 
    12: list(range(1, 32))  
}

meses = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5,
    'junio': 6, 'julio': 7, 'agosto': 8, 'septiembre': 9,
    'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos de línea en cadenas de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Registra una URL fallida en un archivo de log.

    Args:
        archivo_errores (str): Ruta del archivo de log (sin extensión `.txt`).
        url_dia (str): URL a registrar.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Ejecuta una petición GET con reintentos ante caídas HTTP.

    Args:
        url_buscar (str): URL a consultar.
        ruta_errores (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
    """

    i = 0 
    encontrada_respuesta = 0
    respuesta = None
    try:
        respuesta = requests.get(url_buscar ,stream=True)
        if respuesta and respuesta.status_code == 200:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta

        elif respuesta.status_code == 404:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta
        else:
            encontrado = False
            for i in range(10):
                print(f"No se pudo acceder a {url_buscar}: reintentamos")
                time.sleep(i+1)
                respuesta = requests.get(url_buscar, stream=True) 
                if respuesta and respuesta.status_code == 200:
                    print("Se ha aceptado el reintento de conexion")
                    encontrado = True
                    break
            if encontrado == False:
                escribir_url_errores(ruta_errores, url_buscar)
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta
        
    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos.")
        escribir_url_errores(ruta_errores, url_buscar)
        encontrada_respuesta = 0
        respuesta = None
        return respuesta, encontrada_respuesta
        
    except requests.exceptions.RequestException as e:
        print(f"Intento {i+1}: error al acceder a {url_buscar}: {e}")
        escribir_url_errores(ruta_errores, url_buscar)
        encontrada_respuesta = 0
        respuesta = None
        return respuesta, encontrada_respuesta

def guardar_contenido_csv(df, ruta, anio):
    """Anexa el DataFrame al CSV acumulativo anual.

    Args:
        df (pd.DataFrame): DataFrame a guardar.
        ruta (str): Directorio destino.
        anio (int|str): Año para el nombre del archivo CSV.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Documento guardado en csv")

def descargar_pdf(response_pdf, enlacePDF):
    """Guarda un PDF desde un stream HTTP en disco.

    Args:
        response_pdf (requests.models.Response): Respuesta HTTP con el stream del PDF.
        enlacePDF (str): Ruta local de destino.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, descripcion, texto_pdf, a_de, ruta_pdf, fecha_completa):
    """Construye un DataFrame con los metadatos y contenido de un boletin del archivo histórico.

    Args:
        identificador (str): ID único del boletin.
        descripcion (str): Descripción del boletin.
        texto_pdf (str): Texto extraído del PDF.
        a_de (str): URL del PDF original.
        ruta_pdf (str): Ruta local del PDF.
        fecha_completa (str): Fecha de publicación del boletin.

    Returns:
        pd.DataFrame: Fila lista para el CSV.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "publication_date": fecha_completa,
        "summary": descripcion,
        "pdf_content": texto_pdf,
        "text": texto_pdf,
        "url": a_de,
        "read_date": fecha_lectura,
        "route_pdf": ruta_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_and_tables(pdf_path):
    """Extrae texto e identifica tablas desde un PDF usando pdfplumber.

    Args:
        pdf_path (str): Ruta al PDF local.

    Returns:
        tuple[str, bool]: Texto completo (con tablas) y booleano de éxito.
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
                    tabla_texto = "\n".join(["\t".join(row) for row in df_table])
                    contenido.append(f"\n[TABLA {page_num}.{table_num}]\n{tabla_texto}\n")
                    last_y = table.bbox[3]
                    # Liberar variables justo después de usarlas
                    del df_table, tabla_texto, upper_text

                # Texto después de la última tabla
                lower_text = page.within_bbox((0, last_y, page.width, page.height)).extract_text()
                if lower_text:
                    contenido.append(lower_text)
                del lower_text, tables
                gc.collect()
 
        return "\n".join(contenido), True
    except Exception as e:
        print("Error en extraer contenido y tablas")
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
            torch.cuda.empty_cache()
        
        return full_text
    except Exception as e:
        print(f"Error en OCR EasyOCR de {os.path.basename(pdf_path)}: {e}")
        return str(e)

def process_pdf(pdf_file, reader):
    """Procesa un PDF con extracción en cadena: pdfplumber y EasyOCR como fallback.

    Args:
        pdf_file (str): Ruta al PDF local.
        reader (easyocr.Reader): Instancia de EasyOCR para fallback OCR.

    Returns:
        tuple[str, str]: Nombre del archivo (sin extensión) y texto extraído.
    """
    filename = os.path.basename(pdf_file)
    # name_without_ext = os.path.splitext(filename)[0]

    # Primero intentar extracción directa (rápida)
    try:
        text, success = extract_text_and_tables(pdf_file)

        if not success:
            print(f"Texto directo insuficiente en {filename}, intentando OCR...")

            text = extract_text_ocr_easyocr(pdf_file, reader)

            if text == 'EOF marker not found':
                print(f"Error al procesar {filename}: EOF marker not found")
                text = ''
    except:
        with open("error_log.txt", "a") as f:
            print(f"Error al procesar {filename}: {sys.exc_info()[0]}")
            f.write(f"Error en {filename}: {sys.exc_info()[0]} - {datetime.datetime.now()}\n")

    if '.pdf' in filename:
        filename = filename.replace('.pdf', '')
    return filename, text

def crear_carpetas_nuevas(anio):
    """Crea la estructura de directorios por año para el scraping.

    Args:
        anio (int): Año para el que se crean las carpetas.

    Returns:
        tuple[str, str]: Ruta al directorio base del año y ruta al subdirectorio PDF.
    """
    base_anio = os.path.join(script_dir, f"{anio}")
    base_dir_pdfs = os.path.join(base_anio, "PDF")

    carpetas = [base_anio, base_dir_pdfs]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    return base_anio, base_dir_pdfs

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF local.
        min_chars (int, optional): Mínimo de caracteres necesarios. Default 50.

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
        
        # Comprobar si hay suficiente texto
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        print(f"Error en extracción directa de {os.path.basename(pdf_path)}: {e}")
        return "", False

def extract_text_ocr(pdf_path, language='spa', poppler_path=r'C:\poppler-24.08.0\Library\bin'):
    """Extrae texto de un PDF escaneado usando OCR con Tesseract.

    Args:
        pdf_path (str): Ruta al PDF local.
        language (str, optional): Código de idioma para Tesseract. Default `'spa'`.
        poppler_path (str, optional): Ruta al binario de Poppler.

    Returns:
        str: Texto extraído via OCR o cadena vacía en caso de error.
    """
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=poppler_path)
        
        full_text = ""
        # Añadir tqdm para seguimiento de páginas OCR
        for i, page in enumerate(tqdm(pages, desc=f"OCR páginas de {os.path.basename(pdf_path)}", leave=False)):
            text = pytesseract.image_to_string(page, lang=language)
            full_text += text + "\n\n"
        
        return full_text
    except Exception as e:
        print(f"Error en OCR de {os.path.basename(pdf_path)}: {e}")
        return ""

def process_pdf(pdf_file):
    """Procesa un PDF intentando primero extracción directa (PyMuPDF) y usando Tesseract OCR como fallback.

    Args:
        pdf_file (str): Ruta al PDF local.

    Returns:
        str: Texto extraído del PDF.
    """
    filename = os.path.basename(pdf_file)
    name_without_ext = os.path.splitext(filename)[0]
    
    # Primero intentar extracción directa (rápida)
    try:
        text, success = extract_text_direct(pdf_file)
        
        # Si la extracción directa no tuvo éxito, usar OCR
        used_ocr = False
        if not success:
            print(f"Usando OCR para {filename} (extracción directa insuficiente)")
            
            text = extract_text_ocr(pdf_file)
            used_ocr = True
    # else:
    #     print(f"Texto extraído directamente para {filename}")
    except:
        with open("error_log.txt", "a") as f:
            f.write(f"Error en {filename}: {sys.exc_info()[0]}\n")
        
    
    return text

def verificar_carga(driver, selector, busqueda):
    """Espera la presencia de un elemento DOM para validar carga de página.

    Args:
        driver (webdriver.Chrome): Driver activo.
        selector (By.*): Tipo de selector.
        busqueda (str): Valor del selector.

    Returns:
        bool: True si el elemento aparece, False si se agotan los reintentos.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((selector, busqueda)))
            return True
            
        except Exception as e:
            intento += 1
            print(f"Intento {intento}/{intentos_maximos}: Error:{e}. Reintentando...")

            if intento < intentos_maximos:
                print("Recargando la página...")
                driver.refresh()
                time.sleep(2)  

    print("Error: La página no se cargó después de varios intentos.")
    return False

def iniciar_driver():
    """Genera un WebDriver Chrome headless para scraping del archivo histórico de Córdoba.

    Returns:
        webdriver.Chrome: Driver configurado.
    """
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument("--log-level=3") 
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def scrapear_dias_completos():
    """Orquestador del scraping del catálogo histórico del BOP Córdoba.

    Itera por páginas del catálogo digitilizado del Archivo Provincial de Córdoba,
    extrae fechas y enlaces de cada boletin, descarga el PDF con Selenium y extrae el
    texto con pdfplumber + EasyOCR. Guarda los datos en CSV por año y al finalizar
    genera un Parquet + ZIP.
    """

    ruta_continuar = os.path.join(script_dir, "continua_por.txt")
    ruta_archivo_errores = os.path.join(script_dir, "url_errores_antiguos")
    numero_boletin = 0

    num_pag = 42259
    ruta_csv = ""
    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{num_pag}")  #leemos el dia y el mes
            print("Escribimos el mes...")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            linea = f.read()
            num_pag = int(linea.strip())
            print("Leemos el mes...")

    anio = 1983
    fecha_completa = ""
    while anio <= 2025:

        base_enlace = f"https://catalogodelarchivo.dipucordoba.es/ms-opac/search?q=bolet%C3%ADn+OR+oficial+OR+de+OR+la+OR+provincia&start={num_pag}&rows=10&sort=fecha+asc&norm=albala&fq=msstored_sfc_cole&fv=%22COLECCI%C3%93N%20BOLET%C3%8DN%20OFICIAL%20DE%20LA%20PROVINCIA%22&fo=and"
        response, find = intentar_peticion(base_enlace, ruta_archivo_errores)
        num_pag += 10

        if find and find == 1 and response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            numero_boletin += 1
            contenedor = soup.find("div", id="result_container")
            medias = contenedor.find_all("div", class_="media")

            for med in medias:
                try:
                    try:
                        fecha = med.find("div", class_="contenedorFechas")
                        desde = fecha.find("p", class_="textField list-link-item")

                        if desde:
                            texto = desde.get_text(strip=True)  # 'Desde: 02-01-1883'
                            fecha_completa = texto.split("Desde:")[-1].strip()  # '02-01-1883'
                            anio = int(fecha_completa.split("-")[-1])  # '1883'
                            print(fecha_completa)
                        else:
                            print("No se encontró la fecha 'Desde'")
                    except Exception as e:
                        print("Error al obtener la fecha:", e)

                    identificador = f"BOCOR-{fecha_completa}-Boletin-{numero_boletin}"

                    base_dir_pdfs = os.path.join(script_dir, f"{anio}", "pdf")
                    base_dir_csv = os.path.join(script_dir, f"{anio}")

                    carpetas = [base_dir_csv, base_dir_pdfs]

                    for carpeta in carpetas:
                        os.makedirs(carpeta, exist_ok=True)

                    cabece = med.find("h2", class_="media-heading")
                    a = cabece.find("a", class_="list-title")
                    descripcion = a.text.strip()
                    enlace = a['href']
                    enlace = f"https://catalogodelarchivo.dipucordoba.es/{enlace}"
                    enlace = enlace.split(" ")
                    enlace_real = ""
                    enlace_real = enlace[0] + "%20" + enlace[1]
                    print(f"Viajamos a: {enlace_real}")

                    driver = iniciar_driver()
                    driver.get(enlace_real)

                    try:
                        # Espera hasta que aparezca el botón de descarga
                        boton_pdf = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "btn_downloadItem"))
                        )
                        enlace_pdf = boton_pdf.get_attribute("href")
                        print("Descargamos PDF:", enlace_pdf)

                        respon_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                        if encontrado_pdf == 1 and respon_pdf and respon_pdf.status_code == 200:
                            ruta_pdf = f"{base_dir_pdfs}\{identificador}.pdf"
                            descargar_pdf(respon_pdf, ruta_pdf)
                            texto_pdf = process_pdf(ruta_pdf)
                            print("Texto leido y procesado")

                            if texto_pdf:
                                df = crear_df_temporal(identificador, descripcion, texto_pdf, enlace_pdf, ruta_pdf, fecha_completa)
                                guardar_contenido_csv(df, base_dir_csv, anio)
                            time.sleep(1.5)

                    except Exception as e:
                        print("Error en el pdf:", e)
                except:
                    print(f"Excepcion en el boletin...")
                    continue

    parquet_path = f"{base_dir_csv}/{anio}.parquet"
    try:
        if os.path.exists(ruta_csv):
            df = pd.read_csv(ruta_csv, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV convertido a Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error al convertir CSV a Parquet para el año{e}")

    zip_path = os.path.join(script_dir, f"{anio}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
                zipf.write(ruta_csv, os.path.basename(ruta_csv))
            print(f"✅ Archivo ZIP creado: {zip_path}")
    except Exception as e:
        print(f"❌ Error al crear el archivo ZIP para el año {e}")

if __name__ == "__main__":
  scrapear_dias_completos()



