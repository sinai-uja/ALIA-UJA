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
import zipfile
import random

import signal
import sys

interrumpido = False

def handler_signal(sig, frame):
    global interrumpido
    print("⛔ Proceso interrumpido por el usuario. Cerrando driver...")
    interrumpido = True

signal.signal(signal.SIGINT, handler_signal)


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
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, ruta_errores, min_chars=50):
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
        with open(ruta_errores, 'w', encoding='utf-8') as f:
            f.write(f"Error en el pdf: {ruta_errores}")
        return "", False

def escribir_url_errores(archivo_errores, url_dia):
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
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

def guardar_contenido_csv(df, ruta):
    if not df.empty:
        archivo_csv = f"{ruta}/cordis_europa.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, titulo, idioma, resumen, contenido, enlace):
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "language": idioma,
        "title": titulo,
        "summary": resumen, 
        "content": contenido,
        "url": enlace,
        "read_date": fecha_lectura
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

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

def scrapear_dias_completos():
    carpeta_adquisiciones =  os.path.join(script_dir, f"cordis")
    num_pagina = 0
    ruta_archivo_errores = os.path.join(carpeta_adquisiciones, "url_errores")
    base_dir_csv = carpeta_adquisiciones
    ruta_continuar = os.path.join(script_dir, f"continuar_cordis.txt")
    ruta_csv = f"{base_dir_csv}/cordis_europa.csv"
    carpetas = [base_dir_csv]

    numero_pagina_leido = 1

    """ for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    if not os.path.exists(ruta_continuar):
        print("No existe creamos")
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{numero_pagina_leido}")
    else:
        with open(ruta_continuar, 'w') as f:
            numero_pagina_leido = int(f.read().strip())"""

    numero_pagina = numero_pagina_leido

    for pagina in range(7178, 142829):
        if interrumpido:
            break
        try:
            enlace_pagina_filtrado = f"""https://cordis.europa.eu/search/es?q=language%3D%27de%27%2C%27en%27%2C%27es%27%2C%27fr%27%2C%27it%27&p={pagina}&num=10&srt=Relevance:decreasing&archived=true"""
            print(f"Entramos a: {enlace_pagina_filtrado}")
            driver = iniciar_driver()
            driver.get(enlace_pagina_filtrado)
            num_pagina += 1
            wait = WebDriverWait(driver, 15)
            if verificar_carga(driver, By.CLASS_NAME, "col-xl-9"):
                cabecera_pagina = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.cordis-search-results.t-margin-top-25"))
                )
                enlaces_inves = cabecera_pagina.find_elements(By.CSS_SELECTOR, "a.c-card-search__title.ng-star-inserted")

                print(f"Encontradas {len(enlaces_inves)} noticias")
                contador = 0
                for enlace in enlaces_inves:
                    try:
                        contador += 1
                        enlace_href = enlace.get_attribute('href')
                        viajar = f"{enlace_href}"
                        print(viajar)
                        driver_decreto = iniciar_driver()
                        driver_decreto.get(viajar)

                        if verificar_carga(driver_decreto, By.CLASS_NAME, "c-header-project__title"):
                            print(f"Estamos dentro de la pagina del decreto")
                            identificador = f"Cordis_Page_{pagina}_Notice_{contador}_Language_EN"


                            # Extracción de datos
                            titulo = ""
                            resumen = ""
                            contenido = ""
                            url_actual = viajar

                            print("Pasamos al contenido")
                            try:
                                titulo = driver_decreto.find_element(By.CLASS_NAME, "c-header-project__title").text.strip()
                            except:
                                print("No se ha encontrado el título.")
                                pass
                            try:
                                contenido = driver_decreto.find_element(By.CLASS_NAME, "c-article__text").text.strip()
                            except:
                                print("No se ha encontrado el contenido.")
                                pass
                            
                            enlace_xml = ""
                            try:
                                # Busca el enlace al XML
                                xml_link_element = driver_decreto.find_element(By.CSS_SELECTOR, "li.c-article__download-xml a")
                                enlace_xml = xml_link_element.get_attribute("href")

                                # Si es relativo, añade el dominio base
                                if enlace_xml.startswith("/"):
                                    base_url = "https://cordis.europa.eu"  # Ajusta si es distinto
                                    enlace_xml = base_url + enlace_xml

                                print("Enlace al XML:", enlace_xml)

                            except Exception as e:
                                enlace_xml = ""
                                print("No se encontró enlace al XML:", e)

                            contenido_xml = ""
                            try:
                                # Viajamos al XML con requests
                                response = requests.get(enlace_xml)
                                response.raise_for_status()  # lanza error si status != 200

                                contenido_xml = response.text  # Aquí tienes el contenido en string

                                print("Contenido del XML:")
                                print(contenido_xml[:500])  # solo mostramos un fragmento
                            except Exception as e:
                                print("Error al descargar o leer el XML:", e)


                            if titulo:
                                print(f"Guardamos noticia: {titulo[:60]}...")
                                df = crear_df_temporal(identificador, titulo, "EN", resumen, contenido, url_actual)
                                guardar_contenido_csv(df, base_dir_csv)

                            # Espera y retroceso
                            time.sleep(random.uniform(3.0, 6.0))
                            driver_decreto.quit()

                    except Exception as e:
                        print(f"Error en noticia {contador}: {e}")
            driver.quit()

        except Exception as e:
            print(f"Hemos tenido una excepción en la página {pagina}: {e}")
            driver.quit()

    parquet_path = f"{base_dir_csv}/cordis.parquet"
    try:
        if os.path.exists(ruta_csv):
            df = pd.read_csv(ruta_csv, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV convertido a Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error al convertir CSV a Parquet para el año cadime_biomedicina {e}")

    zip_path = os.path.join(script_dir, f"cordis.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
                zipf.write(ruta_csv, os.path.basename(ruta_csv))
            print(f"✅ Archivo ZIP creado: {zip_path}")
    except Exception as e:
        print(f"❌ Error al crear el archivo ZIP para el año cadime_biomedicina: {e}")

if __name__ == "__main__":
    scrapear_dias_completos()

