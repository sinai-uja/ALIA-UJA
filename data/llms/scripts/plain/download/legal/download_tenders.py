"""Recolector de licitaciones públicas del Estado Español.

Este script automatiza la búsqueda, extracción y descarga de información sobre 
licitaciones públicas a través del portal de Contratación del Estado. Utiliza 
Selenium para iterar por resoluciones y Beautiful Soup para extraer los pliegos
y documentos adjuntos. Los archivos PDF se procesan mediante PyMuPDF u OCR
(Tesseract) para obtener su texto. Toda la información extraída se guarda en 
archivos CSV organizados por año de licitación.
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
from selenium.webdriver.support.ui import Select


def start_driver():
    """Inicializa y configura el navegador Chrome sin interfaz gráfica.

    Configura las opciones de Selenium para ejecutar Chrome en modo headless
    (invisible), desactivar el sandboxing (útil en entornos de servidor o
    contenedores) y deshabilitar el uso de memoria compartida /dev/shm.

    Returns:
        webdriver.Chrome: Una instancia configurada del navegador Chrome.
    """
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)
    return driver

def guardar_ya_leido(identifier, path):
    """Guarda un identificador de expediente en el archivo de registro.

    Añade una nueva línea con el identificador al archivo especificado en 'path',
    para llevar control de las licitaciones ya procesadas y evitar duplicidades.

    Args:
        identifier (str): El ID del expediente de licitación.
        path (str): La ruta al archivo de texto de registro.
    """
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{identifier}\n")

def cargar_ya_leidos(path):
    """Carga los identificadores de expedientes ya procesados desde un archivo.

    Lee el archivo línea por línea y devuelve un conjunto (set) con los
    identificadores para búsquedas de membresía rápidas.

    Args:
        path (str): La ruta al archivo de texto de registro.

    Returns:
        set: Un conjunto de strings correspondientes a los IDs ya procesados. 
            Si el archivo no existe, devuelve un conjunto vacío.
    """
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    return set()

def select_spain_and_wait(driver):
    """Filtra la tabla de resultados de licitaciones por país (España).

    Espera a que se cargue el menú de selección de país, escoge 'ES' (España)
    y pulsa el botón de búsqueda. Posteriormente, espera hasta que aparezcan 
    los resultados en la tabla.

    Args:
        driver (webdriver.Chrome): La instancia activa de Selenium.
    """
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "viewns_Z7_AVEQAI930OBRD02JPMTPG21004_:form1:menu1MAQ1"))
    )
    select_element = driver.find_element(By.ID, "viewns_Z7_AVEQAI930OBRD02JPMTPG21004_:form1:menu1MAQ1")
    select = Select(select_element)
    select.select_by_value("ES")  # España
    time.sleep(1)
    boton_buscar = driver.find_element(By.ID, "viewns_Z7_AVEQAI930OBRD02JPMTPG21004_:form1:button1")
    boton_buscar.click()
    print("Clickado para filtrar")
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.ID, "myTablaBusquedaCustom"))
    )
    print("Ya filtrado a españa...")

def escribir_url_errores(archivo_errores, url_dia):
    """Registra una URL que ha fallado en el archivo de registro de errores.

    Añade la URL problemática al final del archivo especificado para posible 
    revisión o reintento posterior.

    Args:
        archivo_errores (str): La ruta base (sin extensión .txt) del archivo
            de errores.
        url_dia (str): La URL que causó el fallo.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def get_html_links_from_detail(driver):
    """Extrae enlaces a documentos HTML desde la vista de detalle de una licitación.

    Busca en la tabla de documentos publicados aquellos enlaces cuyo texto
    contiene la palabra 'Html', recogiendo sus atributos 'href'.

    Args:
        driver (webdriver.Chrome): La instancia activa de Selenium, posicionada
            en la página de detalle de una licitación.

    Returns:
        list[str]: Lista de URLs a los documentos HTML encontrados.
    """
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "myTablaDetalleVISUOE"))
        )
        tabla = driver.find_element(By.ID, "myTablaDetalleVISUOE")

        rows = tabla.find_elements(By.XPATH, ".//tr[contains(@class, 'rowClass')]")
        html_links = []

        for row in rows:
            html_link_elements = row.find_elements(By.XPATH, ".//a[contains(text(), 'Html')]")
            for link in html_link_elements:
                href = link.get_attribute("href")
                if href and href not in html_links:
                    html_links.append(href)

        if html_links:
            print(f"🔗 Enlaces HTML encontrados: {len(html_links)}")
        else:
            print("❌ No se encontraron enlaces HTML en esta licitación.")

        return html_links

    except Exception as e:
        print(f"⚠️ Error al extraer enlaces HTML: {e}")
        return []

