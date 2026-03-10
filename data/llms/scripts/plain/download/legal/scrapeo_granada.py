"""Recolector del Boletín Oficial de la Provincia de Granada (BOP Granada).

Este script automatiza la extracción y descarga de boletines del BOP de Granada.
Usa Selenium Headless para navegar el portal `bop.dipgra.es`, que lista boletines por página.
Por cada boletin descarga el PDF, extrae el texto con PyMuPDF o Tesseract OCR como fallback,
y guarda los resultados en CSV por año con conversiones opcionales a Parquet y ZIP.

Attributes:
    anio_scrappeo (int): Año base de inicio.
    script_dir (str): Directorio raíz del script.
    meses (dict): Diccionario de traducción de nombres de mes en español a número.
    calendario (dict): Formato referencial de días por mes.
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
    """Espera la carga de un elemento en la página del BOP Granada.

    Args:
        driver (webdriver.Chrome): Driver activo.
        selector (By.*): Tipo de selector.
        busqueda (str): Valor del selector a esperar.

    Returns:
        bool: True si carga, False si se agotan los reintentos.
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
    """Genera un WebDriver Chrome headless estable para scraping del BOP Granada.

    Returns:
        webdriver.Chrome: Driver listo para navegación headless.
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

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos de línea en cadenas de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF local.
        min_chars (int, optional): Mínimo de caracteres para considerar la extracción exitosa. Default 50.

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

def escribir_url_errores(archivo_errores, url_dia):
    """Registra URLs fallidas en un archivo de log.

    Args:
        archivo_errores (str): Ruta del archivo de log (sin extensión).
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
        respuesta = requests.get(url_buscar, stream=True)
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
    """Anexa filas al CSV acumulativo anual.

    Args:
        df (pd.DataFrame): DataFrame a guardar.
        ruta (str): Directorio destino.
        anio (int|str): Año para el nombre del archivo CSV.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

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

def crear_df_temporal(titulo, num_boletin, fecha, texto_pdf, a, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos del boletin de Granada.

    Args:
        titulo (str): Título del boletin (atributo `title` del enlace).
        num_boletin (str): Número del boletin extraído del título.
        fecha (str): Fecha formateada `DD-MM-AAAA`.
        texto_pdf (str): Texto extraído del PDF.
        a (str): URL de descarga del PDF.
        ruta_guardar_pdf (str): Ruta local del PDF.

    Returns:
        pd.DataFrame: Fila lista para el CSV.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": titulo,
        "publication_date": fecha,
        "bullein_number": num_boletin,
        "pdf_content": texto_pdf,
        "text": texto_pdf,
        "url": a,
        "read_date": fecha_lectura,
        "route_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF (segunda definición de uso general).

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
        language (str, optional): Código de idioma. Default `'spa'`.
        poppler_path (str, optional): Ruta al binario de Poppler.

    Returns:
        str: Texto extraído o cadena vacía en caso de error.
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
    """Procesa un PDF intentando primero extracción directa y usando OCR como fallback.

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

