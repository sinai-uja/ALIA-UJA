"""Recolector del Boletín Oficial de la Provincia de Málaga (BOP Málaga).

Este script automatiza la extracción y descarga de resoluciones del BOP de Málaga.
Usa Selenium Headless para navegar `bopmalaga.es` accediendo a sumarios diarios.
Por día verifica la fecha en página, extrae secciones y decretos, descarga el texto HTML
como el PDF (para años posteriores a 2017), extrayendo el texto con PyMuPDF o Tesseract OCR.

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

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos en cadenas de texto.

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
    """Ejecuta una petición GET con cabeceras de usuario y reintentos ante caídas HTTP.

    Args:
        url_buscar (str): URL a consultar.
        ruta_errores (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
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

def crear_df_temporal(identificador, resumen, seccion, fecha, texto_html, texto_pdf, url_pdf, url_html, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos y contenido de un decreto del BOP de Málaga.

    Args:
        identificador (str): ID único del decreto.
        resumen (str): Breve descripción extraída de `vista_edicto`.
        seccion (str): Sección del sumario.
        fecha (str): Fecha formateada `DD-MM-AAAA`.
        texto_html (str): Texto extraído del modal HTML del decreto.
        texto_pdf (str): Texto extraído del PDF.
        url_pdf (str): URL del PDF oficial.
        url_html (str): URL del visor HTML del decreto.
        ruta_guardar_pdf (str): Ruta local del PDF.

    Returns:
        pd.DataFrame: Fila lista para el CSV.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    texto_c = texto_html + "\n" + texto_pdf

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "publication_date": fecha,
        "summary": resumen,
        "section": seccion,
        "html_content":texto_html,
        "pdf_content": texto_pdf,
        "text": texto_c,
        "url": url_pdf,
        "url_html": url_html,
        "read_date": fecha_lectura,
        "route_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF (segunda definición).

    Args:
        pdf_path (str): Ruta al PDF.
        min_chars (int, optional): Mínimo de caracteres. Default 50.

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
        pdf_path (str): Ruta al PDF.
        language (str, optional): Código de idioma. Default `'spa'`.
        poppler_path (str, optional): Ruta al binario de Poppler.

    Returns:
        str: Texto extraído via OCR.
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

import os
import time

def esperar_y_renombrar_pdf(nombre_deseado, ruta_pdf, timeout=15):
    """Espera a que se descargue un PDF en la carpeta de descargas y lo renombra al nombre deseado.

    Args:
        nombre_deseado (str): Nombre final del archivo PDF.
        ruta_pdf (str): Carpeta donde se descarga el PDF.
        timeout (int, optional): Tiempo máximo de espera en segundos. Default 15.

    Returns:
        str: Ruta final del PDF renombrado.

    Raises:
        TimeoutError: Si no se descarga ningún PDF en el tiempo límite.
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
    """Genera un WebDriver Chrome con soporte para descarga automática de PDFs.

    Args:
        ruta_descarga (str, optional): Carpeta donde Chrome guardará los PDFs descargados.
            Si se especifica, Chrome se configura para no mostrar el diálogo de guardado.
        headless (bool, optional): Si True el navegador se ejecuta sin interfaz gráfica. Default True.

    Returns:
        webdriver.Chrome: Driver configurado.
    """
    chrome_options = Options()

    chrome_options.add_argument("--headless")

    
    chrome_options.add_argument("--disable-popup-blocking")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")

    if ruta_descarga:
        prefs = {
            "download.default_directory": ruta_descarga,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True  # Muy importante para evitar el visor de PDFs
        }
        chrome_options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def scrapear_dias_completos(*, anio_scrappeo: int):
    """Orquestador del scraping del BOP de Málaga.

    Itera sobre los días del calendario para un rango de años descendente (16 años desde el informado).
    Por cada día accede a la URL del BOP, verifica la fecha publicada en página, extrae secciones
    y decretos con sus enlaces HTML/PDF, descarga el texto del HTML vía modal y el PDF (post-2017).
    Guarda los datos en CSV por año.

    Args:
        anio_scrappeo (int, kwarg): Año de inicio del scraping (trabaja de forma descendente).
    """

    ruta_csv_actual = ""
    for anio in range(anio_scrappeo, anio_scrappeo - 16, -1): 
        base_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdfs = os.path.join(base_anio, "PDF")
        base_dir_csv = base_anio
        ruta_archivo_errores = os.path.join(base_anio, "url_errores")

        for carpeta in [base_anio, base_dir_pdfs, base_dir_csv]:
            os.makedirs(carpeta, exist_ok=True)

        for mes in range(1, 13):  
            dias_mes = calendario.get(mes, [])

            for dia in dias_mes[1-1:]:
                try: 
                    print(f"EMPEZAMOS POR EL DÍA -> {dia}-{mes}-{anio}")
                    base_enlace = f"https://www.bopmalaga.es/index.php?fecha={dia:02}-{mes:02}-{anio}"
                    print(f"📅 Visitando: {base_enlace}")

                    driver = iniciar_driver(ruta_descarga=base_dir_pdfs, headless=False)
                    driver.get(base_enlace)

                    if verificar_carga(driver, By.ID, "seccionSumario"):
                        try:
                            fecha_publicada = driver.find_element(By.ID, "main")
                            header = fecha_publicada.find_element(By.TAG_NAME, "header")
                            h2 = header.find_element(By.TAG_NAME, "h2")
                            fecha_publicada = h2.find_element(By.TAG_NAME, "time").text

                            partes = fecha_publicada.split()  
                            dia_leido = int(partes[0])
                            mes_leido = meses[partes[2].lower()]
                            anio_leido = int(partes[4])

                            # Crear objeto fecha y formatear
                            fecha_leida = f"{anio_leido}-{mes_leido:02}-{dia_leido:02}"
                            fecha_objetivo = f"{anio}-{mes:02}-{dia:02}"

                            if fecha_leida != fecha_objetivo:
                                print(f"⚠️ Fecha en página ({fecha_leida}) no coincide con la esperada ({fecha_objetivo}). Saltamos.")
                                driver.quit()
                                continue
                            print(f"✅ Fecha confirmada: {fecha_leida}")
                        except Exception as e:
                            print(f"⚠️ No se pudo verificar la fecha: {e}")
                            driver.quit()
                            continue

                        contenido = driver.find_element(By.ID, "seccionSumario")
                        secciones = contenido.find_elements(By.TAG_NAME, "section")
                        num_seccion = 0
                        num_decreto = 0
                        nombre_seccion_actual = ""

                        for seccion in secciones:
                            num_seccion += 1
                            num_decreto = 0
                            nombre_seccion_actual = seccion.find_element(By.TAG_NAME, "h3").text
                            decretos = seccion.find_elements(By.TAG_NAME, "article")

                            for decreto in decretos:
                                num_decreto += 1
                                resumen = decreto.find_element(By.CLASS_NAME, "vista_edicto").text
                                resumen = re.sub(r'Ver edicto', '', resumen, flags=re.DOTALL).strip()
                                enlaces = decreto.find_element(By.CLASS_NAME, "span_enlaces")
                                identificador = f"BOP-{anio}-Boletin-{dia}-{mes}-{anio}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                print(f"📄 id: {identificador}")

                                if enlaces:
                                    links = enlaces.find_elements(By.TAG_NAME, "a")
                                    enlace_html = links[0] 
                                    if anio > 2017:
                                        enlace_pdf = links[1] 

                                    texto_html = ""
                                    try:
                                        enlace_html.click()
                                        time.sleep(1.5)  # espera a que aparezca el modal
                                        texto_html = ""

                                        # Ajusta el selector según tu estructura HTML
                                        try:
                                            modal_contenido = driver.find_element(By.ID, "page-container")
                                            texto_html = modal_contenido.text
                                        except:
                                            print("Años antiguos")
                                        
                                        try:
                                            print("Buscamos el texto del edicto")
                                            texto_html += driver.find_element(By.ID, "edictoTXT").text
                                        except:
                                            print("Años nuevos")

                                        # Cerrar el modal
                                        boton_cerrar = driver.find_element(By.CSS_SELECTOR, "i.fa.fa-times")
                                        boton_cerrar.click()
                                        time.sleep(1)

                                    except Exception as e:
                                        print(f"❌ No se pudo extraer HTML del decreto {identificador}: {e}")
                                        texto_html = ""
                                    

                                    links = enlaces.find_elements(By.TAG_NAME, "a")
                                    enlace_html = links[0]
                                    texto_pdf = ""
                                    url_pdf = ""
                                    ruta_final_pdf = ""

                                    if anio > 2017:
                                        enlace_pdf = links[1]
                                        
                                        url_pdf = enlace_pdf.get_attribute("href")

                                        # Abrimos el PDF en nueva pestaña para iniciar descarga
                                        handle_original = driver.current_window_handle
                                        print("------------------------------------------------")
                                        # Abrimos el PDF en nueva pestaña
                                        driver.execute_script("window.open(arguments[0]);", url_pdf)
                                        time.sleep(2)

                                        # Cambiamos a la nueva pestaña (última)
                                        driver.switch_to.window(driver.window_handles[-1])
                                        ruta_final_pdf = esperar_y_renombrar_pdf(f"{identificador}.pdf", base_dir_pdfs)
                                        texto_pdf = process_pdf(ruta_final_pdf)


                                    df = crear_df_temporal(
                                        identificador, resumen, nombre_seccion_actual,
                                        f"{dia}-{mes}-{anio}", texto_html, texto_pdf, 
                                        url_pdf, enlace_html.get_attribute("href"),
                                        ruta_final_pdf
                                    )

                                    guardar_contenido_csv(df, base_dir_csv, anio)
                                    time.sleep(2)
                            
                    else:
                        print(f"⚠️ Boletín no disponible.")

                    driver.quit()

                except ChunkedEncodingError as e:
                    print(f"❌ ChunkedEncodingError: {e}")
                    continue
                except requests.exceptions.RequestException:
                    print(f"❌ Error de conexión.")
                    continue
                except Exception as e:
                    print(f"❌ Error inesperado el día {dia}: {e}")
                    continue


if __name__ == "__main__":
    clize.run(scrapear_dias_completos)