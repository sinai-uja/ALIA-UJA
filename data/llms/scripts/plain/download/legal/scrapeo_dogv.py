"""Recolector del Diari Oficial de la Generalitat Valenciana (DOGV).

Este script automatiza la extracción y descarga de resoluciones del DOGV.
Usa Selenium Headless para navegar el portal `dogv.gva.es`, que renderiza sumarios dentro de iframes.
Por cada día, mapea primero las posiciones de los decretos (sección e índice) y luego los procesa
individualmente, descargando el PDF y extrayéndole el texto con PyMuPDF o Tesseract OCR como fallback.
Guarda tabulaciones CSV y registra errores en archivos TXT de continuación.

Attributes:
    anio_scrappeo (int): Año base de inicio.
    script_dir (str): Directorio raíz del script.
    calendario (dict): Formato referencial de días por mes.
"""

import os
from bs4 import BeautifulSoup
from httpcore import TimeoutException
import requests
from datasets import Dataset
import PyPDF2
from io import BytesIO
from urllib.parse import urljoin
import re
import pytesseract
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
import clize
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
import pandas as pd
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
import clize
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
import polars as pl
import pytesseract
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

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

def iniciar_driver():
    """Genera un WebDriver Chrome headless con opciones de estabilidad para scraping pesado.

    Returns:
        webdriver.Chrome: Driver inicializado con ventana maximizada y sin GUI.
    """
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument("--log-level=3") 
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def limpiar_texto(texto):
    """Elimina espacios y saltos redundantes en cadenas de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Registra URLs fallidas en un archivo de log.

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
    """Ejecuta una petición GET con reintentos ante caídas HTTP o transferencias incompletas.

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
        print(f"Guardamos contenido del decreto")

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

def crear_df_temporal(identificador, fecha_decreto, texto_pdf_re, pdf_url, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos y texto del decreto DOGV.

    Args:
        identificador (str): ID único del decreto (Ej. DOGV-AÑO-Boletin-X-Seccion-Y-Decreto-Z).
        fecha_decreto (str): Fecha formateada `DD-MM-AAAA`.
        texto_pdf_re (str): Texto extraído del PDF.
        pdf_url (str): URL del PDF oficial.
        ruta_guardar_pdf (str): Ruta local del PDF descargado.

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
        "fecha_decreto": fecha_decreto,
        "text": texto_pdf_re,
        "url_pdf": pdf_url,
        "fecha_lectura": fecha_lectura,
        "ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto puro directamente desde la capa de texto del PDF usando PyMuPDF.

    Args:
        pdf_path (str): Ruta al PDF local.
        min_chars (int, optional): Mínimo de caracteres para considerar la extracción exitosa. Default a 50.

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
        poppler_path (str, optional): Ruta al binario de Poppler para convertir páginas. Default a ruta estándar.

    Returns:
        str: Texto extraído vía OCR o cadena vacía en caso de error.
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

def verificar_carga(driver, selector, busqueda):
    """Espera la carga de un elemento DOM en la página del DOGV.

    Args:
        driver (webdriver.Chrome): Driver activo.
        selector (By.*): Tipo de selector.
        busqueda (str): Cadena del selector a esperar.

    Returns:
        bool: True si el elemento carga, False si se agotan los reintentos.
    """
    intentos_maximos = 3  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((selector, busqueda)))
            return True
            
        except Exception as e:
            intento += 1
            print(f"Intento {intento}/{intentos_maximos}: Error:{e}. Reintentando...")

            if intento < intentos_maximos:
                print("Recargando la página...")
                driver.refresh()
                time.sleep(2)  
    return False

