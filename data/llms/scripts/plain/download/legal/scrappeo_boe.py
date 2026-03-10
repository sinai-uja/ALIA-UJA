"""Recolector del Boletin Oficial del Estado (BOE).

Este script automatiza la extracción de decretos del BOE accediendo a los índices diarios
en formato XML. Por cada decreto descarga el XML y el PDF asociado, extrae los metadatos
de los campos XML y los acumula en un DataFrame que se guarda en CSV por año.
Dispone opcionalmente de lectura OCR con Tesseract para PDFs escaneados.

Attributes:
    base_enlace (str): URL base del API XML del BOE.
    calendario (dict): Formato referencial de días por mes.
    script_dir (str): Directorio raíz del script.
    anio_scrappeo (int): Año de referencia.
    dataframeTemporal (pd.DataFrame): Acumulador temporal de datos durante el scraping.
    todas_columnas (set): Conjunto de todas las columnas detectadas en los XML.
"""

import os
from bs4 import BeautifulSoup
import requests
from datasets import Dataset
import csv
import PyPDF2
from io import BytesIO
from urllib.parse import urljoin
import re
import pandas as pd
import pytesseract
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
import clize
from datetime import datetime
import shutil

base_enlace = "https://www.boe.es/diario_boe/xml.php?id=BOE-"
pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")

#Cambiar fecha de lectura cada dia

calendario = {    #Calendario para poder recorrer todos los dias del año
    1: list(range(1, 31)),
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

pdfs_path = ""
xmls_path = ""
leido_ocr_path = ""
poppler_path_ = f"C:/Program Files/poppler/Library/bin"
anio_scrappeo = 2025

#Con esto tomamos la ruta donde esta el script
script_dir = os.path.dirname(os.path.abspath(__file__))

todas_columnas = set()

dataframeTemporal = pd.DataFrame()

def limpiar_texto(texto):
    """Elimina espacios redundantes y saltos de línea en cadenas de texto.

    Args:
        texto (str): Texto crudo.

    Returns:
        str: Texto saneado.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):   #Guardar el enlace de errores por timeout del boe
    """Registra una URL fallida en un archivo de log.

    Args:
        archivo_errores (str): Ruta del archivo de log (sin extensión `.txt`).
        url_dia (str): URL a registrar.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_error):   #Intento de petición modularizado para acceder a todas las páginas
    """Ejecuta una petición GET con reintentos ante caídas HTTP.

    Args:
        url_buscar (str): URL a consultar.
        ruta_error (str): Ruta del log de errores (sin extensión).

    Returns:
        requests.models.Response | None: Respuesta HTTP o None en caso de error.
    """
    try:
        respuesta = requests.get(url_buscar)
        if respuesta.status_code == 200:
            return respuesta

        elif respuesta.status_code == 404:
            return respuesta
        else:
            for i in range(5):
                print(f"No se pudo acceder a {url_buscar}: reintentamos")
                time.sleep(i+1)
                respuesta = requests.get(url_buscar) 
                if respuesta.status_code == 200:
                    print("Se ha aceptado el reintento de conexion")
                    break
            
            escribir_url_errores(ruta_error, url_buscar)
            return respuesta
        
    except requests.exceptions.RequestException  as e:
        print(f"Error al acceder al url: {e}")
        escribir_url_errores(ruta_error, url_buscar)

