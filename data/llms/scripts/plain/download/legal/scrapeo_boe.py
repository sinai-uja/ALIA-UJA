"""Recolector del Boletín Oficial del Estado (BOE).

Este script automatiza la extracción masiva de datos y descarga de documentos
del BOE. Utiliza peticiones HTTP y Selenium (para renderizado dinámico cuando se requiere)
para navegar por el histórico, extraer la estructura jerárquica de resoluciones y 
descargarlas en formato PDF. Incluye extracción de texto avanzado en local
empleando procesamiento OCR (Tesseract / EasyOCR) y métodos de extracción directa (PyMuPDF).
Estructura finalmente los metadatos y contenido puro en formato CSV y Parquet.

Attributes:
    anio_scrappeo (int): El año o parámetro base inicial de recolección temporal.
    script_dir (str): Directorio raíz donde reside el script y sus ramificaciones de dependencias.
    calendario (dict): Formato referencial de días sobre los meses (iterador de bucle principal).
    meses (dict): Mapeo estricto del lenguaje español-numérico para procesamiento de fechas.
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
import pandas as pd
import pytesseract
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
from requests.exceptions import ChunkedEncodingError
import polars as pl
import pytesseract
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import clize
import zipfile
from PyPDF2 import PdfReader
import random
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import pdfplumber
import easyocr
import numpy as np
import torch
from datetime import datetime
import shutil

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))
pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

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

meses = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5,
    'junio': 6, 'julio': 7, 'agosto': 8, 'septiembre': 9,
    'octubre': 10, 'noviembre': 11, 'diciembre': 12
}

def limpiar_texto(texto):
    """Elimina espacios múltiples y saltos de línea de una cadena de texto.

    Args:
        texto (str): El texto original a limpiar.

    Returns:
        str: El texto limpio y formateado a espacios simples.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Registra una URL conflictiva de manera persistente en disco duro.

    Dicho registro de error actúa como una constancia para revisión y re-intento a futuro.

    Args:
        archivo_errores (str): Ruta preestablecida del archivo (excluyendo '.txt').
        url_dia (str): La URL que originó la excepción HTTP resolutiva.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Ejecuta una petición HTTP GET blindada contra incidencias y latencia.

    Procesa las cabeceras exitosas (200), alertas de vacío (404) y dispone hasta 10
    reintentos para otro abanico de excepciones en tramas TCP o de Servidor.

    Args:
        url_buscar (str): La URL objetivo.
        ruta_errores (str): Directorio raíz y nombre sobre el que registrar URL problemáticas finales.

    Returns:
        tuple: Objeto requests.models.Response (o None) emparejado a  un 
            booleano en entero de éxito transaccional (1) o caída absoluta (0).
    """

    i = 0 
    encontrada_respuesta = 0
    respuesta = None
    try:
        respuesta = requests.get(url_buscar ,stream=True)
        if respuesta and respuesta.status_code == 200:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta

        elif respuesta.status_code == 404:
            encontrada_respuesta = 1
            return respuesta, encontrada_respuesta
        else:
            encontrado = False
            for i in range(10):
                print(f"No se pudo acceder a {url_buscar}: reintentamos")
                time.sleep(i+1)
                respuesta = requests.get(url_buscar, stream=True) 
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
    """Realiza un volcado del metadato recolectado de un dictamen a un archivo unificado CSV del anio.

    Args:
        df (pd.DataFrame): Objeto estandarizado de Pandas con los valores formados.
        ruta (str): Directorio final destinado a su preservación.
        anio (int|str): El identificativo general de año temporal en marcha (usado en el propio fichero).
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Documento guardado en csv")

