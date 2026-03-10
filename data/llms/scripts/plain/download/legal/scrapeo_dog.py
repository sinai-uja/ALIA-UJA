"""Recolector del Diario Oficial de Galicia (DOG).

Este script automatiza la extracción de resoluciones del DOG navegando hacia atrás en el
portal de la Xunta de Galicia mediante un motor Selenium Headless.
Navega por el calendario mensual del portal oficial, accede a sumarios de cada día y extrae
el texto HTML de los decretos (pre-2001 sin PDF, post-2001 con PDF directo).
Usa drivers efímeros por decreto para paralelizar y aislar fallos de carga.

Attributes:
    anio_scrappeo (int): Año base de inicio (Ej. 1979).
    calendario (dict): Formato referencial de días por mes.
    todas_columnas (set): Conjunto global para tracking de columnas dinámicas.
    script_dir (str): Directorio raíz del script.
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

anio_scrappeo = 1979
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

todas_columnas = set()
script_dir = os.path.dirname(os.path.abspath(__file__))

def iniciar_driver():
    """Genera un WebDriver Chrome sin GUI para automatización web.

    Note:
        La línea `--headless` está comentada en este script, por lo que el navegador
        puede abrirse de forma visible. Descomentarla para ejecución en servidor.

    Returns:
        webdriver.Chrome: Driver Chrome configurado.
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

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos de línea en cadenas de texto.

    Args:
        texto (str): Texto crudo a limpiar.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

def intentar_peticion(url_buscar, ruta_errores):
    """Ejecuta una petición GET protegida con reintentos ante caídas HTTP.

    Args:
        url_buscar (str): URL a consultar.
        ruta_errores (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta y bandera de éxito (1) o fallo (0).
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

def guardar_contenido(df, ruta, anio):
    """Anexa filas al CSV anual acumulativo.

    Args:
        df (pd.DataFrame): DataFrame con datos del decreto.
        ruta (str): Directorio destino.
        anio (int|str): Año para el nombre del CSV.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Guarda un PDF desde un stream HTTP.

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

def crear_df_temporal(enlace_decreto, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, contenido_texto, enlace_pdf, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos y texto del decreto DOG.

    Args:
        enlace_decreto (str): URL del decreto visitado.
        identificador (str): ID único del decreto.
        fecha_decreto (str): Fecha formateada `DD-MM-AAAA`.
        nombre_seccion (str): Sección del DOG (`dog-toc-nivel-1`).
        nombre_subseccion (str): Organismo emisor (`dog-toc-organismo`).
        contenido_texto (str): Texto extraído del elemento `story`.
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
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Seccion": nombre_seccion,
        "Subseccion": nombre_subseccion,
        "Contenido": contenido_texto,
        "Url_pdf": enlace_pdf,
        "Url_decreto": enlace_decreto,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x)) 

    return nuevo_df

def verificar_carga_inicio(driver, selector, busqueda):
    """Espera la carga del componente principal del calendario DOG.

    Args:
        driver (webdriver.Chrome): Driver activo.
        selector (By.*): Tipo de selector.
        busqueda (str): Valor del selector a esperar.

    Returns:
        bool: True si carga correctamente, False si agota reintentos.
    """
    intentos_maximos = 3  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((selector, busqueda)))
            return True
            
        except Exception as e:
            intento += 1
            print(f"Intento {intento}/{intentos_maximos}: Error: Reintentando...")

            if intento < intentos_maximos:
                print("Recargando la página...")
                driver.refresh()
                time.sleep(1)  

    print("Error: La página no se cargó después de varios intentos.")
    return False