def get_html_content(html_url):
    """Extrae enlaces HTML a partir de una URL secundaria usando Selenium.

    Abre una nueva instancia del navegador, navega a la URL proporcionada
    (generalmente un enlace interno de un documento) y busca enlaces con texto
    'html' en su interior, útil para ciertas estructuras de publicación complejas.

    Args:
        html_url (str): La URL de la página a analizar.

    Returns:
        list[str]: Lista de URLs absolutas correspondientes a los recursos HTML
            encontrados.
    """
    driver_html = start_driver()
    driver_html.get(html_url)

    try:
        WebDriverWait(driver_html, 10).until(
            EC.presence_of_element_located((By.ID, "myTablaDetalleVISUOE"))
        )
        tabla = driver_html.find_element(By.ID, "myTablaDetalleVISUOE")
        celdas_doc = tabla.find_elements(By.CSS_SELECTOR, "td.documentosPub")

        html_links = []
        for celda in celdas_doc:
            links = celda.find_elements(By.TAG_NAME, "a")
            for link in links:
                if link.text.strip().lower() == "html":
                    href = link.get_attribute("href")
                    if href and href not in html_links:
                        html_links.append(href)


        if html_links:
            print(f"🔗 Enlaces HTML encontrados: {len(html_links)}")
        else:
            print("❌ No se encontraron enlaces HTML en esta licitación.")

        return html_links

    except Exception as e:
        print(f"⚠️ Error al extraer enlaces HTML: {e}")
        return []

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
    """Procesa un archivo PDF extrayendo su texto.
    
    Primero intenta extraer el texto usando métodos directos (PyMuPDF).
    Si el resultado está vacío o es insuficiente (sugiriendo un PDF
    escaneado o imagen), emplea reconocimiento óptico de caracteres (OCR)
    con Tesseract/Poppler.

    Args:
        pdf_file (str): La ruta local al archivo PDF.

    Returns:
        str: El texto extraído del documento PDF.
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

def guardar_contenido_csv(df, ruta):
    """Guarda un DataFrame de pandas conteniendo los datos en un archivo CSV.

    Si el DataFrame no está vacío, lo anexa al archivo CSV en la ruta
    especificada. Si el archivo no existe, lo crea e inserta los nombres
    de las columnas como cabecera.

    Args:
        df (pd.DataFrame): El DataFrame con la información de la licitación.
        ruta (str): La ruta (sin extensión .csv) donde guardar el archivo.
    """
    if not df.empty:
        archivo_csv = f"{ruta}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Documento guardado en csv")

def descargar_pdf(response_pdf, enlacePDF):
    """Guarda el contenido de una respuesta HTTP en disco como archivo PDF.

    Utiliza iter_content para descargar el archivo en fragmentos continuos y
    limitar el uso de memoria en archivos muy grandes.

    Args:
        response_pdf (requests.models.Response): Objeto de respuesta HTTP
            cuyo contenido binario se guardará.
        enlacePDF (str): Nombre y ruta local del archivo a crear.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def limpiar_texto(texto):
    """Limpia el texto eliminando espacios o saltos de línea adicionales.

    Combina todos los bloques separados por espacios en blanco (incluyendo 
    retornos de carro, tabulaciones y saltos de línea) utilizando un único
    espacio simple.

    Args:
        texto (str): La cadena de texto de entrada a ser limpiada.

    Returns:
        str: El texto sin espacios redundantes.
    """
    return " ".join(str(texto).split()) 