def descargar_pdf(response_pdf, enlacePDF):
    """Extrae el contenido directo del descriptor binario asociado a un decreto PDF.

    Lo procesa in-streaming por empaquetados definidos para evadir la congestión de memoria RAM.

    Args:
        response_pdf (requests.models.Response): Flujo HTTP validado a procesar y descomponer en red.
        enlacePDF (str): Nombre local asignado y directorio de aterrizaje hacia el PDF base.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, referencia, fecha_decreto, resumen, nombre_seccion_actual, nombre_subseccion_actual, nombre_agr, Contenido, texto_pdf, text, enlace_pdf, ruta_guardar_pdf):
    """Sintetiza de forma masiva en Pandas un renglón representativo del BOE.

    Contiene lógica de limpieza general y aglutina el conjunto analítico (OCR, raw text) extraido del documento físico y web.

    Args:
        identificador (str): Etiqueta posicional universal designada.
        referencia (str): Alfanumérico provisto dentro de un dictamen meta (a veces nulo).
        fecha_decreto (str): Tiempo del boletín formal.
        resumen (str): Introducción de las notas indexadas obtenidas con BS4.
        nombre_seccion_actual (str): Clasificador de nivel superior en la hoja estructural del día.
        nombre_subseccion_actual (str): Clasificador secundario en la jerarquía del día.
        nombre_agr (str): Grupo semántico de nivel intermedio (Tercer descendiente).
        Contenido (str): Depuración puramente extraída en red HML del ID "textoxslt".
        texto_pdf (str): Escaneo analítico obtenido después del procesador PyMuPDF/tesseract del documento subyacente descargado.
        text (str): El total condensado si lograran converger distintas vertientes analíticas.
        enlace_pdf (str): Conector puro del protocolo web original por si el PDF es inservible.
        ruta_guardar_pdf (str): Almacenamiento local para fines de debugging.

    Returns:
        pd.DataFrame: Renglón simple asimilado para exportación a la BD total o un archivo particular CSV.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "publication_date": fecha_decreto,
        "reference": referencia,
        "summary": resumen,
        "section": nombre_seccion_actual,
        "subsection": nombre_subseccion_actual,
        "group": nombre_agr,
        "content": Contenido,
        "pdf_content": texto_pdf,
        "text": text,
        "url": enlace_pdf,
        "read_date": fecha_lectura,
        "route_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_and_tables(pdf_path):
    """Lee y disocia textos simples de tablas complejas usando pdfplumber.

    Algoritmo minucioso que segmenta espacialmente, recupera celdillas y restablece formatos 
    a un bloque condensado, borrando a medida para estabilizar los requisitos masivos de RAM.

    Args:
        pdf_path (str): Fichero local al PDF en análisis.

    Returns:
        tuple[str, bool]: Sumario de extracciones intercaladas entre etiquetas [TABLA] con el flag operativo `True`.
            Devuelve (Mensaje de fallo, `False`) en caso de crash interno/pdf dañado.
    """
    contenido = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.find_tables()
                tables = sorted(tables, key=lambda t: t.bbox[1])
                last_y = 0
                for table_num, table in enumerate(tables, 1):
                    # Texto antes de la tabla
                    upper_text = page.within_bbox((0, last_y, page.width, table.bbox[1])).extract_text()
                    if upper_text:
                        contenido.append(upper_text)
                    # Tabla
                    df_table = table.extract()
                    tabla_texto = "\n".join(["\t".join(row) for row in df_table])
                    contenido.append(f"\n[TABLA {page_num}.{table_num}]\n{tabla_texto}\n")
                    last_y = table.bbox[3]
                    # Liberar variables justo después de usarlas
                    del df_table, tabla_texto, upper_text

                # Texto después de la última tabla
                lower_text = page.within_bbox((0, last_y, page.width, page.height)).extract_text()
                if lower_text:
                    contenido.append(lower_text)
                del lower_text, tables
                gc.collect()
 
        return "\n".join(contenido), True
    except Exception as e:
        print("Error en extraer contenido y tablas")
        return f"{e}", False

