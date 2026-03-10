"""Scraper del Centro Andaluz de Documentación e Información de Medicamentos (CADIME).

Este módulo utiliza Selenium Webdriver para navegar el portal web de CADIME,
identificar publicaciones y boletines divulgativos, descargar sus PDFs asociados
(mediante `requests`) y extraer su contenido textual usando la biblioteca
`PyMuPDF` (`fitz`). Toda la información recuperada es consolidada en un
archivo CSV que incluye metadatos y el texto estructurado.

Example:
    Ejecución del script en entorno de captura::

        python scrapeo_biomedico_cadime.py

    Arrancará una sesión de Selenium en modo headless, descargará los PDFs
    y generará un archivo `cadime_biomedicina.csv` con los datos.

Note:
    Depende críticamente de `webdriver-manager` para la actualización
    dinámica de ChromeDriver. Además, requiere `fitz` (PyMuPDF) para
    la extracción en texto plano desde documentos PDF. Maneja paginación
    y contenido cargado dinámicamente, asegurando la robustez de las
    esperas e interactuaciones con Selenium.
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
import fitz  
import concurrent.futures
from tqdm import tqdm
import sys
import gc
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))

calendario = { 
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

def iniciar_driver():
    """Configura e inicia un WebDriver de Chrome.

    Establece las opciones de ejecución en modo 'headless' para evitar
    la carga de interfaces gráficas. Aísla procesos (no-sandbox) y 
    minimiza la retención de RAM suprimiendo el log de GPU y dev-shm.

    Returns:
        webdriver.Chrome: Instancia del driver configurado.
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

def limpiar_texto(texto: str) -> str:
    """Elimina dobles espacios y purga retornos redundantes de una cadena de texto.

    Args:
        texto (str): Texto en crudo.

    Returns:
        str: Texto unificado con un solo espaciado regular.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path: str, min_chars: int = 50) -> tuple:
    """Extrae texto contenido de un archivo PDF usando PyMuPDF (fitz).

    Abre un archivo PDF local y procesa de forma directa la indexación 
    de texto en crudo de todas las páginas, determinando de esta forma
    si posee información legítimamente parseable por extensión vs imágenes exclusivas.

    Args:
        pdf_path (str): Ruta al fichero PDF que se evaluará.
        min_chars (int, optional): Número mínimo de caracteres para no considerarlo vacío. Defaults to 50.

    Returns:
        tuple: (direct_text, is_valid)
            - direct_text (str): El texto recuperado del documento.
            - is_valid (bool): True si fue exitosa la extracción, False ante fallos o vacíos.
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
        with open(ruta_errores, 'w', encoding='utf-8') as f:
            f.write(f"Error en el pdf: {ruta_errores}")
        return "", False

def escribir_url_errores(archivo_errores: str, url_dia: str) -> None:
    """Consigna un archivo de registro con URLs problemáticas.

    Args:
        archivo_errores (str): Nombre base o ruta del archivo de errores (sin extensión).
        url_dia (str): La URL fallida o generadora de conflicto.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar: str, ruta_errores: str) -> tuple:
    """Gestiona una petición HTTP a una URL implementando una lógica de reintentos.

    Procura sortear errores de conexión o tiempos de respuesta prolongados,
    tolerando fallas intermitentes (`ChunkedEncodingError`). Da constancia en 
    registros si los intentos máximos fracasan.

    Args:
        url_buscar (str): Dirección web de interés.
        ruta_errores (str): Ruta al archivo de texto a nutrir con errores.

    Returns:
        tuple: (respuesta, encontrada_respuesta)
            - respuesta (requests.Response | None): El objeto Response en caso de dar 200/404.
            - encontrada_respuesta (int): 1 (Logrado), 0 (Fallido permanente).
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