def scrapear_dias_completos():
    """Orquestador del scraping del BOP Granada.

    Accede al portal `bop.dipgra.es/publica/boletines-anteriores` y navega página a página
    por el listado de boletines anteriores. Por cada boletin extrae el título, número, fecha
    y URL, descarga el PDF, extrae el texto y guarda el resultado en CSV.
    Al finalizar convierte el CSV a Parquet y genera un ZIP del año.
    """

    ruta_csv_actual = ""
    anio = 2025
    ruta_archivo_errores = os.path.join("url_errores")

    try: 
        base_enlace = f"https://bop.dipgra.es/publica/boletines-anteriores/resultados-bop-anteriores/"
        print(f"Entramos al enlace: {base_enlace}")
        
        driver = iniciar_driver()
        driver.get(base_enlace)

        while int(anio) > 1983:
            if verificar_carga(driver, By.CLASS_NAME, "listado"):
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "listado")))
                listado = driver.find_element(By.CLASS_NAME, "listado")
                decretos = listado.find_elements(By.CLASS_NAME, "elementoListado")

                for decreto in decretos:
                    contenido = decreto.find_element(By.CLASS_NAME, "contenido_elemento")
                    a_ = contenido.find_element(By.TAG_NAME, "a")
                    boletin = a_.get_attribute("title")  # <--- CORREGIDO
                    print(f"Boletin: {boletin}")
                    boletin_split = ""
                    
                    lista = boletin.split(" ")
                    num_boletin = lista[1]
                    anio_leido = lista[3]
                    lista[2] = ""
                    
                    boletin_split = lista[0] + "_" + lista[1] + "_" + lista[3]
                    a = a_.get_attribute("href")
                    print(f"Año: {anio_leido}")
                    fecha_elem = contenido.find_element(By.CLASS_NAME, "campo_2")
                    fecha_raw = fecha_elem.text if fecha_elem else ""

                    if fecha_raw:
                        partes_fecha = fecha_raw.strip().lower().split()
                        if len(partes_fecha) == 3:
                            dia_ = partes_fecha[0].zfill(2)
                            mes_ = meses.get(partes_fecha[1], "00")
                            anio_ = partes_fecha[2]
                        else:
                            dia_, mes_, anio_ = "00", "00", "0000"
                    else:
                        dia_, mes_, anio_ = "00", "00", "0000"

                    if anio_leido:
                        dia = dia_
                        mes = mes_
                        anio = anio_
                        base_anio = os.path.join(script_dir, f"{anio}")
                        base_dir_pdfs = os.path.join(base_anio, "PDF")
                        base_dir_csv = base_anio
                    
                        carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                        for carpeta in carpetas:    # Crear las carpetas si no existen
                            os.makedirs(carpeta, exist_ok=True)

                    print(f"Viajamos a: {a}")
                    texto_pdf = ""

                    respuesta, encontrado = intentar_peticion(a, ruta_archivo_errores)
                    if encontrado == 1 and respuesta and respuesta.status_code == 200:
                        ruta_guardar_pdf = f"{base_dir_pdfs}\{boletin_split}.pdf"
                        descargar_pdf(respuesta, ruta_guardar_pdf)
                        texto_pdf = process_pdf(ruta_guardar_pdf)

                        df = crear_df_temporal(boletin, num_boletin, f"{dia}-{mes}-{anio_leido}", texto_pdf, a, ruta_guardar_pdf)
                        guardar_contenido_csv(df, base_dir_csv, anio)
                        time.sleep(1.5)

                try:
                    boton_siguiente = driver.find_element(By.XPATH, '//a[@title="Siguiente" and contains(@class, "paginacion_siguiente")]')
                    siguiente_href = boton_siguiente.get_attribute("href")

                    if siguiente_href:
                        print(f"Avanzamos a la siguiente página: {siguiente_href}")
                        driver.get(siguiente_href)
                        time.sleep(2)  # tiempo para que cargue bien
                    else:
                        print("El botón 'Siguiente' no tiene un href válido.")
                        break
                except NoSuchElementException:
                    print("No se encontró el botón 'Siguiente'. Puede que no haya más páginas.")
                    break

                        
            # Convertir CSV a Parquet
        parquet_path = f"{base_dir_csv}/{anio}.parquet"
        try:
            if os.path.exists(ruta_csv_actual):
                df = pd.read_csv(ruta_csv_actual, encoding='utf-8')
                df.to_parquet(parquet_path, index=False)
                print(f"✅ CSV convertido a Parquet: {parquet_path}")
        except Exception as e:
            print(f"❌ Error al convertir CSV a Parquet para el año {anio}: {e}")

        # Crear un ZIP que agrupe todos los archivos del año
        zip_path = os.path.join(script_dir, f"{anio}.zip")
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Añadir el archivo parquet al ZIP
                if os.path.exists(parquet_path):
                    zipf.write(parquet_path, os.path.basename(parquet_path))
                    zipf.write(ruta_csv_actual, os.path.basename(ruta_csv_actual))
                print(f"✅ Archivo ZIP creado: {zip_path}")
        except Exception as e:
            print(f"❌ Error al crear el archivo ZIP para el año {anio}: {e}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    scrapear_dias_completos()