def extract_text_ocr_easyocr(pdf_path, reader):
    """Extrae texto usando OCR con EasyOCR procesando página a página para optimizar RAM"""
    try:
        full_text = ""
        
        # Obtén el número total de páginas del PDF
        pdf_reader = PdfReader(pdf_path)
        num_pages = len(pdf_reader.pages)
        
        for page_number in tqdm(range(1, num_pages + 1), desc=f"OCR páginas de {os.path.basename(pdf_path)}", leave=False):
            # Convierte solo una página a imagen para OCR
            pages = convert_from_path(pdf_path, dpi=300, first_page=page_number, last_page=page_number)
            page_image = np.array(pages[0])
            
            # Extrae texto de la imagen
            result = reader.readtext(page_image, detail=0, paragraph=True)
            text = " ".join(result)
            full_text += text + "\n\n"
            
            # Limpieza para liberar memoria
            del pages, page_image, result, text
            gc.collect()
            torch.cuda.empty_cache()
        
        return full_text
    except Exception as e:
        print(f"Error en OCR EasyOCR de {os.path.basename(pdf_path)}: {e}")
        return str(e)
    
def extract_text_direct(pdf_path, min_chars=1):
    """Extrae texto directamente usando PyMuPDF"""
    try:
        direct_text = ""
        gc.collect()
        doc = fitz.open(pdf_path)
        for page in doc:
            direct_text += page.get_text()
        doc.close()
        gc.collect()
        
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        print(f"Error al extraer texto directo de {os.path.basename(pdf_path)}: {e}")
        return f"{e}", False

def process_pdf(pdf_file, reader):
    """Procesa un PDF usando extracción directa y OCR si es necesario"""
    filename = os.path.basename(pdf_file)
    try:
        text, success = extract_text_and_tables(pdf_file)
        if not success:
            print(f"Texto directo insuficiente en {filename}, intentando PyMuPDF...")
            text, success = extract_text_direct(pdf_file)
            if not success:
                print(f"Texto directo insuficiente en {filename}, intentando OCR...")
                text = extract_text_ocr_easyocr(pdf_file, reader)
                if text == 'EOF marker not found':
                    print(f"Error al procesar {filename}: EOF marker not found")
                    text = ''
    except:
        with open("error_log.txt", "a") as f:
            print(f"Error al procesar {filename}: {sys.exc_info()[0]}")
            f.write(f"Error en {filename}: {sys.exc_info()[0]} - {datetime.datetime.now()}\n")

    if '.pdf' in filename:
        filename = filename.replace('.pdf', '')
    return filename, text


def crear_carpetas_nuevas(anio):
    """Crea la arquitectura base requerida de carpetas necesarias de scraping anualmente.

    Args:
        anio (int|str): Identificador centralizado (Año) bajo el cual anidar las carpetas de recursos y depuración.

    Returns:
        tuple[str, str]: Un arreglo pareado `(base_anio, base_dir_pdfs)` representando las dos rutas absolutas base en sistema.
    """
    base_anio = os.path.join(script_dir, f"{anio}")
    base_dir_pdfs = os.path.join(base_anio, "PDF")

    carpetas = [base_anio, base_dir_pdfs]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    return base_anio, base_dir_pdfs

def extract_text_direct(pdf_path, min_chars=50 ):
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

def extract_text_ocr(pdf_path, language='spa', poppler_path=r'C:\poppler-24.08.0\Library\bin'):
    """Extrae texto usando OCR con Tesseract"""
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=poppler_path)
        
        full_text = ""
        # Añadir tqdm para seguimiento de páginas OCR
        for i, page in enumerate(tqdm(pages, desc=f"OCR páginas de {os.path.basename(pdf_path)}", leave=False)):
            text = pytesseract.image_to_string(page, lang=language)
            full_text += text + "\n\n"
        
        return full_text
    except Exception as e:
        print(f"Error en OCR de {os.path.basename(pdf_path)}: {e}")
        return ""

