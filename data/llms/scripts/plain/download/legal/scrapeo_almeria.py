"""Recolector de boletines oficiales de la provincia de Almería (BOP Almería).

Este script automatiza la descarga de boletines y decretos del BOP de Almería.
Navega a través de un calendario web, extrae los enlaces a documentos PDF, los
descarga y, opcionalmente, extrae su texto usando PyMuPDF o Tesseract OCR.
Toda la metainformación y el contenido de los documentos se consolida en
archivos CSV y Parquet por año, los cuales luego son comprimidos en un archivo ZIP.

Attributes:
    anio_scrappeo (int): El año inicial o principal configurado para raspar.
    script_dir (str): Directorio donde se está ejecutando el script.
    meses (dict): Diccionario que relaciona nombres de meses en español con su número.
    calendario (dict): Diccionario auxiliar con la cantidad típica de días por mes.
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
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
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
meses = {
    "enero": "01",
    "febrero": "02",
    "marzo": "03",
    "abril": "04",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12"
}
anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))

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

def verificar_carga(driver, selector, busqueda):
    """Espera activamente a que un elemento se cargue en la página web.

    Utiliza Selenium WebDriverWait para verificar la presencia de un elemento
    específico en el DOM. Si falla, recarga la página hasta un máximo de
    5 intentos.

    Args:
        driver (webdriver.Chrome): La instancia del navegador Selenium.
        selector (By): El tipo de selector usado (ej. By.CSS_SELECTOR).
        busqueda (str): El valor del selector a buscar.

    Returns:
        bool: True si el elemento se carga correctamente, False si se agotan
            los intentos sin éxito.
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

def limpiar_texto(texto):
    """Elimina espacios múltiples y saltos de línea de una cadena de texto.

    Args:
        texto (str): El string original a limpiar.

    Returns:
        str: El texto limpio con espacios simples.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto directamente usando PyMuPDF"""
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

def escribir_url_errores(archivo_errores, url_dia):
    """Añade una URL problemática a un archivo de registro de errores.

    Args:
        archivo_errores (str): Nombre base del archivo de errores (sin '.txt').
        url_dia (str): La URL que ha causado el error de conexión.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Realiza una petición HTTP GET con manejo de errores y reintentos.

    Intenta conectar a una URL dada con un User-Agent predeterminado.
    Si falla, reintenta hasta 5 veces aumentando el tiempo de espera.
    Anota la URL en el registro de errores si todos los intentos fracasan.

    Args:
        url_buscar (str): La URL a la que se desea acceder.
        ruta_errores (str): Ruta base del archivo de control de errores.

    Returns:
        tuple[requests.models.Response|None, int]: Una tupla con el objeto de 
            respuesta HTTP (o None si hubo error) y un entero (1=éxito, 0=fracaso).
    """

    headers = {
        "Referer": url_buscar,
        "User-Agent": "Mozilla/5.0"
    }
    i = 0 
    encontrada_respuesta = 0
    respuesta = None
    try:
        respuesta = requests.get(url_buscar, headers=headers, stream=True)
        if respuesta and respuesta.status_code == 200:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta

        elif respuesta.status_code == 404:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta
        else:
            encontrado = False
            for i in range(5):
                print(f"No se pudo acceder a {url_buscar}: reintentamos")
                time.sleep(i+1)
                respuesta = requests.get(url_buscar) 
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
    """Añade los datos de un DataFrame a un archivo CSV estructurado por año.

    Args:
        df (pd.DataFrame): DataFrame con la información del decreto procesado.
        ruta (str): Directorio destino donde guardar el archivo.
        anio (int|str): Año correspondiente, que define el nombre del archivo.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga de forma segura el contenido binario de un PDF.

    Escribe la respuesta HTTP en disco en bloques de 8KB (chunks) para 
    evitar problemas de memoria con PDFs grandes.

    Args:
        response_pdf (requests.models.Response): Respuesta HTTP del documento.
        enlacePDF (str): Ruta completa de destino donde alojar el archivo.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha, numero_boletin, texto_decreto, url_pdf, ruta_guardar_pdf):
    """Estructura los datos extraídos en un formato DataFrame unificado.

    Genera una fila de pandas con identificador, fecha de publicación,
    número de boletín, texto asociado (OCR o directo) y rutas/URLs.
    Aplica una limpieza de texto a cada campo para uniformizar formato.

    Args:
        identificador (str): ID único compuesto construido para el decreto.
        fecha (str): Fecha de publicación del decreto en formato dia-mes-anio.
        numero_boletin (int|str): El número oficial del boletín.
        texto_decreto (str): El texto extraído o resumido del documento PDF.
        url_pdf (str): URL de donde procede la descarga.
        ruta_guardar_pdf (str): El path local del PDF en crudo descargado.

    Returns:
        pd.DataFrame: Un dataframe limpio listo para guardar.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "publication_date": fecha,
        "bullein_number": numero_boletin,
        "text": texto_decreto,
        "url": url_pdf,
        "read_date": fecha_lectura,
        "route_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto directamente usando PyMuPDF"""
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
    """Extrae texto usando OCR con Tesseract"""
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
    """Procesa un PDF usando extracción directa y OCR si es necesario"""
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