def scrapear_dias_completos(*, anio_scrappeo: int):
    """Orquestador principal del scraping del DOGV.

    Para cada día del año, carga el sumario desde un iframe en `dogv.gva.es`, mapea
    las posiciones de todos los decretos (sección + índice) y los procesa individualmente.
    En cada decreto: hace clic para abrir el PDF en nueva pestaña, descarga el PDF,
    extrae el texto (PyMuPDF con fallback a OCR Tesseract), guarda el resultado en CSV
    y registra duplicados o fallos en el log de errores.
    Mantiene un archivo TXT de continuación para reanudar scraping interrumpido.

    Args:
        anio_scrappeo (int, kwarg): Año de inicio del scraping.
    """
    for anio in range(anio_scrappeo, anio_scrappeo + 1):
        base_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdfs = os.path.join(base_anio, "PDF")
        base_dir_csv = base_anio
        ruta_archivo_errores = os.path.join(base_anio, "url_errores")
        ruta_continuar = os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [base_anio, base_dir_pdfs, base_dir_csv]
        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        mes_leido = 1
        dia_leido = 1
        numero_boletin = 1

        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{mes_leido},{dia_leido},{numero_boletin}")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                mes_leido, dia_leido, numero_boletin = map(int, f.read().strip().split(','))

        print(f"EMPEZAMOS POR EL DIA -> {dia_leido}-{mes_leido}-{anio}")

        for mes in range(mes_leido, 13):
            dias_mes = calendario.get(mes, [])
            for dia in dias_mes[dia_leido - 1:]:
                try:
                    base_enlaces = f"https://dogv.gva.es/es/sumari?data={anio}-{mes:02}-{dia:02}"

                    # Primer paso: obtener posiciones
                    driver = iniciar_driver()
                    driver.get(base_enlaces)
                    decretos_posiciones = []

                    if verificar_carga(driver, By.CLASS_NAME, "portlet-layout"):
                        print(f"Entramos a la página del día: {dia}-{mes}-{anio}")
                        iframe = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.TAG_NAME, "iframe"))
                        )
                        driver.switch_to.frame(iframe)
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "div.cursor-unset"))
                        )
                        secciones = driver.find_elements(By.CSS_SELECTOR, "div.cursor-unset")
                        if not secciones:
                            print("No existe el decreto de este día")
                            time.sleep(1)
                            driver.quit()
                            continue

                        for i, seccion in enumerate(secciones):
                            decretos = seccion.find_elements(By.CSS_SELECTOR, "i.fa-solid.fa-file-pdf.fa-2x")
                            for j in range(len(decretos)):
                                decretos_posiciones.append((i, j))

                        driver.quit()
                    else:
                        print("No se ha cargado la página")
                        driver.quit()
                        continue

                    for idx_seccion, idx_decreto in decretos_posiciones:
                        try:
                            driver = iniciar_driver()
                            driver.get(base_enlaces)

                            if verificar_carga(driver, By.CLASS_NAME, "portlet-layout"):
                                iframe = WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.TAG_NAME, "iframe"))
                                )
                                driver.switch_to.frame(iframe)
                                WebDriverWait(driver, 10).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.cursor-unset"))
                                )
                                secciones = driver.find_elements(By.CSS_SELECTOR, "div.cursor-unset")
                                if idx_seccion >= len(secciones):
                                    driver.quit()
                                    continue

                                seccion = secciones[idx_seccion]
                                decretos = seccion.find_elements(By.CSS_SELECTOR, "i.fa-solid.fa-file-pdf.fa-2x")
                                if idx_decreto >= len(decretos):
                                    driver.quit()
                                    continue

                                decreto = decretos[idx_decreto]

                                bol = driver.find_element(By.CLASS_NAME, "imc--num")
                                texto_bol = bol.text
                                splter = texto_bol.split(" ")
                                boletin_leido = splter[1]
                                identificador = f"DOGV-{anio}-Boletin-{boletin_leido}-Seccion-{idx_seccion + 1}-Decreto-{idx_decreto + 1}"
                                ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"

                                tabs_antes = driver.window_handles
                                decreto.click()
                                time.sleep(2)
                                tabs_despues = driver.window_handles

                                if len(tabs_despues) > len(tabs_antes):
                                    nueva_pestana = list(set(tabs_despues) - set(tabs_antes))[0]
                                    print("Cambiamos de ventana...")
                                    driver.switch_to.window(nueva_pestana)
    
                                pdf_url_modificar = driver.current_url
                                pdf_url = pdf_url_modificar.replace('_va.pdf', '_es.pdf')

                                respuesta_pdf, encontrado_pdf = intentar_peticion(pdf_url, ruta_archivo_errores)
                                if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                    descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                    texto_pdf_re = process_pdf(ruta_guardar_pdf)
                                    csv_path = os.path.join(base_dir_csv, f"{anio}.csv")

                                    if texto_pdf_re != "":
                                        #os.remove(ruta_guardar_pdf)
                                        print(f"PDF leído y eliminado")
                                    else:
                                        escribir_url_errores(ruta_archivo_errores, pdf_url)

                                    text = texto_pdf_re
                                    identificador_ya_existe = False
                                    if os.path.exists(csv_path):
                                        df_existente = pd.read_csv(csv_path)
                                        if 'Identificador' in df_existente.columns:
                                            identificador_ya_existe = identificador in df_existente['Identificador'].values

                                    if not identificador_ya_existe:
                                        df_re = crear_df_temporal(
                                            identificador,
                                            f"{dia}-{mes}-{anio}",
                                            text,
                                            pdf_url,
                                            ruta_guardar_pdf
                                        )
                                        guardar_contenido_csv(df_re, base_dir_csv, anio)
                                        print(f"Guardamos contenido del decreto -> {identificador}")
                                        time.sleep(0.5)
                                    else:
                                        escribir_url_errores(ruta_archivo_errores, pdf_url)
                                driver.close()
                                driver.switch_to.window(driver.window_handles[0])
                                driver.quit()
                        except Exception as e:
                            print(f"Error procesando decreto {idx_seccion}-{idx_decreto}: {e}")
                            driver.quit()
                            continue

                    numero_boletin += 1
                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                        print(f"Guardamos el fichero en el boletin: {mes}-{dia}-Boletin-{numero_boletin - 1}")
                        f.write(f"{mes},{dia},{numero_boletin - 1}")

                except Exception as e:
                    print(f"Error inesperado en el día {dia}: {e}")
                    continue

                except ChunkedEncodingError as e:
                    print(f"Error en la transferencia de datos: {e}")
                    continue

                except requests.exceptions.RequestException as e:
                    print(f"Intento rechazado: {e}")
                    continue
            dia_leido = 1


if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