def process_pdf(pdf_file):
    """Procesa un PDF usando extracción directa y OCR si es necesario"""
    filename = os.path.basename(pdf_file)
    name_without_ext = os.path.splitext(filename)[0]
    
    # Primero intentar extracción directa (rápida)
    try:
        text, success = extract_text_direct(pdf_file)
        
        # Si la extracción directa no tuvo éxito, usar OCR
        used_ocr = False
        if not success:
            print(f"Usando OCR para {filename} (extracción directa insuficiente)")
            
            text = extract_text_ocr(pdf_file)
            used_ocr = True
    # else:
    #     print(f"Texto extraído directamente para {filename}")
    except:
        with open("error_log.txt", "a") as f:
            f.write(f"Error en {filename}: {sys.exc_info()[0]}\n")
        
    
    return text

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Secuencia maestra del scraping que centraliza y articula operaciones por cada día de un año al BOE.

    Enlaza módulos de descarga, extracción óptica OCR de PDFs pesados y la unificación de texto directo HTML `textoxslt`. 
    Implementa tracking estricto a fallos en `continua_por.txt` e inicia su recorrido leyendo exhaustivamente jerarquías 
    HTML mediante el framework BS4 y consolidaciones OCR locales (Tesseract & EasyOCR).
    Al completarse el año unifica los metadatos volcándolos a `.parquet` comprimido a .zip.

    Args:
        anio_scrappeo (int, kwarg): Marcador temporal inyectable de inicio del calendario de rastreo que controla bucles y el nombramiento base de BD locales.
    """

    for anio in range(anio_scrappeo,anio_scrappeo + 1): #Modificar el año si queremos ejecutar más terminales
        
        base_dir_pdfs = os.path.join(script_dir, f"{anio_scrappeo}", "pdf")
        base_dir_csv = os.path.join(script_dir, f"{anio_scrappeo}")
        ruta_archivo_errores = os.path.join(script_dir, f"{anio_scrappeo}", "url_errores")

        carpetas = [base_dir_csv, base_dir_pdfs, ruta_archivo_errores]

        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        ruta_continuar =  os.path.join(script_dir, f"{anio_scrappeo}", "continua_por.txt")
        numero_boletin = 0
        reader = easyocr.Reader(['es', 'en'], gpu=False)
        dia_leido = 1
        mes_leido = 1
        num_bol = 0
        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{dia_leido}, {mes_leido}, {num_bol}")  #leemos el dia y el mes
                print("Escribimos el mes...")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                linea = f.read()
                dia_str, mes_str, num_bol2 = linea.strip().split(",")
                dia_leido = int(dia_str)
                mes_leido = int(mes_str)
                num_bol = int(num_bol2)
                print("Leemos el mes...")

        print(f"EMPEZAMOS POR EL boletin -> {numero_boletin}")

        # Crear las carpetas si no existen
        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        numero_boletin = 46
        mes_leido = 2   
        dia_leido = 24
        for mes in sorted(calendario):
            if mes < mes_leido:
                continue  # saltar meses anteriores
            for dia in calendario[mes]:
                if mes == mes_leido and dia < dia_leido:
                    continue 

                base_enlace = f"https://www.boe.es/boe/dias/{anio}/{mes:02}/{dia:02}/"
                response, find = intentar_peticion(base_enlace, ruta_archivo_errores)

                if find and find == 1 and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    numero_boletin += 1
                    sumary = soup.find("div", class_="sumario")
                    siguiente = sumary.find()

                    num_seccion = 0
                    num_decreto = 0
                    print("Scrapeamos todas las secciones del boletín...")

                    nombre_seccion_actual = "" 
                    nombre_subseccion_actual = "" 
                    nombre_agrupacion_actual = "" 

                    while siguiente:
                        if siguiente.name == 'h3':
                            nombre_seccion_actual = siguiente.text
                            num_seccion += 1
                            num_decreto = 0
                            print(f"Nueva seccion: {nombre_seccion_actual}")
                        
                        if siguiente.name == 'h4':
                            nombre_subseccion_actual = siguiente.text
                            print(f"Nueva seccion: {nombre_subseccion_actual}")
                        
                        if siguiente.name == 'h5':
                            nombre_agrupacion_actual = siguiente.text
                            print(f"Nueva seccion: {nombre_agrupacion_actual}")

                        if siguiente.name == 'ul':
                            todos_li = siguiente.find_all("li", class_="dispo")
                            for decreto in todos_li:
                                num_decreto += 1
                                identificador = f"BOE-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                resumen = ""
                                resumen = decreto.find("p").text
                                enlaces_doc = decreto.find("div", class_="enlacesDoc")
                                enlace_viajar = enlaces_doc.find("li", class_="puntoHTML")
                                enlace_pdf = enlaces_doc.find("li", class_="puntoPDF2")
                                if not enlace_pdf:
                                    enlace_pdf = enlaces_doc.find("li", class_="puntoPDF")
                                a_dentro = None
                                try:
                                    a_dentro = enlace_pdf.find("a")['href']
                                except:
                                    a_dentro = None
                                texto_pdf_leido = None
                                a_enlace_pdf = None
                                a = None
                                referencia = None
                                texto_concatenado = None
                                ruta_guardar_pdf = None
                                texto_concatenado2 = None
                                if a_dentro:
                                    a_enlace_pdf = f"https://www.boe.es{a_dentro}"
                                    ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"

                                    response_pdf, encontrado_pdf = intentar_peticion(a_enlace_pdf, ruta_archivo_errores)
                                    if encontrado_pdf and encontrado_pdf == 1 and response_pdf.status_code == 200:
                                        descargar_pdf(response_pdf, ruta_guardar_pdf)
                                        texto_pdf_leido = process_pdf(ruta_guardar_pdf)

                                try:
                                    a = enlace_viajar.find("a")['href']
                                except:
                                    a = None
                                if a:
                                    a_pdf = f"https://www.boe.es{a}"
                                    print(f"Viajamos a: {a_pdf}")

                                    response_decreto, find_decreto = intentar_peticion(a_pdf, ruta_archivo_errores)
                                    if find_decreto and find_decreto == 1 and response_decreto.status_code == 200:
                                        soup_decreto = BeautifulSoup(response_decreto.text, 'html.parser')                  
                                        metadatos = soup_decreto.find("div", class_="metadatos")
                                        
                                        if metadatos:
                                            dts = metadatos.find_all("dt")
                                            dds = metadatos.find_all("dd")

                                            for dt, dd in zip(dts, dds):
                                                if "Referencia" in dt.text:
                                                    referencia = dd.text.strip()

                                        texto = soup_decreto.find(id="textoxslt")
                                        if texto:
                                            parrafos = texto.find_all("p")
                                            if any("Texto no disponible" in p.get_text() for p in parrafos):
                                                texto_concatenado2 = None
                                            else:
                                                texto_concatenado2 = " ".join(p.get_text(strip=True) for p in parrafos)

                                if texto_concatenado2 and texto_pdf_leido:
                                    texto_concatenado = texto_concatenado2 + "\n" + texto_pdf_leido
                                elif texto_concatenado2:
                                    texto_concatenado = texto_concatenado2
                                elif texto_pdf_leido:
                                    texto_concatenado = texto_pdf_leido
                                else:
                                    texto_concatenado = None
                                        
                                df = crear_df_temporal(identificador, referencia, f"{dia}-{mes}-{anio}", resumen, nombre_seccion_actual, nombre_subseccion_actual, nombre_agrupacion_actual, texto_concatenado2, texto_pdf_leido, texto_concatenado, a_enlace_pdf, ruta_guardar_pdf)
                                guardar_contenido_csv(df, base_dir_csv, anio)
                                ruta_csv = f"{base_dir_csv}\{anio}"
                                time.sleep(random.randint(2, 4))
                                print("Pasamos al siguiente decreto...")

                        siguiente = siguiente.find_next_sibling()

    
    parquet_path = f"{base_dir_csv}/{anio}.parquet"
    try:
        if os.path.exists(ruta_csv):
            df = pd.read_csv(ruta_csv, encoding='utf-8')
            df.to_parquet(parquet_path, index=False)
            print(f"✅ CSV convertido a Parquet: {parquet_path}")
    except Exception as e:
        print(f"❌ Error al convertir CSV a Parquet para el año{e}")

    zip_path = os.path.join(script_dir, f"{anio}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if os.path.exists(parquet_path):
                zipf.write(parquet_path, os.path.basename(parquet_path))
                zipf.write(ruta_csv, os.path.basename(ruta_csv))
            print(f"✅ Archivo ZIP creado: {zip_path}")
    except Exception as e:
        print(f"❌ Error al crear el archivo ZIP para el año {e}")

       
if __name__ == "__main__":
    clize.run(scrapear_dias_completos)