import os
import time

def esperar_y_renombrar_pdf(nombre_deseado, ruta_pdf, timeout=15):
    """Espera la descarga asíncrona de un PDF desde el navegador y lo renombra.

    Muy útil al usar Selenium para descargas automáticas sin control sobre el
    nombre exacto generado. Supervisa el directorio hasta detectar la 
    culminación de la generación del archivo (no es un .crdownload temporal).

    Args:
        nombre_deseado (str): Nuevo nombre para el documento ya descargado.
        ruta_pdf (str): Directorio donde Chrome guarda temporalmente el archivo.
        timeout (int): Tiempo de espera máximo en segundos. Por defecto 15.

    Returns:
        str: La ruta completa del archivo final renombrado.

    Raises:
        TimeoutError: Si el archivo no aparece finalizado antes del timeout.
    """
    inicio = time.time()
    while time.time() - inicio < timeout:
        archivos = os.listdir(ruta_pdf)
        archivos_pdf = [f for f in archivos if f.endswith(".pdf") and not f.endswith(".crdownload")]
        
        if archivos_pdf:
            ruta_original = os.path.join(ruta_pdf, archivos_pdf[0])
            ruta_destino = os.path.join(ruta_pdf, nombre_deseado)
            os.rename(ruta_original, ruta_destino)
            print(f"✅ PDF renombrado a: {nombre_deseado}")
            return ruta_destino
        
        time.sleep(0.5)

    raise TimeoutError("❌ No se descargó ningún PDF dentro del tiempo límite.")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def iniciar_driver(ruta_descarga=None, headless=True):
    """Genera una instancia de Selenium Chrome lista para scrapers.

    Permite delegar un directorio de descarga directo por defecto mediante
    la inyección en experimentales y activa el modo 'headless' (oculto).

    Args:
        ruta_descarga (str, optional): Ruta absoluta a la carpeta de descargas del navegador.
        headless (bool, optional): Indica si el navegador va o no a tener UI gráfica.
            Por defecto es True.

    Returns:
        webdriver.Chrome: El controlador del navegador Chrome parametrizado.
    """
    chrome_options = Options()

    # Configuración de preferencias de descarga
    if ruta_descarga:
        prefs = {
            "download.default_directory": ruta_descarga,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
            "plugins.always_open_pdf_externally": True  # Evita abrir PDFs en el visor
        }
        chrome_options.add_experimental_option("prefs", prefs)

    # Opciones para modo headless
    if headless:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument("--log-level=3") 
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu') # necesario para descargas headless

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    # Habilitar descargas en modo headless (mediante comando DevTools)
    if headless and ruta_descarga:
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": ruta_descarga
        })

    return driver


