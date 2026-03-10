"""Recolector del Diari Oficial de la Generalitat de Catalunya (DOGC).

Este script automatiza la extracción de disposiciones del DOGC usando Selenium para navegar
el calendario interactivo del portal `dogc.gencat.cat`. Por cada día con publicación detectado,
accede al sumario, itera sobre secciones y decretos, descarga el PDF con un driver separado y
extrae el texto HTML del decreto desde una página de texto completo (`fullText`).
Los datos se guardan en CSV por año.

Attributes:
    anio_scrappeo (int): Año de referencia.
    script_dir (str): Directorio raíz del script.
    headers (dict): Cabeceras HTTP para peticiones web.
    calendario (dict): Formato referencial de días por mes.
    meses (dict): Mapa de nombres de mes en castellano a número.
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
import time
import clize
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
import os
from pdf2image import convert_from_path
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import pytesseract
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
import ssl
import glob
import time
import shutil
import zipfile


pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
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

meses = {
    'Enero': '01', 'Febrero': '02', 'Marzo': '03', 'Abril': '04',
    'Mayo': '05', 'Junio': '06', 'Julio': '07', 'Agosto': '08',
    'Septiembre': '09', 'Octubre': '10', 'Noviembre': '11', 'Diciembre': '12'
}

def esperar_y_renombrar_pdf(carpeta_descargas: str, nombre_objetivo: str, timeout: int = 20) -> str:
    """Espera a que se descargue un archivo PDF en la carpeta y lo renombra al nombre objetivo.

    Args:
        carpeta_descargas (str): Carpeta de descargas de Chrome.
        nombre_objetivo (str): Nombre final del PDF.
        timeout (int, optional): Tiempo máximo de espera en segundos. Default 20.

    Returns:
        str: Ruta final del PDF renombrado.

    Raises:
        TimeoutError: Si no se descarga ningún PDF en el tiempo límite.
    """
    tiempo_inicio = time.time()
    archivo_pdf = ""

    while time.time() - tiempo_inicio < timeout:
        # Buscar archivos PDF descargados
        pdfs = glob.glob(os.path.join(carpeta_descargas, "*.pdf"))
        if pdfs:
            # Tomamos el más reciente
            pdfs.sort(key=os.path.getmtime, reverse=True)
            archivo_pdf = pdfs[0]

            # Verificamos que no esté en uso todavía (descargando .crdownload)
            if not archivo_pdf.endswith(".crdownload"):
                ruta_final = os.path.join(carpeta_descargas, nombre_objetivo)
                shutil.move(archivo_pdf, ruta_final)
                return ruta_final
        time.sleep(0.5)

    raise TimeoutError("No se descargó ningún PDF dentro del tiempo esperado.")

def iniciar_driver():
    """Genera un WebDriver Chrome para scraping del DOGC (sin headless para uso interactivo).

    Returns:
        webdriver.Chrome: Driver configurado.
    """
    chrome_options = webdriver.ChromeOptions()
    #chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument("--log-level=3") 
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def iniciar_driver_con_descargas(download_dir: str) -> webdriver.Chrome:
    """Inicia un Chrome headless configurado para descargar PDFs automáticamente en `download_dir`.

    Args:
        download_dir (str): Carpeta de destino para los PDFs descargados.

    Returns:
        webdriver.Chrome: Driver configurado para descarga automática.
    """
    # 1) Asegura que la carpeta existe
    os.makedirs(download_dir, exist_ok=True)

    # 2) Configura opciones de Chrome
    chrome_options = Options()
    chrome_options.add_argument("--headless")                 # modo headless
    chrome_options.add_argument("--disable-gpu")              # recomendado en headless
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": download_dir,           # carpeta de descarga
        "download.prompt_for_download": False,                # sin prompt
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True            # fuerza descarga PDF
    })

    # 3) Instancia el driver
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )

    # 4) Habilita descargas en headless via CDP
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": download_dir}
    )

    return driver

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos de línea en cadenas de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

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
    """Ejecuta una petición GET con contexto TLS 1.2 y reintentos ante caídas HTTP.

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
        context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        context.set_ciphers("DEFAULT")
        respuesta = requests.get(
            url_buscar,
            verify=True,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        print(respuesta.status_code)
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

def crear_df_temporal(identificador, fecha_decreto, nombre_seccion, nombre_subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos y contenido de una disposición del DOGC.

    Args:
        identificador (str): ID único de la disposición.
        fecha_decreto (str): Fecha formateada del decreto.
        nombre_seccion (str): Sección del sumario.
        nombre_subseccion (str): Subsección del sumario.
        contenido_text (str): Texto extraído del HTML del decreto.
        enlace_pdf (str): URL del PDF oficial.
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
        "id": identificador,
        "fecha_decreto": fecha_decreto,
        "seccion": nombre_seccion, 
        "subseccion": nombre_subseccion,
        "contenido": contenido_text,
        "url": enlace_pdf,
        "fecha_lectura": fecha_lectura,
        "ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

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
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((selector, busqueda)))
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

def esperar_descarga_completa(download_dir: str, filename: str, timeout: int = 30) -> bool:
    """Espera hasta que el archivo descargado esté completamente guardado en disco.

    Comprueba que no haya archivos `.crdownload` activos para el nombre esperado.

    Args:
        download_dir (str): Carpeta de descargas de Chrome.
        filename (str): Nombre esperado del archivo descargado.
        timeout (int, optional): Tiempo máximo de espera en segundos. Default 30.

    Returns:
        bool: True si el archivo está completo, False si expira el tiempo.
    """
    target_path = os.path.join(download_dir, filename)
    temp_ext = ".crdownload"
    t0 = time.time()

    while time.time() - t0 < timeout:
        # 1) Comprobar si el archivo final existe
        if os.path.exists(target_path):
            # 2) Asegurarse de que no haya aún un .crdownload abierto
            if not any(
                fn.startswith(filename) and fn.endswith(temp_ext)
                for fn in os.listdir(download_dir)
            ):
                return True
        time.sleep(0.5)
    return False
 
def extraer_num_dogc(enlace_boletin):
    """Extrae el número de boletin DOGC de la URL del sumario.

    Args:
        enlace_boletin (str): URL del sumario con parámetro `numDOGC`.

    Returns:
        str | None: Número del boletin o None si no se encuentra.
    """
    match = re.search(r'numDOGC=(\d+)', enlace_boletin)
    if match:
        return match.group(1)
    else:
        return None

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.expected_conditions import text_to_be_present_in_element

def eliminar_overlay(driver, timeout=5):
    """Elimina el overlay de cookies/PPMS del portal DOGC mediante JavaScript.

    Args:
        driver (webdriver.Chrome): Driver activo.
        timeout (int, optional): Tiempo de espera para detectar el overlay. Default 5.
    """
    try:
        # Esperamos explícitamente que aparezca el overlay si existe
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "ppms_cm_popup_overlay"))
        )
        overlay = driver.find_element(By.ID, "ppms_cm_popup_overlay")

        driver.execute_script("""
            let el = arguments[0];
            if (el && el.parentNode) {
                el.parentNode.removeChild(el);
            }
        """, overlay)
        print("✅ Overlay eliminado con JS.")
        
        # Confirmar que ya no está
        WebDriverWait(driver, 3).until_not(
            EC.presence_of_element_located((By.ID, "ppms_cm_popup_overlay"))
        )
    except Exception as e:
        print("ℹ️ Overlay no visible o ya eliminado.", str(e))

