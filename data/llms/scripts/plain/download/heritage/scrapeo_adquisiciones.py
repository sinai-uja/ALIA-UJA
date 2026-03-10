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
from selenium.webdriver.support.expected_conditions import presence_of_element_located, visibility_of_element_located
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
        archivo_csv = f"{ruta}/adquisiciones.csv"
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

def crear_df_temporal(identificador, anio_, titulo_noti, descripcion, contenido, enlace_noti):
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "year": anio_,
        "section": titulo_noti,
        "description": descripcion,
        "content": contenido,
        "url": enlace_noti,
        "read_date": fecha_lectura
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

def scrapear_dias_completos():
    driver = iniciar_driver()
    wait = WebDriverWait(driver, 10)

    carpeta_adquisiciones = os.path.join(os.path.dirname(__file__), "Adquisiciones")
    ruta_archivo_errores = os.path.join(carpeta_adquisiciones, "url_errores")
    base_dir_csv = carpeta_adquisiciones
    ruta_csv = os.path.join(base_dir_csv, "Adquisiciones.csv")

    os.makedirs(base_dir_csv, exist_ok=True)
    print("Iniciamos scrapeo")

    base_enlace = "https://www.cultura.gob.es/cultura/archivos/informacion-general/adquisiciones-donaciones/portada-adquisiciones-donaciones.html"
    driver.get(base_enlace)

    if verificar_carga(driver, By.CSS_SELECTOR, "div.tabs.dsp-c"):
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.tabs.dsp-c")))
            anios = driver.find_element(By.CSS_SELECTOR, "div.tabs.dsp-c")
            todos_anios = anios.find_element(By.CLASS_NAME, "dsp-d")
            todos = todos_anios.find_elements(By.TAG_NAME, "li")
            print(f"Elementos anios: {len(todos)}")
            enlaces_navegar = []

            for li in todos:
                a_tag = li.find_element(By.TAG_NAME, "a")
                a_tag = li.find_element(By.TAG_NAME, "a")
                contenido = driver.execute_script("return arguments[0].innerText;", a_tag).strip()
                if contenido != "Portada" and contenido != "Años Anteriores":
                    print(f"Texto visible via JS: '{contenido}'")
                    enlaces_navegar.append((contenido, a_tag.get_attribute("href")))

            for anio_, enlace in enlaces_navegar:
                drver_dentro = iniciar_driver()
                drver_dentro.get(enlace)
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "tabs-contenido")))
                seccion_actual = ""
                num_seccion = -1
                num_noti = 0

                elementos = drver_dentro.find_elements(By.CSS_SELECTOR, "div.tabs-contenido > *")
                for elemento in elementos:
                    clases = elemento.get_attribute("class").split()

                    if "cim" in clases and "ancho" in clases:
                        try:
                            img = elemento.find_element(By.TAG_NAME, "img")
                            seccion_actual = img.get_attribute("alt").strip()
                            print(f"Sección encontrada (desde alt): {seccion_actual}")
                            num_seccion += 1
                            num_noti = 0
                        except:
                            print("No se encontró imagen o atributo alt.")

                    if "cle" in clases:
                        noticias = elemento.find_elements(By.CLASS_NAME, "enlace")
                        for noti in noticias:
                            num_noti += 1
                            identificador = f"Adquisicion_{anio_}_seccion_{num_seccion}_Archivo_{num_noti}"
                            print(identificador)
                            try:
                                enlace_noti = noti.find_element(By.CSS_SELECTOR, "p.titulo > a")
                                url_noti = enlace_noti.get_attribute("href")
                                titulo_noti = enlace_noti.text.strip()
                                descripcion = noti.find_element(By.CLASS_NAME, "descripcion").text.strip()
                                print(f"Enlace: {url_noti}")

                                driver_adq = iniciar_driver()
                                driver_adq.get(url_noti)  # Abre directamente la URL

                                div_cte = driver_adq.find_element(By.ID, "contenido")
                                contenido = div_cte.text
                                driver_adq.quit()

                                df = crear_df_temporal(identificador, anio_, titulo_noti, descripcion, contenido, url_noti)
                                guardar_contenido_csv(df, base_dir_csv)
                                time.sleep(1)
                            except Exception as e:
                                print(f"Error en noticia {num_noti}: {e}")

                drver_dentro.quit()
        except Exception as e:
            print(f"Error inesperado: {e}")
        finally:
            driver.quit()

    # CSV -> Parquet
    parquet_path = os.path.join(base_dir_csv, "adquisiciones.parquet")
    try:
        if os.path.exists(ruta_csv):
            df = pd.read_csv(ruta_csv, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV convertido a Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error al convertir CSV a Parquet: {e}")

    # Crear ZIP
    try:
        with zipfile.ZipFile(os.path.join(os.path.dirname(__file__), "adquisiciones.zip"), 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
                zipf.write(ruta_csv, os.path.basename(ruta_csv))
            print("✅ Archivo ZIP creado")
    except Exception as e:
        print(f"❌ Error al crear ZIP: {e}")

if __name__ == "__main__":
    scrapear_dias_completos()