def crear_df_temporal(identificador, h5, contenido_htmls, contenido_pliegos, texto, url, expediente, fecha):
    """Construye un DataFrame de pandas de una fila a partir de la información procesada.

    Agrega los datos de la licitación (id, fechas, expediente, contenido) y calcula
    la fecha de lectura actual. Aplica limpieza de texto a todas las columnas usando
    la función 'limpiar_texto'.

    Args:
        identificador (str): ID asignado a la iteración en el script.
        h5 (str): Texto extraído del título (h5) de la licitación.
        contenido_htmls (str): Cadenas agrupadas con datos extraídos de enlaces HTML.
        contenido_pliegos (str): Textos obtenidos de los PDFs asociados.
        texto (str): Combinación final de todo el texto asociado.
        url (str): URL de la página de detalle de la licitación.
        expediente (str): El código o ID oficial del expediente.
        fecha (str): Fecha límite de presentación u otra fecha referenciada en la tabla.

    Returns:
        pd.DataFrame: Un dataframe limpio conteniendo los campos definidos de
            esta licitación.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "date": fecha,
        "publication_date": h5,
        "record": expediente,
        "content_htmls": contenido_htmls,
        "pdf_content": contenido_pliegos,
        "text": texto,
        "url": url,
        "read_date": fecha_lectura
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def intentar_peticion(url_buscar, ruta_errores):
    """Abre una petición GET con soporte de reintentos escalonados.

    Si una petición HTTP a la URL retorna un 200 o 404, retorna de forma
    inmediata. Si falla o lanza una excepción, reintenta hasta 10 veces
    aumentando progresivamente el tiempo de espera.

    Args:
        url_buscar (str): La URL objetivo para la petición GET en modo stream.
        ruta_errores (str): Ruta base del archivo para apuntar los fallos.

    Returns:
        tuple[requests.models.Response|None, int]: Una tupla conteniendo
            el objeto respuesta y un intero (1=éxito parcial/total, 0=fracaso).
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