def descargarXml_pdf(base_dir_xml, base_dir_pdfs, enlaceXML,anio,mes,dia,decreto,apartado, ruta_error):
    """Descarga el XML de un decreto del BOE y extrae su PDF asociado.

    A partir de la URL del XML obtiene el contenido, lo guarda en disco y extrae
    la URL del PDF desde el campo `url_pdf` del XML para descargarlo.

    Args:
        base_dir_xml (str): Directorio de destino de los XMLs.
        base_dir_pdfs (str): Directorio de destino de los PDFs.
        enlaceXML (str): URL del XML del decreto.
        anio (int): Año del decreto.
        mes (int): Mes del decreto.
        dia (int): Día del decreto.
        decreto (str): Número o código del decreto.
        apartado (str): Sección del BOE (`A` o `B`).
        ruta_error (str): Ruta del log de errores.
    """
    
    global contadorSalvaguarda
    global dataframeTemporal
    global cambio_dia

    try:
        response_xml = requests.get(enlaceXML)
        contenido = response_xml.content
    except:
        print("No se puede tomar el contenido de content")

    xml_filename = f"BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}.xml"
    xml_path = os.path.join(base_dir_xml,xml_filename)

    pdf_file = f"BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}.pdf"
    pdf_path = os.path.join(base_dir_pdfs, pdf_file)

    if os.path.exists(xml_path):   #Comprobamos que no este el fichero ya descargado
        print(f"El archivo {xml_filename} ya existe. Se omite la descarga.")
    else:
        try:
            response_xml = intentar_peticion(enlaceXML, ruta_error)   #intentamos peticion a pagina y descargamos
            if response_xml.status_code == 200:
                contenido = response_xml.content
                with open(xml_path, "wb") as xml_file:
                    xml_file.write(response_xml.content)
                    print(f"Xml descargado BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}")
                    almacenar_en_csv(response_xml)
                
        except Exception as e:
            print(f"Error descargando el XML: {e}")

    if os.path.exists(pdf_path):
        print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
    else:
        try:
            # Accedemos al pdf leyendo todo el xml
            raiz = ET.fromstring(contenido)
            url_pdf = None
            for elemento in raiz.findall(".//url_pdf"):   #Obtenemos el enlace del pdf, desde el xml
                url_pdf = elemento.text
                break

            url_dec_pdf = f"https://www.boe.es/{url_pdf}"
            descargarPDF(base_dir_pdfs, url_dec_pdf, anio, mes, dia, decreto, apartado, ruta_error)
        except Exception as e:
            print(f"No se ha podido descargar el pdf: {e}")    

def almacenar_en_csv(response_xml):
    """Parsea el contenido XML de un decreto y lo acumula en el DataFrame temporal global.

    Extrae todos los tags del XML como columnas, aplica limpieza de texto y concatena
    el resultado al `dataframeTemporal` global.

    Args:
        response_xml (requests.models.Response): Respuesta HTTP con el contenido XML del decreto.
    """
    global dataframeTemporal
    global todas_columnas

    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day

    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"    #Obtenemos fecha actual para guardar en el csv

    try:   
        datos_para_xml = BeautifulSoup(response_xml.content, "lxml-xml")
        decreto_data = {}
        todos_datos = []

        for element in datos_para_xml.find_all(True):   #obtenemos todas las columnas
            if element.name not in todas_columnas:
                todas_columnas.add(element.name)

            decreto_data[element.name] = element.get_text().strip()

        decreto_data["fecha_lectura"] = fecha_lectura

        todos_datos.append(decreto_data)
        df = pd.DataFrame(todos_datos, columns=list(todas_columnas))
        
        for col in df.columns:
            df[col] = df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

        dataframeTemporal = pd.concat([dataframeTemporal, df], ignore_index=True, sort=False)   #unimos con el dataframe temporal

    except Exception as e:
        print(f"Error al procesar el csv: {e}")

def Guardar_Contenido(df, base_dir_csv, anio_scrappeo):
    """Guarda o anexa el DataFrame al CSV acumulativo del año.

    Args:
        df (pd.DataFrame): DataFrame con los datos del día a guardar.
        base_dir_csv (str): Directorio del CSV de salida.
        anio_scrappeo (int|str): Año para el nombre del archivo CSV.
    """
    if not df.empty:
        archivo_csv = f"{base_dir_csv}/{anio_scrappeo}.csv"

        if os.path.exists(archivo_csv):  
            df_existente = pd.read_csv(archivo_csv, encoding='utf-8', low_memory=False)
            df_combinado = pd.concat([df_existente, df], ignore_index=True, sort=False)
            df_combinado.to_csv(archivo_csv, index=False, encoding='utf-8')  
        else:
            df.to_csv(archivo_csv, index=False, encoding='utf-8') 

        print("Guardamos el dataframe temporal")

