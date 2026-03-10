"""Recolector del Boletín Oficial de la Ciudad de Ceuta (BOCCE).

Este módulo facilita la descarga completa de la hemeroteca del BOCCE.
Navega a través de su arquitectura de directorios anuales/mensuales utilizando
tanto 'requests' básico para directorios como 'Selenium' (Chromedriver)
para renderizar y extraer contenido donde los elementos DOM son dinámicos
(especialmente los enlaces directos a PDF por día).

Attributes:
    anio_scrappeo (int): El año inicial predeterminado para el proceso.
    script_dir (str): Directorio raíz del script usado para trazar paths absolutos.
    calendario (dict): Formato referencial estándar sobre meses.
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
    """Declara y configura una instancia de Chrome Headless optimizada.

    Integra opciones para suprimir logs, anular Sandbox y desactivar la
    GPU con el objetivo de maximizar su eficacia en background en entornos Docker
    o servidores limpios.

    Returns:
        webdriver.Chrome: Driver configurado y preparado para navegación.
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

def limpiar_texto(texto):
    """Remueve espacios consecutivos duplicados de un texto bruto.

    Args:
        texto (str): La secuencia de entrada original.

    Returns:
        str: El texto depurado.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Apila internamente un registro con la URL que provocó fallo.

    Args:
        archivo_errores (str): Destino del archivo sin sufijo temporal (.txt implícito).
        url_dia (str): Enlace fallido.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Bucle iterativo con timeout y reintentos ante fallos de respuesta red.

    Captura fallos críticos como ChunkedEncodingError o Timeout puro, intentando
    repetir hasta 5 veces la petición HTTP antes de dar el enlace por deficiente
    y comunicarlo al sistema de registro de errores.

    Args:
        url_buscar (str): Path HTTP destino.
        ruta_errores (str): Path directo del apuntador de errores.

    Returns:
        tuple[requests.models.Response|None, int]: Response resultante y
            un booleano (1 o 0) de comprobación.
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

def guardar_contenido_csv(df, ruta, anio,  boletin, seccion, decreto):
    """Inyecta un DataFrame pandas dentro del CSV compilatorio del año asignado.

    Agrega las filas, incorporando automáticamente encabezados si el archivo
    no existía previamente.

    Args:
        df (pd.DataFrame): DataFrame con toda la metadata del edicto.
        ruta (str): Directorio del CSV de destino final.
        anio (int|str): Año correspondiente al fichero.
        boletin (int|str): Índice o número del boletín procesado (debug).
        seccion (int|str): Identificador de sección procesada (debug).
        decreto (int|str): Índice decreciente del mandato (debug).
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print(f"Guardamos contenido del decreto -> Boletin-{boletin}-Secc-{seccion}-Dec-{decreto}")