def scrape_licitaciones():
    """Flujo principal: Configura directorios, arranca el raspador y procesa las licitaciones.

    Entra en la página de Contratación del Estado española, simula el filtrado 
    del buscador por país (España), e itera ininterrumpidamente extrayendo la
    información de cada fila en los resultados resultantes. Accede al detalle, 
    parsea los documentos (HTML, PDF), clasifica los resultados por año, y los 
    guarda progresivamente en CSV.

    Mantiene un archivo 'ya_leidos.txt' en el que apunta los expedientes ya
    procesados para poder reanudar el trabajo tras posibles fallos de red 
    o interrupciones del script.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ya_leidos_path = os.path.join(script_dir, "ya_leidos.txt")
    base_dir_csv = os.path.join(script_dir)
    base_dir_pdfs = os.path.join(script_dir, "pdf")
    ya_leidos_set = cargar_ya_leidos(ya_leidos_path)
    ruta_archivo_errores = os.path.join(script_dir, "errores")

    carpetas = [base_dir_csv, base_dir_pdfs]

    for carpeta in carpetas:
        os.makedirs(carpeta, exist_ok=True)


    base_enlace = (
        "https://contrataciondelestado.es/wps/portal/!ut/p/b1/jc7LDoIwEAXQb-ELZihthWXl1RIUlIfSDenCGAyPjfH7rcat6Oxucu7MgIbO5S5Dxn0P4Qx6No_hau7DMpvxlTXvaVyEYSIJ-pUXIcmjpuHSxpRZ0FnAvJC2WVvySqWISiZR3tidKeH_9fHLCPzVP4FeJ-QD1l58g5Uf9nKZLtBZtulFGx-ECjwstkd7KCt3dZkSF5FCDZ2CSY9JoG7UCMd5AsfXxdg!/dl4/d5/L2dBISEvZ0FBIS9nQSEh/pw/Z7_AVEQAI930OBRD02JPMTPG21004/act/id=0/p=javax.servlet.include.path_info=QCPjspQCPbusquedaQCPFormularioBusqueda.jsp/611498585907/-/"
    )
    contador = 0
    while True:
        contador += 1
        driver = start_driver()
        identificador = f"Licitacion_{contador}"
        driver.get(base_enlace)
        try:
            select_spain_and_wait(driver)
            table = driver.find_element(By.ID, "myTablaBusquedaCustom")
            body = table.find_element(By.TAG_NAME, "tbody")
            rows = body.find_elements(By.TAG_NAME, "tr")
            print(f"{len(rows)}")

            for row in rows:
                try:
                    print("Entramos a buscar expediente")
                    expediente_elem = row.find_element(By.CLASS_NAME, "tdExpediente")
                    expediente_id = expediente_elem.text.strip()
                    expediente_id_ = expediente_id.split()
                    expediente_id = expediente_id_[0]

                    fecha_pres = row.find_element(By.CLASS_NAME, "tdFechaLimite").text
                    print(fecha_pres)
                    fechas = fecha_pres.split("/")
                    anio = fechas[2]

                    # Crear carpeta PDF para el año si no existe
                    pdf_dir_anio = os.path.join(base_dir_pdfs, anio)
                    os.makedirs(pdf_dir_anio, exist_ok=True)

                    # CSV de salida por año
                    csv_anio_path = os.path.join(base_dir_csv, f"{anio}_licitaciones")


                    if expediente_id in ya_leidos_set:
                        continue
                    guardar_ya_leido(expediente_id, ya_leidos_path)
                    ya_leidos_set.add(expediente_id)

                    print(f"\n Procesando expediente: {expediente_id}")
                    link = expediente_elem.find_element(By.TAG_NAME, "a")
                    link.click()

                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.ID, "DetalleLicitacionVIS_UOE"))
                    )
                    url_licitacion = driver.current_url

                    html_urls = get_html_links_from_detail(driver)
                    contenido_htmls = ""
                    contenido_pliegos = ""
                    texto = ""
                    h5 = ""
                    print("Pasamos a leer en los enlaces")
                    for html_url in html_urls:
                        print(f"Entramos a html: {html_url}")
                        response_, encontrado = intentar_peticion(html_url, ruta_archivo_errores)
                        if encontrado == 1 and response_ and response_.status_code == 200:
                            soup_ = BeautifulSoup(response_.text, 'html.parser')
                            contenido_htmls += soup_.text

                            try:
                                try:
                                    h5 = soup_.find("h5").text
                                except:
                                    print("No tiene h5")
                                    pass
                                try:    
                                    plieg = soup_.find("div", class_="boxWithBackground")
                                    ules = plieg.find("ul")
                                    todos_li = ules.find_all("li")
                                except:
                                    print("No tiene pliegos")
                                    pass

                                for li in todos_li:
                                    a = li.find("a")
                                    titulo_enlace_ = a.text
                                    titulo = titulo_enlace_.split(" ")
                                    titulo_enlace = ""
                                    for p in titulo:
                                        titulo_enlace += p + "_"
                                    enlace_pdf = a['href']
                                    print(f"Descargamos pdf: {enlace_pdf}")
                                    response_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                    if encontrado_pdf == 1 and response_pdf and response_pdf.status_code == 200:
                                        content_type = response_pdf.headers.get('Content-Type', '').lower()
                                        if 'pdf' in content_type:
                                            ruta_guardar_pdf = os.path.join(pdf_dir_anio, f"{titulo_enlace}_{identificador}.pdf")
                                            descargar_pdf(response_pdf, ruta_guardar_pdf)
                                            contenido_pliegos += titulo_enlace + ": "
                                            contenido_pliegos += process_pdf(ruta_guardar_pdf) + " "
                                        else:
                                            print(f"[!] El archivo no es un PDF: {enlace_pdf} (Content-Type: {content_type})")
                            except:
                                print("Error en la extraccion de pliegos")
                    texto = contenido_htmls + " || " + contenido_pliegos
                    df = crear_df_temporal(identificador, h5, contenido_htmls, contenido_pliegos, texto, url_licitacion, h5, fecha_pres)
                    guardar_contenido_csv(df, csv_anio_path)
                    time.sleep(2)
                    break

                except Exception as e:
                    print(f"Error al procesar fila: {e}")
            driver.quit()
        except Exception as e:
            print(f"Error general: {e}")
            time.sleep(5)
            driver.quit()
            continue

if __name__ == "__main__":
    scrape_licitaciones()
