"""Recolector del Boletín Oficial de Aragón (BOA).

Este script automatiza la descarga de boletines y decretos del BOA a través de su
interfaz web. Navega calendario por calendario usando Selenium, localiza los PDFs
vinculados a cada disposición, los descarga y extrae parte de su HTML para
construir un registro de metadatos almacenado en archivos CSV por año.

Attributes:
    anio_scrappeo (int): Año de inicio predeterminado para el proceso.
    script_dir (str): Directorio raíz del script donde se alojarán los descargas.
    calendario (dict): Configuración del calendario (días por mes).
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
    """Configura e inicia una instancia headless de Google Chrome vía Selenium.

    Desactiva la interfaz de usuario, la aceleración gráfica, el sandboxing y el
    uso de la partición compartida del sistema operativo en favor de un despliegue
    apto para servidores y contenedores.

    Returns:
        webdriver.Chrome: Una instancia iniciada y configurada del navegador.
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
    """Filtra y normaliza cadenas de texto.

    Reemplaza todos los retornos de carro, tabulaciones y espacios múltiples
    conectados por un único espacio en blanco.

    Args:
        texto (str): El texto a limpiar.

    Returns:
        str: El texto normalizado.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Guarda en disco las URLs a las que no se ha podido conectar.

    Args:
        archivo_errores (str): Nombre del archivo donde apuntar el error (sin .txt).
        url_dia (str): La URL que causó el fallo.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Intenta descargar o acceder al contenido de una URL aplicando reintentos.

    Tiene un bucle de hasta 5 intentos adicionales si la URL devuelve error o no
    responde, pausándose progresivamente.

    Args:
        url_buscar (str): La ruta HTTP destino.
        ruta_errores (str): Archivo donde se apuntará la URL si todos los intentos fracasan.

    Returns:
        tuple[requests.models.Response|None, int]: Tupla con el objeto Result o None,
            y un flag binario marcando éxito (1) o error absoluto (0).
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
    """Anexa un conjunto de datos transformado a un archivo CSV.

    Si el archivo no existe en el destino, lo crea agregándole una nueva cabecera
    derivada de las propiedades del DataFrame.

    Args:
        df (pd.DataFrame): Los datos correspondientes a un decreto.
        ruta (str): Directorio raíz del año donde se aloja el CSV.
        anio (int|str): El año procesado, usado en el renombre del fichero.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga iterativamente en porciones un archivo binario.

    Args:
        response_pdf (requests.models.Response): Objeto respuesta que contiene
            el PDF adjunto a descargar.
        enlacePDF (str): Nombre o ruta final donde ubicar el archivo PDF local.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Agrega las metainformaciones extraídas en un objeto pandas uniforme.

    Asigna los parámetros a columnas clave e incluye una nueva columna refiriendo
    la fecha de consulta del sistema. Los campos de texto sufren limpieza antes
    de asignarse al contenedor final.

    Args:
        enlace_html (str): URL relativa o absoluta del documento renderizado en la web.
        identificador (str): Etiqueta creada sintéticamente para seguir el decreto.
        fecha_decreto (str): Fecha de la publicación en formato día-mes-año.
        seccion (str): Sección oficial a la que pertenece dictada en el encabezado.
        subseccion (str): Categoría interior, p.j 'Ayuntamiento' o 'Decretos'.
        contenido_text (str): Párrafos limpios y unidos recolectados del documento HTML.
        enlace_pdf (str): Enlace directo de origen al PDF crudo.
        ruta_guardar_pdf (str): Cadena de la ruta donde yace el registro local del PDF.

    Returns:
        pd.DataFrame: Conjunto unificado con el paquete de metadatos de importación.
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
    """Vigila la disponibilidad de un elemento HTML con un tiempo máximo fijado.

    Recarga la navegación de la página principal en caso de fallo crítico
    continuado. Usado normalmente para verificar si los componentes creados con 
    Angular de la web del BOA existen.

    Args:
        driver (webdriver.Chrome): Ventana en ejecución.
        selector (By): Método de captura, normalmente By.CSS_SELECTOR.
        busqueda (str): Condición de consulta usada por el identificador (CSS/XPATH).

    Returns:
        bool: True si el campo ha hecho acto de presencia en el DOM antes
            de expirar el reloj, de lo contrario False.
    """
    intentos_maximos = 3  
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
    return False

