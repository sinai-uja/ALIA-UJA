"""Recolector del Boletín Oficial de Melilla (BOME) - Parte 2 (2018-Actualidad).

Este script complementa al recolector principal del BOME, automatizando la extracción
sistemática de resoluciones oficiales desde el portal renovado (2018 en adelante).
Usa un enfoque mixto de renderizado web Headless mediante Selenium para evadir barreras de la página 
y de peticiones HTTP en segundo plano sobre los activos en listados estructurados dinámicamente.

Attributes:
    anio_scrappeo (int): El año inicial base a explorar, estático en script.
    script_dir (str): Directorio raíz del script donde se almacenan PDFs y CSVs.
    calendario (dict): Formato referencial de iteración temporal de días sobre los meses.
    meses_calendario (dict): Mapeo literal español-numérico para formato de fechas.
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

meses_calendario = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
}


def iniciar_driver():
    """Inicializa y configura de manera furtiva un navegador Chrome en modo Headless.

    Establece opciones sin GUI, eximiendo carga estricta de GPU y reduciendo el log verboso.

    Returns:
        webdriver.Chrome: Instancia WebDriver operativa lista para la navegación o parseo dinámico.
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
    """Refina y normaliza el espaciado global entre caracteres.

    Args:
        texto (str): Cadena bruta decodificada sin filtrar por html/bs4.

    Returns:
        str: Segmento ordenado a un espacio único constante por salto u operador.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Adjunta explícitamente y registra enlaces con fallos HTTP terminales detectados en red.

    Args:
        archivo_errores (str): Senda sin extensión destino al '.txt'.
        url_dia (str): La URL que desestima su intento original en la matriz.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Enrutamiento web persistente por stream `Chunked` provisto de control activo contra rechazos del server.

    Args:
        url_buscar (str): Meta de localización HTTP(s).
        ruta_errores (str): Componente de disco en donde loguear un fallo integral web final tras 5 pasadas cíclicas.

    Returns:
        tuple[requests.models.Response | None, int]: Instancia web o None y matriz booleana manual `1, 0`.
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
    """Almacena o amalgama DataFrame temporal Pandas al CSV transaccional anual matriz general.

    Args:
        df (pd.DataFrame): Cuadro aislado formateado correspondiente a la petición unitaria de Scrap.
        ruta (str): Directorio raíz del año donde reside el CSV.
        anio (int|str): Extensión y base de nombramiento para iterador año.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Transfiere en el medio disco persistente el stream binario asincrónico por partes (`8kb`) de PDF oficial.

    Args:
        response_pdf (requests.models.Response): Instancia base devuelta validada previamente en `intentar_peticion()`.
        enlacePDF (str): Nomenclatura del fichero meta local sobre sistema de archivos.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Procesa e inicializa DataFrame tabular conteniendo metadatos unitarios consolidados del registro.

    Args:
        enlace_html (str): Reconstrucción absoluta link extraído HTML de la lectura secundaria intersecante.
        identificador (str): Cadena universal BOME+Años+Ids relativos.
        fecha_decreto (str): Impresión formal natural validada sobre el aviso original bs4.
        contenido_text (str): Lo empaquetado y purgado en html render bs4.
        enlace_pdf (str): Enlace unívoco al activo digital en el portal.
        ruta_guardar_pdf (str): Equivalencia base depositada final en el disco duro.

    Returns:
        pd.DataFrame: DataFrame de renglón solitario y limpiezas subyacentes terminadas sobre tabulaciones.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
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
    """Supervisa o reanima pasarelas latentes de Selenium forzando el reload de los bloqueos in-memory.

    Args:
        driver (webdriver.Chrome): Motor a cargo de vigilar y esperar activamente (20s máximos sin refresh temporal `timeout`).
        selector (By.*): Indicador nominal nativo locator ID/Class (`By.XPATH` etc).
        busqueda (str): Etiqueta cruda objetivo que gatilla el success.

    Returns:
        bool: Retorna asertivamente el alcance pleno sin excepción (True) o corta la ejecución general (False).
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
    """Arranque sistemático y base principal sobre la estructura cronológica de boletines del BOME 2018-Actualidad.

    Recorre internamente desde `2018` al presente e inyecta paralelismo indirecto usando Beautifulsoup para resolver la data HTML
    del entramado estructural. Controla hitos en logs `continuar_por_parte2.txt`. Recoleta recursivamente y atraviesa iterando subagrupadores
    o capas orgánicas en la disposición arborescente (listados `mt-list-container` -> `li` -> `ul`) que el server presenta de sumarios diarios.
    """
    ruta_continuar =  os.path.join(script_dir, f"continuar_por_parte2.txt")
    ruta_archivo_errores = os.path.join(script_dir, "url_errores")

    numero_boletin = 1
    anio = 2018

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
            for anio in range(2018, 2025):
                base_anio = os.path.join(script_dir, f"{anio}")
                base_dir_pdfs = os.path.join(base_anio, "PDF")
                base_dir_csv = base_anio 
                carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                for carpeta in carpetas:    # Crear las carpetas si no existen
                    os.makedirs(carpeta, exist_ok=True)
                print(f"Carpetas del anio {anio} creadas...")
                
                enlace_principal = f"https://bomemelilla.es/bomes/{anio}"
                respuesta, encontrado = intentar_peticion(enlace_principal, ruta_archivo_errores)

                if encontrado == 1 and respuesta and respuesta.status_code == 200:
                    print("Estamos en la pagina principal del BOCCE")
                    soup = BeautifulSoup(respuesta.text, 'html.parser')
                    columna = soup.find("div", class_="col-md-8")
                    meses = columna.find_all("div", class_="col-md-4")
                    for mes in meses:
                        tabla_enlaces = mes.find("table", class_= "table table-striped table-bordered table-hover")
                        enlaces = tabla_enlaces.find_all("tr", class_="bome")
                        
                        for aes in enlaces:
                            onclick_value = aes.get('onclick')
                            enlace_relativo = onclick_value.split("location.href = '")[1].split("'")[0]
                            enlace_boletin = f"https://bomemelilla.es{enlace_relativo}"

                            respuesta_boletin, encontrado_boletin = intentar_peticion(enlace_boletin, ruta_archivo_errores)
                            if encontrado_boletin == 1 and respuesta_boletin and respuesta_boletin.status_code == 200:
                                soup_boletin = BeautifulSoup(respuesta_boletin.text, 'html.parser')
                                lista = soup_boletin.find("div", "mt-list-container list-todo")
                                lista_ul = lista.find("ul")
                                secciones = lista_ul.find_all("li")

                                num_seccion = 0
                                num_subseccion = 0
                                num_decreto = 0
                                for seccion in secciones:
                                    num_seccion += 1
                                    num_decreto = 0
                                    lista_subsecciones = seccion.find_all("ul")

                                    for cada_ul in lista_subsecciones:
                                        num_subseccion += 1
                                        decretos = cada_ul.find_all("li")

                                        for decreto in decretos:
                                            num_decreto += 1
                                            identificador = f"BOME-{anio}-Boletin-{numero_boletin}-S-{num_seccion}-D-{num_decreto}"
                                            div_enlaces = decreto.find("div", class_="desVer")
                                            enlace_pdf = div_enlaces.find("a")
                                            onclick_value = enlace_pdf.get('onclick', '')
                                            link_pdf = None
                                            ruta_guardar_pdf = None
                                            onclick_value = enlace_pdf.get('onclick', '')
                                            link_pdf = None
                                            if 'window.open' in onclick_value and '.pdf' in onclick_value:
                                                link_pdf = onclick_value.split("window.open('")[1].split("');")[0]
                                                link_pdf = f"https://bomemelilla.es{link_pdf}"  

                                            if link_pdf:
                                                respuesta_pdf, encontrado_pdf = intentar_peticion(link_pdf, ruta_archivo_errores)
                                                if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                                    ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"
                                                    descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                                    numero_boletin += 1
                                                    time.sleep(0.5)

                                            enlace_html = enlace_pdf.find_next_sibling("a")['href']
                                            enlace_html = f"https://bomemelilla.es{enlace_html}"

                                            respuesta_html, encontrado_html = intentar_peticion(enlace_html, ruta_archivo_errores)
                                            if encontrado_html == 1 and respuesta_html and respuesta_html.status_code == 200:
                                                soup_decreto = BeautifulSoup(respuesta_html.text, 'html.parser')
                                                columna_p = soup_decreto.find("div", class_="col-md-8")
                                                clase_fecha = soup_decreto.find("div", class_="center")
                                                span_class = clase_fecha.find("span", class_="lowercase")
                                                fecha_texto = span_class.get_text() if span_class else None
                                                fecha_sin_dia = fecha_texto.split(", ")[1] if ", " in fecha_texto else fecha_texto
                                                fecha_partes = fecha_sin_dia.split(' de ')
                                                dia = fecha_partes[0]
                                                nuevo_mes = meses_calendario[fecha_partes[1].lower()]
                                                anio = fecha_partes[2]
                                                fecha_decreto = f"{dia}-{nuevo_mes}-{anio}"
                                                contenido_texto = columna_p.find_all("p")
                                                texto = ""
                                                for pes in contenido_texto:
                                                    texto += pes.get_text()
                                                df = crear_df_temporal(enlace_html, identificador, fecha_decreto, texto, link_pdf, ruta_guardar_pdf)
                                                guardar_contenido_csv(df, base_dir_csv, anio)
                                                print(f"Fecha: {fecha_decreto}: guardada en csv")
                                                
                                with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                    print(f"Guardamos el fichero en el boletin: {anio}-{numero_boletin - 1}")
                                    f.write(f"{anio}, {numero_boletin - 1}")

                                numero_boletin += 1

    except Exception as e:
        print(f"Error inesperado en el boletin {numero_boletin}: {e}")

    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos: {e}")

    except requests.exceptions.RequestException as e:
        print(f"Intento rechazado")

if __name__ == "__main__":
    scrapear_dias_completos()