def descargarPDF(base_dir_pdfs, enlacePDF,anio,mes,dia,decreto,apartado, ruta_error):
    """Descarga el PDF de un decreto del BOE desde su URL.

    Args:
        base_dir_pdfs (str): Directorio de destino de los PDFs.
        enlacePDF (str): URL completa del PDF.
        anio (int): Año del decreto.
        mes (int): Mes del decreto.
        dia (int): Día del decreto.
        decreto (str): Número o código del decreto.
        apartado (str): Sección del BOE (`A` o `B`).
        ruta_error (str): Ruta del log de errores.
    """
    #Guardamos el pdf

    pdf_file = f"BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}.pdf"
    pdf_path = os.path.join(base_dir_pdfs, pdf_file)

    try:
        response_pdf = requests.get(enlacePDF, stream=True)
        response_pdf = intentar_peticion(enlacePDF, ruta_error)
        if response_pdf.status_code == 200:
            with open(pdf_path, "wb") as pdf_file:
                for chunk in response_pdf.iter_content(chunk_size=8192):
                    pdf_file.write(chunk)
                print(f"PDF descargado decreto : BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}")

        # Descomentar para realizar el scrapeo
        # leer_y_guardar_pdf_tesseract(enlacePDF, ruta_ocr_pdfs, anio, mes, dia, decreto, apartado)

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def busca_xml(base_dir_xml, base_dir_pdfs, href, anio, mes, dia, ruta_error):
    """Detecta si un enlace a apunta a un XML del BOE y lanza la descarga.

    Args:
        base_dir_xml (str): Directorio de los XML.
        base_dir_pdfs (str): Directorio de los PDF.
        href (str): Valor del atributo `href` del enlace analizado.
        anio (int): Año del boletin.
        mes (int): Mes del boletin.
        dia (int): Día del boletin.
        ruta_error (str): Ruta del log de errores.
    """
    
    if "xml" in href.lower():          # Entramos al xml
        enlaceALXML = f"https://www.boe.es{href}"
        decreto = enlaceALXML.split("-")[-1]    #Extraemos el decreto que es
        apartado = re.search(r"id=BOE-([AB])", enlaceALXML).group(1)  #Cogemos tambien el apartado

        descargarXml_pdf(base_dir_xml, base_dir_pdfs, enlaceALXML, anio, mes, dia, decreto, apartado, ruta_error)  

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Orquestador del scraping del BOE.

    Itera año a año desde `anio_scrappeo` hasta 2024 y por cada día del calendario
    accede a la página del BOE, extrae los enlaces a XMLs de decretos y descarga cada
    par XML + PDF. Al terminar cada día guarda el DataFrame acumulado en CSV.

    Args:
        anio_scrappeo (int, kwarg): Año de inicio del scraping.
    """
    global cambio_dia
    global dataframeTemporal
    global todas_columnas

    todas_columnas.add("fecha_lectura")

    for anio in range(anio_scrappeo,2025): #Modificar el año si queremos ejecutar más terminales

        ruta_ocr_pdfs = os.path.join(script_dir, f"{anio_scrappeo}", "OCR_pdfs")
        base_dir_xml = os.path.join(script_dir, f"{anio_scrappeo}", "Decretos_xml")
        base_dir_pdfs = os.path.join(script_dir, f"{anio_scrappeo}", "Decretos_pdfs")
        base_dir_csv = os.path.join(script_dir, f"{anio_scrappeo}_csv")
        ruta_archivo_errores = os.path.join(script_dir, f"{anio_scrappeo}_url_errores")

        carpetas = [ruta_ocr_pdfs, base_dir_xml, base_dir_pdfs, base_dir_csv, ruta_archivo_errores]

        # Crear las carpetas si no existen
        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        for mes in calendario:            #leemos cada mes
            for dia in calendario[mes]:   #leemos cada dia

                #Definimos el url
                print(f"Entramos al dia: {dia} mes: {mes} anio: {anio}")
                url_buscar = f"https://www.boe.es/boe/dias/{anio}/{mes:02}/{dia:02}/"

                try:
                    respuesta = intentar_peticion(url_buscar, ruta_archivo_errores)
                    if respuesta.status_code == 200:
                        print("Entramos a la pagina del dia")
                        soup = BeautifulSoup(respuesta.text, 'html.parser')
                        enlaces = soup.find_all('a', href=True)   # Con esto accedo a todos los enlaces q haya
                        for enlace in enlaces:
                            href = enlace['href']
                            if 'txt.php' in href.lower():          #Con esto entramos a la pagina del decreto
                                time.sleep(0.5)                         #Intentamos aumentar el tiempo entre peticiones
                                url_php = f"https://www.boe.es{href}"
                                respuesta_php = intentar_peticion(url_php, ruta_archivo_errores)
                                if respuesta_php.status_code == 200:
                                        soupPhp = BeautifulSoup(respuesta_php.text, 'html.parser')   #Buscamos en la pagina el xml y el pdf
                                        enlacesXml = soupPhp.find_all('a', href=True)

                                        for enlacexml in enlacesXml:
                                            hrefXml = enlacexml['href']
                                            busca_xml(base_dir_xml, base_dir_pdfs, hrefXml,anio, mes, dia, ruta_archivo_errores)            
                                            continue  

                        print("Este es el ultimo enlace")
                        Guardar_Contenido(dataframeTemporal, base_dir_csv, anio_scrappeo)
                        dataframeTemporal = pd.DataFrame()             

                except Exception as e:
                    print(f"Error procesando {url_buscar}: {e}")

    print("Guardamos el contenido del temporal por si hay algo más")
    Guardar_Contenido(dataframeTemporal, base_dir_csv, anio_scrappeo)
    dataframeTemporal = pd.DataFrame() 

def leer_y_guardar_pdf_tesseract(ruta_pdf, ruta_texto, anio, mes, dia, decreto, apartado):
    """Extrae el texto de un PDF usando OCR Tesseract y guarda el resultado en un archivo `.txt`.

    Args:
        ruta_pdf (str): Ruta al PDF local.
        ruta_texto (str): Directorio de destino del archivo de texto OCR.
        anio (int): Año del decreto.
        mes (int): Mes del decreto.
        dia (int): Día del decreto.
        decreto (str): Número o código del decreto.
        apartado (str): Sección del BOE (`A` o `B`).
    """
    try:
        # Convertir el PDF en imágenes
        print(f"Leemos el pdf de: {ruta_pdf}")
        imagenes = convert_from_path(ruta_pdf, dpi=300, poppler_path=poppler_path_)
        
        texto_total = ""
        ruta_pdf_pcr = os.path.join(ruta_texto, f"BOE-{apartado}-{anio}-{mes}-{dia}-Decreto-{decreto}.txt")
        for i, imagen in enumerate(imagenes):                        # Usar Tesseract OCR para extraer texto de cada imagen
            texto = pytesseract.image_to_string(imagen, lang="spa")       # "spa" es para español
            texto_total += texto

        # Guardar el texto extraído en un archivo
        with open(ruta_pdf_pcr, "w", encoding="utf-8") as archivo_texto:
            archivo_texto.write(texto_total)
        
        print(f"Texto del pdf tras OCR guardado en: {ruta_pdf_pcr}")
    except Exception as e:
        print(f"Error procesando el PDF: {e}")

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