def verificar_carga(driver, selector, busqueda):
    """Espera la carga de un elemento en la página del decreto.

    Args:
        driver (webdriver.Chrome): Driver activo.
        selector (By.*): Tipo de selector.
        busqueda (str): Valor del selector a esperar.

    Returns:
        bool: True si el elemento aparece, False si se agotan los reintentos.
    """
    intentos_maximos = 3  
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
    """Orquestador del scraping del DOG navegando mes a mes hacia atrás.

    Arranca en el portal de la Xunta, navega el calendario mensual y para cada día
    disponible abre un driver secundario. Distingue dos modos:
    - **Pre-2001**: extrae solo texto HTML desde el elemento `story`.
    - **Post-2001**: descarga el PDF vía enlace `dog-descargar` y también extrae texto HTML.
    Guarda un archivo TXT de estado por año y registra errores en `url_errores.txt`.
    """
    
    anio = 2000
    while int(anio) > 1985:  
        try: 
            base_anio = os.path.join(script_dir, f"{anio}")
            base_dir_pdfs = os.path.join(base_anio, "PDF")
            base_dir_csv = base_anio
            ruta_archivo_errores = os.path.join(base_anio, "url_errores")
            ruta_continuar =  os.path.join(base_anio, f"DOG.txt")

            carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

            for carpeta in carpetas:    # Crear las carpetas si no existen
                os.makedirs(carpeta, exist_ok=True)

            mes_leido = 1
            dia_leido = 1

            if not os.path.exists(ruta_continuar):
                with open(ruta_continuar, 'w', encoding='utf-8') as f:
                    f.write(f"{mes_leido},{dia_leido}")  #leemos el dia y el mes
                    print("Escribimos fecha...")
            else:
                with open(ruta_continuar, 'r', encoding='utf-8') as f:
                    mes_leido, dia_leido = map(int, f.read().strip().split(','))
                    print("Leemos fecha...")

            enlace_inicial = "https://www.xunta.gal/diario-oficial-galicia/portalPublicoHome.do?lang=es"
            driver = iniciar_driver()
            driver.get(enlace_inicial)
            if verificar_carga_inicio(driver, By.CLASS_NAME, 'table-condensed' ):
                div_decretos = driver.find_element(By.CLASS_NAME, 'table-condensed')
                dias = driver.find_elements(By.CSS_SELECTOR, 'td[data-action="selectDay"]')
                for dia_scrap in dias:
                    try:
                        try:
                            fecha = dia_scrap.get_attribute('data-day')
                            dia, mes, anio = fecha.split('/')
                            enlace = dia_scrap.find_element(By.TAG_NAME, 'a')
                            url_dia = enlace.get_attribute('url')
                        except:
                            print(f"No hay decreto en: {dia}/{mes}/{anio}")
                            time.sleep(1)
                            continue
                        print(f"Enlace para el DOG del {fecha}: {url_dia}")
                                
                        driver_dia = iniciar_driver()
                        url_dia = f"https://www.xunta.gal/diario-oficial-galicia/{url_dia}"
                        driver_dia.get(url_dia)
                        num_seccion = 0
                        num_decreto = 0

                        dia = int(dia)
                        mes = int(mes)
                        anio = int(anio)

                        if anio < 2001: #parte antigua sin pdfs
                            print("Procesamiento para parte antigua...")
                            if verificar_carga_inicio(driver_dia, By.CLASS_NAME, 'contidoDesplegado' ):
                                div_decretos = driver_dia.find_element(By.ID, 'fichaSeccion')
                                story = div_decretos.find_elements(By.CLASS_NAME, 'story')
                                story_real = story[1]
                                elementos = story_real.find_elements(By.XPATH, "./*")   
                                nombre_seccion_actual = ""
                                nombre_subseccion_actual = ""
                                for elemento in elementos:
                                    if elemento.tag_name == 'p':
                                        clase = elemento.get_attribute('class')  
                                        if clase == 'dog-toc-nivel-1':
                                            nombre_seccion_actual = elemento.text
                                        
                                        elif clase == 'dog-toc-organismo':
                                            nombre_subseccion_actual = elemento.text
                                            num_seccion += 1
                                            num_decreto = 0
                                    
                                    if elemento.tag_name == 'ul':
                                        li = elemento.find_element(By.CLASS_NAME, 'dog-toc-sumario')
                                        etiqueta = li.find_element(By.TAG_NAME, 'a')
                                        enlace = etiqueta.get_attribute('href')
                                        driver_decretos = iniciar_driver()
                                        num_decreto += 1
                                        fecha_decreto = f"{dia}-{mes}-{anio}"
                                        identificador = f"DOG-{dia}-{mes}-{anio}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                        driver_decretos.get(enlace)

                                        if verificar_carga(driver_decretos, By.CLASS_NAME, 'story'):
                                            print("Dentro del decreto")
                                            contenido_texto = driver_decretos.find_elements(By.CLASS_NAME, 'story')
            
                                            texto_completo = ""
                                            for elemento in contenido_texto:
                                                try:
                                                    parrafos = elemento.find_elements(By.TAG_NAME, "p")  
                                                    texto_completo = "\n".join([p.text.strip() for p in parrafos])
                                                                
                                                    df = crear_df_temporal(enlace, identificador, fecha_decreto, nombre_seccion_actual, nombre_subseccion_actual, texto_completo, None, None)
                                                    guardar_contenido(df, base_dir_csv, anio)
                                                    print(f"Guardamos en el csv: {identificador}")
                                                except:
                                                    print("No se ha guardado el decreto")
                                            print("Contenido recogido del html...")
                                            driver_decretos.quit()
                                            time.sleep(0.5)
                                        else:
                                            escribir_url_errores(ruta_archivo_errores, url_dia)

                        else: #parte nueva con pdfs
                            print("Procesamiento para parte nueva...")
                            if verificar_carga_inicio(driver_dia, By.CLASS_NAME, 'contidoDesplegado' ):
                                div_decretos = driver_dia.find_element(By.ID, 'fichaSeccion')
                                story = div_decretos.find_element(By.CLASS_NAME, 'story')
                                elementos = story.find_elements(By.XPATH, "./*")   # Esto selecciona solo los hijos directos de story
                                nombre_seccion_actual = ""
                                nombre_subseccion_actual = ""
                                enlace = ""
                                identificador = ""
                                fecha_decreto = "" 
                                texto_completo = ""

                                for elemento in elementos:
                                    if elemento.tag_name == 'p':
                                        clase = elemento.get_attribute('class')  
                                        if clase == 'dog-toc-nivel-1':
                                            nombre_seccion_actual = elemento.text
                                        
                                        elif clase == 'dog-toc-organismo':
                                            nombre_subseccion_actual = elemento.text
                                            num_seccion += 1
                                            num_decreto = 0
                                        
                                        elif clase == 'dog-descargar':
                                            etiqueta = elemento.find_element(By.TAG_NAME, 'a')
                                            enlace_pdf = etiqueta.get_attribute('href')
                                            print(f"El enlace PDF es: {enlace_pdf}")
                                            ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"
                                            if not os.path.exists(ruta_guardar_pdf):
                                                intento = 0
                                                conseguido = False
                                                while intento < 5 and not conseguido:
                                                    response = requests.get(enlace_pdf, stream=True)
                                                    if response.status_code == 200:
                                                        conseguido = True
                                                        descargar_pdf(response,ruta_guardar_pdf)
                                                    else:
                                                        time.sleep(1)
                                                        print("Reintentamos descargar el pdf")

                                                df = crear_df_temporal(enlace, identificador, fecha_decreto, nombre_seccion_actual, nombre_subseccion_actual, texto_completo, enlace_pdf, ruta_guardar_pdf)
                                                guardar_contenido(df, base_dir_csv, anio)
                                                print(f"Guardamos en el csv: {identificador}")


                                    if elemento.tag_name == 'ul':
                                        li = elemento.find_element(By.CLASS_NAME, 'dog-toc-sumario')
                                        etiqueta = li.find_element(By.TAG_NAME, 'a')
                                        enlace = etiqueta.get_attribute('href')
                                        driver_decretos = iniciar_driver()
                                        num_decreto += 1
                                        fecha_decreto = f"{dia}-{mes}-{anio}"
                                        identificador = f"DOG-{dia}-{mes}-{anio}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                        driver_decretos.get(enlace)

                                        if verificar_carga(driver_decretos, By.CLASS_NAME, 'story'):
                                            print("Dentro del decreto")
                                            contenido_texto = driver_decretos.find_elements(By.CLASS_NAME, 'story')
            
                                            texto_completo = ""
                                            for elemento in contenido_texto:
                                                try:
                                                    parrafos = elemento.find_elements(By.TAG_NAME, "p")  
                                                    texto_completo = "\n".join([p.text.strip() for p in parrafos])
                                                                
                                                except:
                                                    print("No se ha guardado el decreto")

                                            print("Contenido recogido del html...")
                                            driver_decretos.quit()
                                            time.sleep(0.5)
                                        else:
                                            escribir_url_errores(ruta_archivo_errores, url_dia)

                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                            print(f"Guardamos el fichero en el boletin: {mes}-{dia}")
                            f.write(f"{mes}, {dia}")

                        driver_dia.quit()
                        time.sleep(1)
                    except:
                        print("Ha ocurrido una excepción pasamos al dia siguiente")

                try:
                    prev_button = driver.find_element(By.CLASS_NAME, 'prev')
                    print("Clickeamos al mes anterior...")
                    prev_button.click()
                    driver.quit()
                    print("Continuamos")
                    time.sleep(2)  
                except Exception as e:
                    print("No se pudo navegar más atrás.")

        except Exception as e:
            print(f"Error inesperado: {str(e)}")
            with open(ruta_archivo_errores, "a", encoding="utf-8") as f:
                f.write(f"Error en el inicio: {str(e)}\n")
            driver.refresh()

        except ChunkedEncodingError as e:
            print(f"Error en la transferencia de datos: {e}")
            
        except requests.exceptions.RequestException as e:
            print(f"Intento rechazado")

if __name__ == "__main__":
    scrapear_dias_completos()