def descargar_pdf(response_pdf, enlacePDF):
    """Efectúa la descarga serial en formato chunk (paquete dividido) de un PDF.

    Args:
        response_pdf (requests.models.Response): Instancia base conteníendo el body.
        enlacePDF (str): Nombre total o ruta de inserción donde volcar el PDF.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion,subsubseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Estructura e instancía los bloques informativos de origen en formato compatible DataFrame.

    Integra todos los campos junto a la hora y fecha del scraper (Fecha_lectura). Todos
    los atributos de origen literario son expugnados de saltos de línea y formateos basura.

    Args:
        enlace_html (str): Link al artículo original detallado.
        identificador (str): ID inventado general interno.
        fecha_decreto (str): Datación oficial de la emisión.
        seccion (str): Categoría grupal I en el boletín.
        subseccion (str): Categoría grupal II en el boletín.
        subsubseccion (str): Categoría inferior.
        contenido_text (str): Texto si fuera recuperado vía HTML/texto.
        enlace_pdf (str): Referencia web al PDF incrustado.
        ruta_guardar_pdf (str): Referencia final local del archivo PDF.

    Returns:
        pd.DataFrame: Un set de series ordenadas limpias con las métricas dadas.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Título": seccion,
        "Subtítulo": subseccion,
        "Subsubtitulo": subsubseccion,
        "Contenido": contenido_text,
        "Url_pdf": enlace_pdf,
        "Url_html": enlace_html,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def verificar_carga(driver, selector, busqueda):
    """Retenedor persistente para componentes condicionales renderizados por React/Angular.

    Se asegura mediante repeticiones y reinicio de pantalla (refresh) de la presencia 
    obligada de un Selector antes de proseguir la interpretación de etiquetas HTML hijas.

    Args:
        driver (webdriver.Chrome): Motor activo evaluando la UI.
        selector (By): Mecanismo de selección oficial de Selenium (By.ID...).
        busqueda (str): Query o patrón usado por el selector.

    Returns:
        bool: Éxito (True) o fracaso total (False) de la aparición del bloque.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((selector, busqueda)))
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
    """Bucle matriz del flujo operativo para descarga integra autonómica del BOCCE.

    Punto de arranque que inspecciona el catálogo retroactivo del panel de Ceuta.
    Desciende jerárquicamente: Años en matriz general -> Meses -> Archivos concretos.
    Ante la complejidad javascript de la página de los decretos diarios, levanta
    una instancia Selenium Headless por cada mes, extrae los HREF de cada tarjeta
    y lanza un 'requests' convencional para acelerar sustancialmente la finalización del PDF.
    Implementa un registro .txt de backup contra desconexiones sorpresas para
    restauración de estado de bucles.
    """
    ruta_continuar =  os.path.join(script_dir, f"continuar_por.txt")
    ruta_archivo_errores = os.path.join(script_dir, "url_errores")

    numero_boletin = 1
    anio = 2000

    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{anio},{numero_boletin}") 
            print("Escribimos el mes...")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            anio, numero_boletin = map(int, f.read().strip().split(','))
            print("Leemos el mes...")

    print(f"EMPEZAMOS POR EL DIA -> Boletin-{numero_boletin}-{anio}")
    try:
        enlace_principal = "https://www.ceuta.es/ceuta/bocce"
        respuesta, encontrado = intentar_peticion(enlace_principal, ruta_archivo_errores)

        if encontrado == 1 and respuesta and respuesta.status_code == 200:
            print("Estamos en la pagina principal del BOCCE")
            soup = BeautifulSoup(respuesta.text, 'html.parser')
            tabla = soup.find("table", class_="jd_cat_subheader")
            
            siguiente_anio = tabla.find_next_sibling()

            while int(anio) > 1980:
                enlace = siguiente_anio.find("a")['href']
                enlace_anio = f"https://www.ceuta.es{enlace}"

                respuesta_anio, encontrado_anio = intentar_peticion(enlace_anio, ruta_archivo_errores)
                if encontrado_anio == 1 and respuesta_anio and respuesta_anio.status_code == 200:
                    soup_anio = BeautifulSoup(respuesta_anio.text, 'html.parser')
                    anio_tabla = soup_anio.find("table", class_="jd_cat_subheader")
                    tr = anio_tabla.find("td").get_text()
                    anio = tr.split(":")[-1].strip()
                    print(f"Entramos al anio: {anio}")

                    base_anio = os.path.join(script_dir, f"{anio}")
                    base_dir_pdfs = os.path.join(base_anio, "PDF")
                    base_dir_csv = base_anio 
                    carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                    for carpeta in carpetas:    # Crear las carpetas si no existen
                        os.makedirs(carpeta, exist_ok=True)
                    
                    print(f"Carpetas del anio {anio} creadas...")

                    siguiente_mes = anio_tabla.find_next_sibling()

                    while siguiente_mes:
                        print("Pasamos al siguiente mes")
                        if siguiente_mes.name == "div":
                            enlace = siguiente_mes.find("a")['href']
                            enlace_mes = f"https://www.ceuta.es{enlace}"
                            driver = iniciar_driver()
                            driver.get(enlace_mes)

                            if verificar_carga(driver, By.CLASS_NAME, "ja-content-main"):
                                print("Estamos dentro del mes")
                                etiqueta_anterior = driver.find_element(By.CLASS_NAME, "ja-content-main")
                                formulario_dias = etiqueta_anterior.find_element(By.TAG_NAME, "form")
                                decretos = formulario_dias.find_elements(By.XPATH, '//div[contains(@style, "padding:3px; background-color:#F5F5F5; position:relative;")]')
                                for decreto in decretos:
                                    identificador = f"BOCCE-{anio}-Boletin-{numero_boletin}"
                                    enlace_pdf = decreto.find_element(By.TAG_NAME, "a").get_attribute('href')
                                    print(f"Enlace al pdf: {enlace_pdf}")
                                    respuesta_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                    if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                        ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"
                                        descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                        time.sleep(0.5)
                                    numero_boletin += 1

                                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                        print(f"Guardamos el fichero en el boletin: {anio}-{numero_boletin - 1}")
                                        f.write(f"{anio}, {numero_boletin - 1}")

                        siguiente_mes = siguiente_mes.find_next_sibling()
                    
                else:
                    print("No se ha podido acceder al nuevo año")
                
                #Pasamos al siguiente anio
                siguiente_anio = siguiente_anio.find_next_sibling()

    except Exception as e:
        print(f"Error inesperado en el boletin {numero_boletin}: {e}")

    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos: {e}")

    except requests.exceptions.RequestException as e:
        print(f"Intento rechazado")

if __name__ == "__main__":
    scrapear_dias_completos()