def guardar_contenido_csv(df: pd.DataFrame, ruta: str) -> None:
    """Añade un DataFrame con los metadatos y cuerpo extraído de un boletín al archivo final.

    Realiza agregaciones intermitentes (`mode='a'`) manejando la presencia o
    carencia del header de un CSV.

    Args:
        df (pd.DataFrame): DataFrame unitario con datos.
        ruta (str): Directorio raíz donde reside o residirá `cadime_biomedicina.csv`.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/cadime_biomedicina.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf: requests.Response, enlacePDF: str) -> None:
    """Vuelca en bloque a un archivo local el flujo binario desde la red.

    Args:
        response_pdf (requests.Response): Respuesta obtenida en modo Stream.
        enlacePDF (str): Nombre completo (con ruta) para registrar físicamente el PDF.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador: str, titulo: str, contenido: str, url_pdf: str) -> pd.DataFrame:
    """Elabora un DataFrame estructurado con los detalles particulares del documento hallado.

    Compila la información integrando la estampa temporal local.
    Adicionalmente, depura del todo `contenido` mediante el borrado de saltos y blancos nulos.

    Args:
        identificador (str): ID asignado o recuperado en el ciclo actual.
        titulo (str): Título principal del documento extraído en la propia Web.
        contenido (str): Todo el texto interior captado por el OCR o librería correspondiente.
        url_pdf (str): Enlace web directo fuente del activo.

    Returns:
        pd.DataFrame: DataFrame pandas formateado y listo para persistir en la base CSV.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Nombre_seccion": titulo,
        "Contenido_pdf": contenido,
        "Fecha_lectura": fecha_lectura,
        "Enlace_pdf": url_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

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

def verificar_carga(driver, selector, busqueda):
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

def scrapear_dias_completos() -> None:
    """Gestor principal del recorrido de la web de CADIME.

    Inicializa los controladores Web-Selenium de la estructura
    de boletines y explora artículo por artículo para guardar sus
    documentos internos y procesar la información respectiva como su 
    texto. Finalmente, compila los sub-esquemas de resultados en un CSV y
    descarga PDFs.
    
    Creates:
        Carpeta local `CADIME` y archivo `url_errores.txt`.
    """
    carpeta_adquisiciones =  os.path.join(script_dir, f"CADIME")

    ruta_archivo_errores = os.path.join(carpeta_adquisiciones, "url_errores")
    base_dir_csv = carpeta_adquisiciones

    carpetas = [base_dir_csv]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    numero_boletin = 1
    try:
        base_enlace = f"https://www.cadime.es/bta/bta.html?start=63"
        driver = iniciar_driver()
        driver.get(base_enlace)

        articulo = 0
        if verificar_carga(driver, By.CSS_SELECTOR, "div.com-content-category-blog.blog"):
            print("Dentro de la pagina")
            blog_inicial = driver.find_element(By.CSS_SELECTOR, "div.com-content-category-blog.blog")
            dos_contenidos = blog_inicial.find_elements(By.CSS_SELECTOR, "div.com-content-category-blog__items.blog-items")

            for contenido in dos_contenidos:
                decretos = contenido.find_elements(By.CSS_SELECTOR, "div.com-content-category-blog__item.blog-item")

                for cada in decretos:
                    a_tag = cada.find_element(By.CSS_SELECTOR, 'h2 a')
                    if a_tag:
                        enlace = a_tag.get_attribute('href')
                        titulo = a_tag.text.strip()

                        driver_decreto = iniciar_driver()
                        driver_decreto.get(enlace)

                        if verificar_carga(driver_decreto, By.CLASS_NAME, "col"):
                            articulo += 1
                            print("Dentro de la pagina")
                            entrando = driver_decreto.find_element(By.CLASS_NAME, "col")
                            pdf_a = entrando.find_element(By.CSS_SELECTOR, "div.com-content-article__body")
                            enlace_pdf = pdf_a.find_element(By.CSS_SELECTOR, 'a[href$=".pdf"]')
                            url_pdf = enlace_pdf.get_attribute('href')

                            identificador = f"Cadime_Pag_4_Art_{articulo}"
                            respuesta_pdf, encontrado_pdf = intentar_peticion(url_pdf, ruta_archivo_errores)
                            ruta_guardar_pdf = f"{carpeta_adquisiciones}\\{identificador}.pdf"
                            if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                texto_pdf_re, exito_re = extract_text_direct(ruta_guardar_pdf)
                                            
                                if exito_re:
                                    df_re = crear_df_temporal(identificador, titulo, texto_pdf_re, url_pdf)
                                    guardar_contenido_csv(df_re, base_dir_csv)
                                    print(f"Guardamos contenido del decreto -> {identificador}")
                                    time.sleep(0.5)
                                else:
                                    escribir_url_errores(ruta_archivo_errores, enlace_pdf)

                        driver_decreto.quit()

        driver.quit()
                            
    except Exception as e:
        print(f"Error inesperado en el boletin {numero_boletin}: {e}")


if __name__ == "__main__":
    scrapear_dias_completos()
