"""Scraper de noticias e informes de la web institucional de FAISEM.

Este módulo implementa una solución de extracción basada en Selenium Webdriver
y BeautifulSoup para recorrer las noticias de la Fundación Pública Andaluza para 
la Integración Social de Personas con Enfermedad Mental (FAISEM). Extrae el texto
descriptivo, metadatos y (si aplica) descarga documentos anexos procesando 
la paginación del portal CMS.

Example:
    Ejecución del pipeline completo::

        python scrapeo_biomedico_faisem.py

    Descargará secuencialmente páginas de noticias (hasta num 220 o agotar)
    guardando el contenido crudo en un dataset CSV `FAISEM/cadime_biomedicina.csv`.

Note:
    Estructura sujeta a las maquetaciones del CMS (Divi Builder) de `faisem.es`.
    Precisa dependencias como `fitz` (PyMuPDF) en caso de que existan transiciones 
    directas a pdfs, y `webdriver_manager` para Chrome autogestionado.
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
    """Inicializa la sesión de Selenium ChromeDriver de forma silenciosa.

    Agrega múltiples extensiones de optimización a Chromium como 
    no-sandbox, deshabilitación de shm-usage y la omisión de logueo.

    Returns:
        webdriver.Chrome: Driver configurado activo.
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
    """Borra múltiples espacios en blanco y estandariza las separaciones.

    Args:
        texto (str): Texto desestructurado de entrada.

    Returns:
        str: Texto procesado con espaciado único lineal.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path: str, ruta_errores: str, min_chars: int = 50) -> tuple:
    """Extrae todo el texto contenido de un documento PDF proporcionado.

    Hace uso de recolección de basura forzosa (`gc.collect()`) para 
    alivianar el pase de largos ficheros sobre PyMuPDF.

    Args:
        pdf_path (str): Ubicación en disco del archivo PDF.
        ruta_errores (str): Ubicación del archivo log txt en caso de fallo.
        min_chars (int, optional): Límite de control para determinar documento válido. Defaults to 50.

    Returns:
        tuple: (texto extraído, validez de la operación) (str, bool).
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
    """Vuelca una URL no encontrada o errónea en un archivo de log permanente.

    Args:
        archivo_errores (str): Archivo destino.
        url_dia (str): Cadena de la URL conflictiva.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar: str, ruta_errores: str) -> tuple:
    """Itera solicitudes mediante Requests manejando latencias de servidor.

    Intenta conectar a la URL un máximo de 5 veces en caso de errores transitorios
    (no controlados como los 404/200 directamente resueltos).
    Captura y maneja los errores `ChunkedEncodingError`.

    Args:
        url_buscar (str): Dirección web foco del GET.
        ruta_errores (str): Archivo para dar parte de deficiencia irrecuperable de conectividad.

    Returns:
        tuple: Objeto requests.Response | None, código entero de status (0 o 1).
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
    """Persiste al final (append) un dataframe pandas con información hacia un CSV local.

    Bajo la nominación errada pero legada de `cadime_biomedicina.csv`
    agrega sin sobrescribir salvo si precisa instanciar los header columns primeramente.

    Args:
        df (pd.DataFrame): Dataframe unificado y saneado listado.
        ruta (str): Directorio matriz.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/cadime_biomedicina.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf: requests.Response, enlacePDF: str) -> None:
    """Acumula la carga (chunk) del Response hacia binario puro sin romper memoria.

    Args:
        response_pdf (requests.Response): Solicitud finalizada en positivo (stream=True).
        enlacePDF (str): Nombre o ruta final adoptada.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador: str, titulo: str, resumen: str, contenido: str, enlace: str) -> pd.DataFrame:
    """Compone la tabla estructural por artículo o caso de noticia encontrado.

    Incluye el ID auto-gestionado, la metadata, un bloque de resumen 
    (si lo hubiese) y el texto íntegro además de la marca temporal local.

    Args:
        identificador (str): ID relacional de extracción de la corrida.
        titulo (str): Título oficial visible por el Webdriver.
        resumen (str): Párrafo de entrada o abstract corto.
        contenido (str): Todo el cuerpo concatenado recabado.
        enlace (str): La URL que origina esta información directa a la nota.

    Returns:
        pd.DataFrame: DataFrame pandas configurado y curado.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Nombre_seccion": titulo,
        "Resumen": resumen, 
        "Contenido_pdf": contenido,
        "Url_contenido": enlace,
        "Fecha_lectura": fecha_lectura
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df


def verificar_carga(driver: webdriver.Chrome, selector: str, busqueda: str) -> bool:
    """Implementa esperas dinámicas para un elemento web con resguardo de refresh.

    Args:
        driver (webdriver.Chrome): Ventana en curso del navegador.
        selector (str): Método orientador (Ej. `By.CSS_SELECTOR`).
        busqueda (str): Query selector a vigilar.

    Returns:
        bool: Éxito o Fracaso al encontrar dom content.
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