def scrapear_dias_completos():
    """Orquestador del scraping del DOGC.

    Accede al portal DOGC, navega el calendario interactivo mes a mes hacia atrás desde 2025
    hasta 1980. Por cada día con publicación detectado (clase `has-publicacio`), accede al
    sumario, itera por secciones y decretos, descarga el PDF y extrae el texto HTML.
    Guarda los resultados en CSV por año.
    """

    anio = 2025
    ruta_continuar =  os.path.join(script_dir, "ruta_continuar.txt")
    ruta_csv = ""

    enlace_inicial = "https://dogc.gencat.cat/es/inici/"
    driver = iniciar_driver()
    driver.get(enlace_inicial)
    if verificar_carga(driver, By.CSS_SELECTOR, 'div.ui-datepicker-inline.ui-datepicker.ui-widget.ui-widget-content.ui-helper-clearfix.ui-corner-all'):
    
        while int(anio) > 1980: 
            # Eliminar cokies
            try:
                # Esperar hasta que el botón esté clickeable y hacer clic
                boton_rechazar = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "ppms_cm_reject-all"))
                )
                boton_rechazar.click()
                print("Botón de rechazo de cookies clickeado.")
            except:
                print("No se pudo eliminar las cokies")

            try: 
                base_anio = os.path.join(script_dir, f"{anio}")
                base_dir_pdfs = os.path.join(base_anio, "PDF")
                base_dir_csv = base_anio
                ruta_archivo_errores = os.path.join(base_anio, "url_errores")
                ruta_errores_leer = os.path.join(base_anio, "errores_pdf")

                carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                for carpeta in carpetas:    # Crear las carpetas si no existen
                    os.makedirs(carpeta, exist_ok=True)

                    mesaz = driver.find_element(By.CSS_SELECTOR, 'div.ui-datepicker-inline.ui-datepicker.ui-widget.ui-widget-content.ui-helper-clearfix.ui-corner-all')
                    mes_actual = mesaz.find_element(By.CLASS_NAME, 'ui-datepicker-month').text
                    div_dias = driver.find_element(By.CLASS_NAME, 'ui-datepicker-calendar')
                    body_calendario = div_dias.find_element(By.TAG_NAME, 'tbody')
                    cada_fila = body_calendario.find_elements(By.TAG_NAME, 'tr')

                    for fila in cada_fila:
                        dias_fila = fila.find_elements(By.CLASS_NAME, 'has-publicacio')
                        for dia_actual in dias_fila:
                            try:
                                dias_actual_numero = dia_actual.find_element(By.CLASS_NAME, 'ui-state-default').text
                                enlace_boletin = dia_actual.get_attribute('title')
                                numero_boletin = extraer_num_dogc(enlace_boletin)
                                time.sleep(4)
                                print(f"Estamos en el dia: {dias_actual_numero} del mes:{mes_actual}")
                                enlace_completo = f"http://dogc.gencat.cat/es/sumari-del-dogc/{enlace_boletin}"
                                print(f"Viajamos a: {enlace_completo}")
                                """try:
                                    driver_decreto = iniciar_driver()
                                    driver_decreto.get(enlace_completo)
                                    if verificar_carga(driver_decreto, By.CLASS_NAME, 'wrapper-disposicions'):
                                        print(f"Dentro del boletín: {numero_boletin}")
                                        disposiciones = driver_decreto.find_element(By.CLASS_NAME, 'wrapper-disposicions')
                                        pila_hijos = disposiciones.find_elements(By.XPATH, "./*")
                                        nombre_seccion = ""
                                        nombre_subseccion = ""
                                        num_seccion = 0
                                        num_decreto = 0

                                        while pila_hijos:
                                            hijo = pila_hijos.pop(0)

                                            tag = hijo.tag_name
                                            if tag == "h2":
                                                nombre_seccion = hijo.text

                                            elif tag == "h3":
                                                nombre_subseccion = hijo.text
                                                num_seccion += 1
                                                num_decreto = 0

                                            elif tag == "ul":
                                                try:
                                                    todos_decretos = hijo.find_elements(By.TAG_NAME, "li")

                                                    for decreto in todos_decretos:
                                                        try:
                                                            enlaces = decreto.find_element(By.CLASS_NAME, "destacat_text_cont")
                                                            enlace_html = enlaces.find_element(By.TAG_NAME, "a").get_attribute("href")
                                                            enlace_html = enlace_html
                                                            enlaces_pdf_bus = enlaces.find_element(By.TAG_NAME, "div")
                                                            enlace_pdf = enlaces_pdf_bus.find_element(By.TAG_NAME, "a").get_attribute("href")
                                                            num_decreto += 1

                                                            identificador = f"DOGC-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                                                            ruta_guardar_pdf = f"{base_dir_pdfs}\{identificador}"
                                                            print(f"Pasamos a descargar pdf: {identificador}")

                                                            driver_pdf = iniciar_driver_con_descargas(base_dir_pdfs)
                                                            enlace_pdf = enlace_pdf.strip()
                                                            driver_pdf.get(enlace_pdf)

                                                            nombre_fichero = f"{identificador}.pdf"
                                                            esperar_descarga_completa(ruta_guardar_pdf, nombre_fichero)
                                                            ruta_guardar_pdf = os.path.join(base_dir_pdfs, nombre_fichero)
                                                            try:
                                                                ruta_guardar_pdf = esperar_y_renombrar_pdf(base_dir_pdfs, nombre_fichero)
                                                                print(f"PDF descargado como {ruta_guardar_pdf}")
                                                            except Exception as e:
                                                                print(f"Error al descargar/renombrar el PDF: {e}")
                                                                escribir_url_errores(ruta_archivo_errores, enlace_pdf)
                                                                driver_pdf.quit()
                                                                pass

                                                            driver_pdf.quit()

                                                            contenido_html = ""
                                                            driver_html = iniciar_driver()
                                                            print(f"Viajamos a {enlace_html}")
                                                            driver_html.get(enlace_html)
                                                            if verificar_carga(driver_html, By.ID, "fullText"):
                                                                contenido_html = driver_html.find_element(By.ID, "fullText").text
                                                            driver_html.quit()

                                                            df_re = crear_df_temporal(
                                                                identificador,
                                                                f"{dias_actual_numero}-{mes_actual}-{anio}",
                                                                nombre_seccion, 
                                                                nombre_subseccion, 
                                                                contenido_html,
                                                                enlace_pdf,
                                                                ruta_guardar_pdf
                                                            )
                                                            guardar_contenido_csv(df_re, base_dir_csv, anio)
                                                            ruta_csv = f"{base_dir_csv}/{anio}.csv"
                                                            print(f"Guardamos contenido del decreto -> {identificador}")
                                                            time.sleep(1.5)

                                                        except:
                                                            print("Este no es un decreto...")
                                                            pass
                                                except:
                                                    print("Este no son decretos...")
                                                    continue

                                            elif tag == "div":
                                                clase = hijo.get_attribute("id")

                                                if clase == "llistat_destacat_text column":
                                                    wrapper = hijo.find_element(By.CLASS_NAME, "wrapper-disposicions")
                                                    nuevos_hijos = wrapper.find_elements(By.XPATH, "./*")
                                                    print(f"{len(pila_hijos)}")
                                                    pila_hijos = nuevos_hijos + pila_hijos 
                                                    print(f"{len(pila_hijos)}")

                                    driver_decreto.quit()

                                except:
                                    print(f"Tenemos una escepción en un dia del mes de {mes_actual}")"""
                            except:
                                print(f"Tenemos una escepción en un dia del mes de {mes_actual}")

                    try:
                        # Esperar a que el botón sea clickeable
                        prev_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.ui-datepicker-prev.ui-corner-all'))
                        )
                        print("Clickeamos al mes anterior...")

                        mes_antes = driver.find_element(By.CLASS_NAME, 'ui-datepicker-month').text.strip()
                        
                        # Clic con JavaScript para mayor fiabilidad
                        driver.execute_script("arguments[0].click();", prev_button)

                        # Esperar hasta que el mes cambie (timeout 10 seg)
                        WebDriverWait(driver, 10).until(
                            lambda d: d.find_element(By.CLASS_NAME, 'ui-datepicker-month').text.strip() != mes_antes
                        )
                        
                        mes_despues = driver.find_element(By.CLASS_NAME, 'ui-datepicker-month').text.strip()
                        print(f"✅ El mes ha cambiado: {mes_antes} → {mes_despues}")

                        if mes_antes == 'Enero' and mes_despues == 'Diciembre':
                            print("Cambiamos de anio")
                            anio -= 1

                    except Exception as e:
                        print("❌ No se encontró el botón para ir al mes anterior o falló el cambio de mes.")
                        raise e

            except Exception as e:
                print(f"Error inesperado: {str(e)}")
                with open(ruta_archivo_errores, "a", encoding="utf-8") as f:
                    f.write(f"Error en el inicio: {str(e)}\n")

            except ChunkedEncodingError as e:
                print(f"Error en la transferencia de datos: {e}")
                
            except requests.exceptions.RequestException as e:
                print(f"Intento rechazado")

if __name__ == "__main__":
    scrapear_dias_completos()


