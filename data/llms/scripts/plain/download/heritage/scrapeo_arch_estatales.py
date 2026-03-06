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
        archivo_csv = f"{ruta}/Archivos_estatales.csv"
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

def crear_df_temporal(identificador, anio_actual_, titulo, contenido_texto, enlace_html):
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Anio_decreto": anio_actual_,
        "Nombre_seccion": titulo,
        "Contenido": contenido_texto,
        "Url_html": enlace_html,
        "Fecha_lectura": fecha_lectura
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
    carpeta_adquisiciones =  os.path.join(script_dir, f"Archivos_Estatales")

    ruta_archivo_errores = os.path.join(carpeta_adquisiciones, "url_errores")
    base_dir_csv = carpeta_adquisiciones

    carpetas = [base_dir_csv]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    numero_boletin = 1
    try:
        base_enlace = f"https://pares.cultura.gob.es/archivos-estatales.html"
        driver = iniciar_driver()
        driver.get(base_enlace)

        if verificar_carga(driver, By.ID, "contenedor"):
            print("Dentro de la pagina")
            elementos = driver.find_element(By.ID, "contenedor")
            div_contenido = elementos.find_element(By.ID, "contenido")
            secciones_grandes = div_contenido.find_elements(By.CLASS_NAME, "cblq")

            anio_actual = 2023
            for seccion_grande in secciones_grandes:
                cte = seccion_grande.find_element(By.CLASS_NAME, "cte")
                h3 = cte.find_element(By.CLASS_NAME, "subrayado")
                a = h3.find_element(By.TAG_NAME, "a")
                titulo_actual = a.text
                print(titulo_actual)

                todos_a = cte.find_elements(By.TAG_NAME, "a")

                for aes in todos_a:
                    try:
                        texto_censo = aes.text
                        print(f"Texto: {texto_censo}")

                        if texto_censo == "Censo Guía":
                            print("Si es, viajamos a scrapear")
                            driver_viajar = iniciar_driver()
                            enlace_contenido = aes.get_attribute('href')
                            driver_viajar.get(enlace_contenido)
                            if verificar_carga(driver_viajar, By.ID, "contenido"):
                                print("Dentro de la pagina de leer")
                                contenido = driver_viajar.find_element(By.ID, "contenido")
                                div_2 = contenido.find_element(By.ID, "div2")
                                direcciones = div_2.find_element(By.ID, "direcciones2")
                                margenes_derecha = direcciones.find_elements(By.CLASS_NAME, "margenderecha")

                                todo_el_contexto = ""
                                for margen in margenes_derecha:
                                    todos_p = margen.find_elements(By.TAG_NAME, "p")
                                    for p in todos_p:
                                        todo_el_contexto += p.text + " "

                                identificador = "_".join(titulo_actual.split())

                                df = crear_df_temporal(identificador, anio_actual, titulo_actual, todo_el_contexto, enlace_contenido)
                                guardar_contenido_csv(df, base_dir_csv)
                                time.sleep(1)

                            driver_viajar.quit()

                    except:
                        print("No es el li para el enlace pasamos al siguiente...")

        driver.quit()
                            
    except Exception as e:
        print(f"Error inesperado en el boletin {numero_boletin}: {e}")


if __name__ == "__main__":
    scrapear_dias_completos()