def transformar_mes(mes_leido):
    """Mapea una abreviatura en español del mes a su equivalente en número.

    Args:
        mes_leido (str): 3/4 primeros caracteres del mes procedentes del DOM.

    Returns:
        str | None: El dígito representativo o None si el código es ignorado.
    """
    time.sleep(10)
    if mes_leido == 'ENE':
        return '1'
    elif mes_leido == 'FEB':
        return '2'
    elif mes_leido == 'MAR':
        return '3'
    elif mes_leido == 'ABR':
        return '4'
    elif mes_leido == 'MAY':
        return '5'
    elif mes_leido == 'JUN':
        return '6'
    elif mes_leido == 'JUL':
        return '7'
    elif mes_leido == 'AGO':
        return '8'
    elif mes_leido == 'SEPT':
        return '9'
    elif mes_leido == 'OCT':
        return '10'
    elif mes_leido == 'NOV':
        return '11'
    elif mes_leido == 'DIC':
        return '12'
    else:
        return None
    
def scrapear_dias_completos():
    """Lógica principal para el raspado y extracción por calendario.

    Este núcleo se conecta a la aplicación single-page del BOA. Recorre
    hacia atrás la selección mensual, captura cada día con entradas válidas 
    (ignorando los inactivos/ya evaluados) y lanza consultas encadenadas para:
        - Determinar grupos/secciones vigentes ese día.
        - Explorar todas las listas de artículos.
        - Guardar PDF locales derivados de sus vínculos externos 'rspkr_dr_added'.
        - Acceder a su fuente HTML para recolectar y ensamblar texto bruto con Soup.
    Utiliza persistencia simple (ruta_errores.txt) para manejar reinicios.
    """
    ruta_archivo_errores = os.path.join("url_errores")
    ruta_continuar = os.path.join(script_dir, f"ruta_errores.txt")

    anio = 2025
    numero_boletin = 1

    base_enlace = f"https://www.boa.aragon.es/#/"

    driver = iniciar_driver()
    driver.get(base_enlace)

    dias_recorridos = set()  # Usamos un conjunto para asegurar que no haya duplicados
    mes_anterior = ""

    while anio > 1980:
        if verificar_carga(driver, By.CSS_SELECTOR, "mat-calendar.mat-calendar.calendar.calendar-home"):
            
            print(f"Entramos a la página inicial de referencia")  # Ya estamos dentro
            calendario = driver.find_element(By.CSS_SELECTOR, "mat-calendar.mat-calendar.calendar.calendar-home")
            tabla_calendario = calendario.find_element(By.CSS_SELECTOR, "tbody.mat-calendar-body")
            filas = tabla_calendario.find_elements(By.CSS_SELECTOR, 'tr[role="row"]')

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button.mat-calendar-period-button.mdc-button.mat-mdc-button.mat-unthemed.mat-mdc-button-base"))
            )

            cabecera = driver.find_element(By.CSS_SELECTOR, "button.mat-calendar-period-button.mdc-button.mat-mdc-button.mat-unthemed.mat-mdc-button-base")
            cabec = cabecera.find_element(By.CLASS_NAME, "mdc-button__label").text
            cab = cabec.split(" ")
            mes_transf = transformar_mes(cab[0])
            mes_anterior = mes_transf

            if mes_transf == 12:
                anio -= 1
            base_anio = os.path.join(script_dir, f"{anio}")
            base_dir_pdfs = os.path.join(base_anio, "PDF")
            base_dir_csv = base_anio

            carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

            for carpeta in carpetas:  # Crear las carpetas si no existen
                os.makedirs(carpeta, exist_ok=True)

            dias_numeros = []
            for ind, i in enumerate(filas):
                dias_cogidos = i.find_elements(By.CSS_SELECTOR, 'td[role="gridcell"]')
                for ind2, j in enumerate(dias_cogidos):
                    try:
                        dia_texto = j.find_element(By.CSS_SELECTOR, "span.mat-calendar-body-cell-content.mat-focus-indicator").text
                        if dia_texto:
                            dias_numeros.append(dia_texto)
                    except:
                        continue

            print(f"Almacenados todos los dias del mes leido: {mes_transf}")

            for dia_scrap in dias_numeros:
                if dia_scrap in dias_recorridos:
                    continue
                dias_recorridos.add(dia_scrap)
                print(f"Dentro del dia {dia_scrap}")

                # Volver a cargar el calendario por si se ha navegado fuera
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "mat-calendar.mat-calendar.calendar.calendar-home"))
                )
                calendario = driver.find_element(By.CSS_SELECTOR, "mat-calendar.mat-calendar.calendar.calendar-home")
                tabla_calendario = calendario.find_element(By.CSS_SELECTOR, "tbody.mat-calendar-body")
                filas = tabla_calendario.find_elements(By.TAG_NAME, "tr")

                dia_encontrado = None
                for fila in filas[1:]:
                    celdas = fila.find_elements(By.TAG_NAME, "td")
                    for celda in celdas[1:]:
                        try:
                            span = celda.find_element(By.CSS_SELECTOR, "span.mat-calendar-body-cell-content.mat-focus-indicator")
                            if span.text == dia_scrap:
                                dia_encontrado = celda
                                break
                        except:
                            continue
                    if dia_encontrado:
                        break

                if not dia_encontrado:
                    print(f"No se encontró el día {dia_scrap} al volver al calendario.")
                    continue

                boton = dia_encontrado.find_element(By.TAG_NAME, "button")
                try:
                    cerrar_modal = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.bg-white button"))
                    )
                    cerrar_modal.click()
                except:
                    pass

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", boton)
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(boton))
                boton.click()
                print("Estamos dentro del día")

                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".resultados-list li"))
                    )
                    etiqueta_decretos = driver.find_element(By.CLASS_NAME, "resultados-list")
                    decretos = etiqueta_decretos.find_elements(By.TAG_NAME, 'li')

                    num_decreto = 1
                    seccion_actual = None
                    subseccion_actual = None
                    num_seccion = 0
                    for decreto in decretos:
                        try:
                            num_decreto += 1
                            seccion = decreto.find_element(By.CSS_SELECTOR, "h3.seccion.c-h3.page-inner-text.color-marker").text
                            subseccion = decreto.find_element(By.CSS_SELECTOR, "h4.emisor.c-h4.page-inner-text.font-bold.uppercase").text

                            if seccion != "":
                                seccion_actual = seccion
                                num_seccion += 1
                                num_decreto = 1
                            if subseccion != "":
                                subseccion_actual = subseccion

                            identificador = f"BOA-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"

                            try:
                                html_enlace = decreto.find_element(By.CLASS_NAME, 'c-link').get_attribute('href')
                            except:
                                print("No tiene enlace html")

                            try:
                                enlace_pdf = decreto.find_element(By.CSS_SELECTOR, "a.rspkr_add_drlink.rspkr_dr_added").get_attribute('href')
                            except:
                                print("No existe enlace pdf")

                            if enlace_pdf:
                                respuesta_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                    ruta_guardar_pdf = f"{base_dir_pdfs}\{identificador}.pdf"
                                    descargar_pdf(respuesta_pdf, ruta_guardar_pdf)

                            if html_enlace:
                                driver_decreto = iniciar_driver()
                                driver_decreto.get(html_enlace)

                                if verificar_carga(driver_decreto, By.CSS_SELECTOR, "p.page-inner-text.mt-6"):
                                    p_mayor = driver_decreto.find_element(By.CSS_SELECTOR, "p.page-inner-text.mt-6")
                                    parrafos = p_mayor.find_elements(By.TAG_NAME, 'p')

                                    contenido_texto = ""
                                    for parrafo in parrafos:
                                        contenido_texto += f" {parrafo.text}"

                                    df = crear_df_temporal(
                                        html_enlace, identificador, f"{dia_scrap}-{mes_transf}-{anio}",
                                        seccion_actual, subseccion_actual, contenido_texto, enlace_pdf, ruta_guardar_pdf
                                    )
                                    guardar_contenido_csv(df, base_dir_csv, anio)
                                    print("Contenido almacenado en csv")

                                    driver_decreto.quit()
                        except:
                            print("Error en el decreto")
                            continue
                    numero_boletin += 1

                    print("Volvemos a la pagina anterior")
                    driver.back()

                except:
                    print(f"El dia: {dia_scrap} de {mes_transf}, no tiene decretos")
                    continue

            boton_mes_anterior = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Previous month"]'))
            )
            boton_mes_anterior.click()
            WebDriverWait(driver, 10).until(
                lambda d: d.find_element(By.CLASS_NAME, "mdc-button__label").text != mes_anterior
            )

        else:
            print("No se ha cargado la página finalmente")

if __name__ == "__main__":
    scrapear_dias_completos()


