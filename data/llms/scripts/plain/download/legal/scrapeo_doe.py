"""Recolector del Diario Oficial de Extremadura (DOE).

Este script automatiza la extracción sistemática de resoluciones del DOE.
Itera sobre calendarios anuales pre-configurados, accediendo a la base web `doe.juntaex.es` por cada día.
Busca las secciones (marcadas con clases CSS `DOE2`, `d*`) y las disposiciones (`div.justificado`),
descargando PDFs y opcionalmente extrayendo el texto HTML desde mayo de 2022 en adelante.

Attributes:
    anio_scrappeo (int): Marcador inicial base temporal.
    script_dir (str): Directorio raíz del script.
    calendario (dict): Formato referencial de días sobre los meses del año.
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
    # 12: list(range(1, 32))  
}

def limpiar_texto(texto):
    """Estiliza los campos base decodificados borrando espacios múltiples y retornos.

    Args:
        texto (str): Cadena en formato crudo obtenida.

    Returns:
        str: Segmento depurado sin ruidos visuales.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Loguea enlaces defectuosos en un registro de texto plano.

    Args:
        archivo_errores (str): Path del archivo de errores (sin extensión).
        url_dia (str): URL fallida a registrar.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Protege peticiones GET con reintentos ante caídas HTTP o transferencias incompletas.

    Args:
        url_buscar (str): URL destino a consultar.
        ruta_errores (str): Ruta del archivo de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
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
    """Anexa filas al CSV acumulativo anual.

    Args:
        df (pd.DataFrame): Fila de datos a guardar.
        ruta (str): Directorio destino del CSV.
        anio (int|str): Año usado como nombre del archivo CSV.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print(f"Guardamos contenido del decreto...")

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga un PDF desde un stream HTTP y lo guarda en disco.

    Args:
        response_pdf (requests.models.Response): Respuesta HTTP con el PDF en stream.
        enlacePDF (str): Ruta local de destino para guardar el PDF.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Construye un DataFrame con los metadatos y contenido de una disposición.

    Args:
        enlace_html (str): URL de la página HTML del decreto.
        identificador (str): ID único del decreto (Ej. DOE-AÑO-Boletin-X-Seccion-Y-Dec-Z).
        fecha_decreto (str): Fecha formateada `DD-MM-AAAA`.
        seccion (str): Sección principal del DOE.
        subseccion (str): Organismo emisor.
        contenido_text (str): Texto extraído del decreto.
        enlace_pdf (str): URL del PDF oficial.
        ruta_guardar_pdf (str): Ruta local del PDF descargado.

    Returns:
        pd.DataFrame: Fila lista para volcar al CSV.
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

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Orquestador principal del scraping del DOE.

    Itera sobre los días del calendario para el año indicado, accediendo a la URL diaria del DOE.
    Detecta secciones (clases CSS `DOE2`, `d*`) y disposiciones (`div.justificado`), descargando PDFs.
    A partir del 5 de mayo de 2022 también extrae el texto HTML de cada decreto.
    Guarda un archivo TXT de continuación para resumir scraping interrumpido.

    Args:
        anio_scrappeo (int, kwarg): Año de inicio del scraping.
    """

    for anio in range(anio_scrappeo,anio_scrappeo+1): #leemos cada dos años

        base_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdfs = os.path.join(base_anio, "PDF")
        base_dir_csv = base_anio
        ruta_archivo_errores = os.path.join(base_anio, "url_errores")
        ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

        for carpeta in carpetas:    # Crear las carpetas si no existen
            os.makedirs(carpeta, exist_ok=True)

        mes_leido = 1
        dia_leido = 1
        numero_boletin = 1

        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{mes_leido},{dia_leido},{numero_boletin}")  #leemos el dia y el mes
                print("Escribimos el mes...")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                mes_leido, dia_leido, numero_boletin = map(int, f.read().strip().split(','))
                numero_boletin += 1
                print("Leemos el mes...")

        print(f"EMPEZAMOS POR EL DIA -> {dia_leido}-{mes_leido}-{anio}")

        for mes in range(mes_leido, 13):  # Desde el mes guardado hasta diciembre (12)
            dias_mes = calendario.get(mes, [])

            # Para el primer mes (si no es el mes inicial), comenzar desde el día guardado
            for dia in dias_mes[dia_leido-1:]:   #leemos cada dia
                try: 
                    con_html = 0
                    if anio < 2022:
                        con_html = 0
                    elif anio == 2022:
                        if mes < 5:
                            con_html = 0
                        elif mes == 5:
                            if dia < 5:
                                con_html = 0
                            else:
                                con_html = 1
                        else:
                            con_html = 1
                    else:
                        con_html = 1 


                    base_enlaces = f"https://doe.juntaex.es/ultimosdoe/mostrardoe.php?fecha={anio}{mes:02}{dia:02}&t=o"
                    print(f"Enlace: {base_enlaces}")
                    respuesta, encontrado = intentar_peticion(base_enlaces, ruta_archivo_errores)
                    if encontrado == 1 and respuesta and respuesta.status_code == 200:
                        soup = BeautifulSoup(respuesta.text, 'html.parser')
                        contenido = soup.find("div", class_="Contenido_DOE")
                        seccion_actual = ""
                        subseccion_actual = ""
                        num_seccion = 0
                        num_decreto = 0
                        next_tag = contenido.find()
                        while next_tag:
                            if next_tag.name == 'p':
                                span = next_tag.find('span')
                                span_classes = span.get('class', [])
                                if 'DOE2' in span_classes:
                                    subseccion_actual = next_tag.text
                                    next_tag = next_tag.find_next_sibling()
                                    
                                elif any(cls.startswith('d') for cls in span_classes):
                                    seccion_actual = next_tag.text
                                    num_decreto = 0
                                    num_seccion += 1
                                    print(f"Nueva seccion: {seccion_actual}")
                                    next_tag = next_tag.find_next_sibling()
                                else:
                                    next_tag = next_tag.find_next_sibling()
                            if next_tag.name == 'div':
                                if 'justificado' in next_tag.get('class', []):
                                    num_decreto += 1
                                    identificador = f"DOE-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                                    base_pdf = 'https://doe.juntaex.es/'
                                    enlace_p = next_tag.find('a', class_='enlace_dis')['href']
                                    enlace_pdf = f"{base_pdf}{enlace_p}"
                                    ruta_guardar_pdf = os.path.join(base_dir_pdfs, identificador)
                                    ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"
                                    if enlace_p:
                                        respuesta_pdf, encon = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                        if encon == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                            descargar_pdf(respuesta_pdf, ruta_guardar_pdf)

                                    if con_html == 1:
                                        enlace_ = next_tag.find('a', class_='menu')['href']
                                        enlace_sin = enlace_.lstrip('./')
                                        enlace_h = f"{base_pdf}{enlace_sin}"
                                        if enlace_:
                                            respuesta_html, encontrado_h = intentar_peticion(enlace_h, ruta_archivo_errores)
                                            if encontrado_h == 1 and respuesta_html and respuesta_html.status_code == 200:
                                                print("Entramos al html del decreto")
                                                soup_html = BeautifulSoup(respuesta_html.text, 'html.parser')
                                                texto = soup_html.find("div", class_='xml')
                                                contenido = texto.get_text(strip=True)
                                                fecha_decreto = f"{dia}-{mes}-{anio}"
                                                df = crear_df_temporal(enlace_h, identificador, fecha_decreto, seccion_actual, subseccion_actual, contenido, enlace_pdf, ruta_guardar_pdf)
                                                guardar_contenido_csv(df, base_dir_csv, anio)
                                    time.sleep(0.5)
                                next_tag = next_tag.find_next_sibling()
                            else:
                                next_tag = next_tag.find_next_sibling()

                except Exception as e:
                    print(f"Error inesperado en el día {dia}: {e}")
                    continue

                except ChunkedEncodingError as e:
                    print(f"Error en la transferencia de datos: {e}")
                    continue
            
                except requests.exceptions.RequestException as e:
                    print(f"Intento rechazado")
                    continue
        dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