def scrapear_dias_completos():
    """Flujo central: Controla el bucle de scrapeo continuo del boletín.

    Extrae en lote decretos correspondientes al BOP de Almería. Se apoya
    en un sistema de control por número de boletín secuencial, rastreando su estado en un
    fichero 'continuar.txt'. Emplea Beautiful Soup para explorar el catálogo 
    y descarga uno por uno todos los PDFs asociados.
    Finalmente, consolida los CSV generados por año a un formato optimizado (Parquet)
    y crea un archivo comprimido ZIP final combinando CSV y Parquet resultante.
    """

    numero_boletin = 36665
    dia = 0
    mes = 0
    anio = 0
    ruta_csv_actual = ""
    ruta_continuar = os.path.join(script_dir, "continuar.txt")
    ruta_archivo_errores = os.path.join(script_dir, "url_errores")

    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{numero_boletin}")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            numero_boletin = map(int, f.read().strip())

    print(f"EMPEZAMOS POR EL BOLEIN --> {numero_boletin}")

    while int(numero_boletin) <= 47835:
        try: 
            base_enlace = f"https://app.dipalme.org/pandora/results.vm?view=boletines&s={numero_boletin}&t=%2Bcreation"
            print(f"📅 Visitando: {base_enlace}")

            respuesta, encontrado = intentar_peticion(base_enlace, ruta_archivo_errores)
            if encontrado == 1 and respuesta and respuesta.status_code == 200:
                soup = BeautifulSoup(respuesta.text, 'html.parser')
                lista = soup.find("div", class_="list")
                frames = lista.find_all("div", class_="list-frame")
                contador_decretos = 0
                print("Dentro de la pagina: Pasamos a los decretos")

                for decreto in frames:
                    contador_decretos += 1
                    print(f"Decreto numero: {contador_decretos}")
                    record = decreto.find("div", class_="list-record")
                    p_element = record.find("p", class_="list-record-name")
                    if not p_element:
                        continue

                    texto = p_element.get_text(strip=True)
                    match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', texto)
                    if match:
                        dia, mes, anio = match.groups()
                        dia = dia.zfill(2)
                        mes = mes.zfill(2)
                        print(f"Día: {dia}, Mes: {mes}, Año: {anio}")
                    else:
                        print("❌ No se encontró la fecha.")

                    base_anio = os.path.join(script_dir, f"{anio}")
                    base_dir_pdfs = os.path.join(base_anio, "PDF")
                    base_dir_csv = base_anio

                    for carpeta in [base_anio, base_dir_pdfs, base_dir_csv]:
                        os.makedirs(carpeta, exist_ok=True)

                    enlace_descarga = decreto.find("a", string="Descargar")
                    if not enlace_descarga:
                        continue

                    url_relativa = enlace_descarga['href']
                    url_base = "https://app.dipalme.org/pandora/"
                    url_pdf = url_base + url_relativa

                    # Ruta y nombre del archivo PDF
                    identificador = f"BOP-Almeria-{dia}-{mes}-{anio}-Pag-{numero_boletin}-Dec-{contador_decretos}"
                    ruta_guardar_pdf = f"{base_dir_pdfs}\{identificador}.pdf"
                    texto_decreto = ""
                    # Descargar el PDF directamente
                    try:
                        response = requests.get(url_pdf)
                        response.raise_for_status()  # lanza error si no es 200

                        descargar_pdf(response, ruta_guardar_pdf)
                        texto_decreto = process_pdf(ruta_guardar_pdf)

                    except Exception as e:
                        print(f"❌ Error al descargar el PDF: {e}")

                    df = crear_df_temporal(identificador, f"{dia}-{mes}-{anio}", numero_boletin, texto_decreto, url_pdf, ruta_guardar_pdf)
                    guardar_contenido_csv(df, base_dir_csv, anio)
                print("Pasamos página...")
                numero_boletin += 15
        except ChunkedEncodingError as e:
            print(f"❌ ChunkedEncodingError: {e}")
            continue
        except requests.exceptions.RequestException:
            print(f"❌ Error de conexión.")
            continue
        except Exception as e:
            print(f"❌ Error inesperado el día {dia}: {e}")
            continue

        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{numero_boletin}")

    # Convertir CSV a Parquet
    parquet_path = f"{base_dir_csv}/{anio}.parquet"
    try:
        if os.path.exists(ruta_csv_actual):
            df = pd.read_csv(ruta_csv_actual, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV convertido a Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error al convertir CSV a Parquet: {e}")

    # Crear ZIP del año
    zip_path = os.path.join(script_dir, f"{anio}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
                zipf.write(ruta_csv_actual, os.path.basename(ruta_csv_actual))
            print(f"✅ ZIP creado: {zip_path}")
    except Exception as e:
        print(f"❌ Error al crear ZIP: {e}")

if __name__ == "__main__":
    scrapear_dias_completos()