def scrapear_dias_completos() -> None:
    """Ejecuta toda la lógica orquestada por la araña web de FAISEM.

    Configura carpetas iniciales y navega la base (https://faisem.es/category/noticias/)
    saltando dinámicamente el paginador inferido hasta un límite prudencial de `Max_pages=220`.
    Concreta extracción para cada recuadro (post), y tras un nuevo enlace a detalles entra
    para raspar cuerpo y meta de la propia noticia.
    """
    carpeta_adquisiciones =  os.path.join(script_dir, f"FAISEM")

    ruta_archivo_errores = os.path.join(carpeta_adquisiciones, "url_errores")
    base_dir_csv = carpeta_adquisiciones

    carpetas = [base_dir_csv]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    print("Iniciamos scrapeo")

    numero_boletin = 1
    try:
        pagina = 0
        base_enlace = f"https://faisem.es/category/noticias/"
        siguiente_enlace = base_enlace

        while pagina <= 220:
            pagina += 1
            articulo = 0

            driver = iniciar_driver()
            driver.get(siguiente_enlace)

            if verificar_carga(driver, By.CSS_SELECTOR, "div.et_pb_section.et_pb_section_0_tb_body.et_section_regular"):
                print("Dentro de la pagina")
                blog_inicial = driver.find_element(By.CSS_SELECTOR, "div.et_pb_section.et_pb_section_0_tb_body.et_section_regular")

                los_contenidos = blog_inicial.find_element(By.CLASS_NAME, "et_pb_ajax_pagination_container")
                todos_articulos = los_contenidos.find_elements(By.TAG_NAME, "article")
                print("Tenemos todos los articulos de la página")


                """                    decretos = articulo_elemento.find_elements(By.CSS_SELECTOR, "div.com-content-category-blog__item.blog-item")

                    print("Pasamos a leer cada noticia...")
                    for cada in decretos:"""
                

                for articulo_elemento in todos_articulos: 
                    titulo_et = articulo_elemento.find_element(By.TAG_NAME, 'h2')
                    etiqueta = titulo_et.find_element(By.TAG_NAME, 'a')
                    titulo = etiqueta.text  
                    enlace_noticia = etiqueta.get_attribute('href')

                    div_resumen = articulo_elemento.find_element(By.CLASS_NAME, "post-content-inner")
                    resumen = div_resumen.find_element(By.TAG_NAME, "p").text 

                    driver_noticia = iniciar_driver()
                    driver_noticia.get(enlace_noticia)
                    print(f"Viajamos a:{enlace_noticia}")

                    if verificar_carga(driver_noticia, By.CSS_SELECTOR, "div.et_pb_row.et_pb_row_0"):
                        print("Dentro de la noticia")
                        articulo += 1
                        identificador = f"Pagina_{pagina}_Noticia_{articulo}"

                        dondelosp = driver_noticia.find_element(By.CLASS_NAME, "et_pb_text_inner")
                        p = dondelosp.find_elements(By.TAG_NAME, "p")

                        contenido_texto_noticia = " ".join([parrafo.text for parrafo in p]) 

                        df = crear_df_temporal(identificador, titulo, resumen, contenido_texto_noticia, enlace_noticia)
                        guardar_contenido_csv(df, base_dir_csv)

                        driver_noticia.quit()
                    else:
                        escribir_url_errores(ruta_archivo_errores, enlace_noticia)

            try:
                barra_navega = driver.find_element(By.CLASS_NAME, "wp-pagenavi")
                siguiente_enlace = barra_navega.find_element(By.CLASS_NAME, "nextpostslink").get_attribute('href')
            except:
                print("No se encontró el enlace a la siguiente página. Deteniendo scraping.")
                break

            driver.quit()
                                    
    except Exception as e:
        print(f"Error inesperado en el boletin {numero_boletin}: {e}")


if __name__ == "__main__":
    scrapear_dias_completos()
