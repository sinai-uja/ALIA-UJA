"""Recolector del Boletín Oficial de la Provincia de Jaén (BOP Jaén).

Este script automatiza la extracción sistemática de datos y descarga masiva de documentos
del BOP Jaén publicadas en formato PDF y HTML.
Recorre subpáginas web navegando anualmente y a través de calendarios predefinidos locales iterando días y meses.
Identifica y extrae "Rectificación de Errores" fuera del DOM normal seccionado. Descarga masiva paralela textual
y su respectivo PDF, en inyección opcional PyMuPDF evaluativa para fallas nativas, además de compresión Parquet / Zip final.

Attributes:
    anio_scrappeo (int): Marcador inicial base en la configuración general (Ej. 2000).
    script_dir (str): Directorio raíz del script donde se almacenan PDFs y CSVs temporales/finales.
    calendario (dict): Referencia de días sobre los doce meses para iteración continua.
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
import os
from pdf2image import convert_from_path
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import zipfile


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

def limpiar_texto(texto):
    """Estiliza los campos base decodificados borrando espacios múltiples y retornos.

    Args:
        texto (str): Cadena en formato crudo obtenida por BeautifulSoup u otra instancia.

    Returns:
        str: Segmento depurado sin ruidos visuales inyectables espurios.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto puro leyendo la capa incrustada directamente usando `PyMuPDF` (fitz).

    Pide un límite mínimo analítico de caracteres y libera memoria llamando a `gc.collect()`.

    Args:
        pdf_path (str): Sendero absoluto al documento físico descargado.
        min_chars (int, optional): Cuota condicional mínima alfanumérica de aceptación de validación. Default a 50.

    Returns:
        tuple[str, bool]: Texto crudo extraído y booleano confirmando si sobrepasa `min_chars`.
    """
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

def escribir_url_errores(archivo_errores, url_dia):
    """Estampa enlaces caídos o fallidos absolutos en un registro de texto plano histórico.

    Args:
        archivo_errores (str): Path de archivo resolutor. Omitir extensión `.txt`.
        url_dia (str): Valor textual de la URL que falló tras retries.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Protege y elabora peticiones GET bajo soporte asíncrono-latencias con bucle for de tolerancia a fallos.

    Contempla las caídas directas `ChunkedEncodingError` generadas por cortes nativos del anfitrión Web.

    Args:
        url_buscar (str): Meta de localización HTTP(s).
        ruta_errores (str): Senda sin extensión destino al '.txt'.

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
    """Fusiona y persiste pandas DataFrames únicos localmente en el tabulado general de su respectivo anio.

    Args:
        df (pd.DataFrame): Cuadro aislado procesado sobre metadata CSV.
        ruta (str): Directorio matriz.
        anio (int|str): Identificador nomenclativo puro.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Consuma bytes remotos del servidor empaquetándolos al HDD.

    Args:
        response_pdf (requests.models.Response): Instancia base devuelta validada previamente en `intentar_peticion()` Streamable.
        enlacePDF (str): Nomenclatura local absoluta en C:/ de depósito inamovible.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha_decreto, seccion, subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Fusión analítica tabular lista extraída en una iteración única.

    Args:
        identificador (str): Etiqueta posicional natural correlativa.
        fecha_decreto (str): Referencia natural temporal en sistema `DD-MM-AAAA`.
        seccion (str): Escalafón mayor HTML seccionado (Padre).
        subseccion (str): Escalafón orgánico interno emisor del texto.
        contenido_text (str): Lo empaquetado y resuelto de PDF incrustado `fitz` PyMuPDF.
        enlace_pdf (str): El puente unívoco PDF al servidor activo.
        ruta_guardar_pdf (str): Depositario temporal local en sistema.

    Returns:
        pd.DataFrame: DataFrame mono-escala con inserción base saneada.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "fecha_decreto": fecha_decreto,
        "seccion": seccion,
        "subseccion": subseccion,
        "contenido": contenido_text,
        "url": enlace_pdf,
        "fecha_lectura": fecha_lectura,
        "ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Orquestador maestro iterativo cruzando días del calendario sobre "bop.dipujaen.es".

    Recorre el DOM con parseador de Python general BS4 en búsqueda de index HTML con etiquetas de error
    `Rectificación de Errores` en un bloque condicional aislado superior que atiende un problema del host local.
    Seguidamente desciende buscando resoluciones internas jerárquicas nominales (`seccion`, `subseccion`, `edicto`).
    Incorpora compendio local y compresión de archivos anual a sistema finalizado robusto (`parquet`, `zip`).

    Args:
        anio_scrappeo (int, kwarg): Marcador cronológico que actúa como base de arranque masivo inyectando 1 año `+1`.
    """

    ruta_csv_actual = ""
    for anio in range(anio_scrappeo,anio_scrappeo+1): 
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
                print("Leemos el mes...")

        print(f"EMPEZAMOS POR EL DIA -> {dia_leido}-{mes_leido}-{anio}")

        for mes in range(mes_leido, 13):  
            dias_mes = calendario.get(mes, [])

            for dia in dias_mes[dia_leido-1:]:   #leemos cada dia
                try: 
                    base_enlace = f"https://bop.dipujaen.es/bop/{dia:02}-{mes:02}-{anio}"
                    print(f"Entramos al enlace: {base_enlace}")
                    
                    respuesta_enlace, encontrado_enlace = intentar_peticion(base_enlace, ruta_archivo_errores)
                    if encontrado_enlace == 1 and respuesta_enlace and respuesta_enlace.status_code == 200:
                        soup = ""
                        try: 
                            soup = BeautifulSoup(respuesta_enlace.text, 'html.parser')
                        except:
                            print("No se ha podido parsear el boletin")
                        
                        sumario_boletin = soup.find("div", id = "sumarioBoletin")
                        
                        if sumario_boletin:
                            rectificacion = soup.find("p", class_="seccion")
                            texto_rectifica = rectificacion.text

                            if texto_rectifica == "Rectificación de Errores":
                                print(f"Encontrada una rectificación del boletin, descargamos")
                                nombre_rectificacion = texto_rectifica
                                subseccion_rectifica = rectificacion.find_next_sibling().text
                                decreto_rectificado = soup.find("p", class_="edicto")
                                acceso_pdf_re = soup.find("p", attrs={"style": "text-align: center"})
                                identificador_re = f"BOP-{anio}-Boletin-{numero_boletin}-Seccion-{0}-Decreto-{0}"
                                enlace_pdf_re = acceso_pdf_re.find('a')['href']

                                if enlace_pdf_re:
                                    respuesta_pdf_re, encontrado_pdf_re = intentar_peticion(enlace_pdf_re, ruta_archivo_errores)
                                    if encontrado_pdf_re == 1 and respuesta_pdf_re and respuesta_pdf_re.status_code == 200:
                                        ruta_guardar_pdf_re = f"{base_dir_pdfs}\{identificador_re}.pdf"
                                        descargar_pdf(respuesta_pdf_re, ruta_guardar_pdf_re)
                                        texto_pdf_re, exito_re = extract_text_direct(ruta_guardar_pdf_re)
                                        
                                        if exito_re:
                                            df_re = crear_df_temporal(identificador_re, f"{dia}-{mes}-{anio}", nombre_rectificacion, subseccion_rectifica, texto_pdf_re, enlace_pdf_re, ruta_guardar_pdf_re)
                                            guardar_contenido_csv(df_re, base_dir_csv, anio)
                                            ruta_csv_actual = f"{base_dir_csv}/{anio}.csv"
                                            print(f"Guardamos contenido del decreto -> Boletin-{numero_boletin}-Secc-{0}-Dec-{0}")

                            secciones_sumario = sumario_boletin.find_all("section")

                            seccion_actual = ""
                            subseccion_actual = ""
                            num_seccion = 0
                            num_decreto = 0

                            for secciones in secciones_sumario:
                                num_seccion += 1
                                num_decreto = 0
                                todas_etiquetas = secciones.find_all()
                                for etiqueta in todas_etiquetas:
                                    if etiqueta.name == 'p':
                                        clase = etiqueta.get('class')  
                                        if clase != None:
                                            if clase[0] == 'seccion':
                                                seccion_actual = etiqueta.text
                                                print(f"Seccion Actual: {seccion_actual}")
                                            elif clase[0] == 'subseccion':
                                                subseccion_actual = etiqueta.text
                                                print(f"Subseccion Actual: {subseccion_actual}")
                                    elif etiqueta.name == 'article':
                                        num_decreto += 1
                                        identificador = f"BOP-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                        resumen_edicto = etiqueta.find("p", class_="edicto")
                                        acceso_pdf = etiqueta.find("p", attrs={"style": "text-align: center"})
                                        enlace_pdf = acceso_pdf.find('a')['href']

                                        if enlace_pdf:
                                            respuesta_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                            if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                                ruta_guardar_pdf = f"{base_dir_pdfs}\{identificador}.pdf"
                                                if not os.path.exists(ruta_guardar_pdf):
                                                    descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                                    texto_pdf, exito = extract_text_direct(ruta_guardar_pdf)
                                                    time.sleep(1.2)
                                                    
                                                    df = crear_df_temporal(identificador, f"{dia}-{mes}-{anio}", seccion_actual, subseccion_actual, texto_pdf, enlace_pdf, ruta_guardar_pdf)
                                                    guardar_contenido_csv(df, base_dir_csv, anio)
                                                    ruta_csv_actual = f"{ruta_csv_actual}/{anio}.csv"
                                                    print(f"Guardamos contenido del decreto -> Boletin-{numero_boletin}-Secc-{num_seccion}-Dec-{num_decreto}")

                                    else:
                                        time.sleep(0.1)
                            numero_boletin += 1
                            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                f.write(f"{mes_leido},{dia_leido},{numero_boletin}")  #leemos el dia y el mes
                        else:
                            print(f"El dia: {dia}-{mes}-{anio}: No contiene decretos")
                    
                    else:
                        print(f"La página del boletín {numero_boletin} no existe")

                except Exception as e:
                    print(f"Error inesperado en el día {dia}: {e}")
                    continue

                except ChunkedEncodingError as e:
                    print(f"Error en la transferencia de datos: {e}")
                    continue
            
                except requests.exceptions.RequestException as e:
                    print(f"Intento rechazado")
                    continue
        
         # Convertir CSV a Parquet
        parquet_path = f"{base_dir_csv}/{anio}.parquet"
        try:
            if os.path.exists(ruta_csv_actual):
                df = pd.read_csv(ruta_csv_actual, encoding='utf-8')
                df.to_parquet(parquet_path, index=False)
                print(f"✅ CSV convertido a Parquet: {parquet_path}")
        except Exception as e:
            print(f"❌ Error al convertir CSV a Parquet para el año {anio}: {e}")

        # Crear un ZIP que agrupe todos los archivos del año
        zip_path = os.path.join(script_dir, f"{anio}.zip")
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # Añadir el archivo parquet al ZIP
                if os.path.exists(parquet_path):
                    zipf.write(parquet_path, os.path.basename(parquet_path))
                    zipf.write(ruta_csv_actual, os.path.basename(ruta_csv_actual))
                print(f"✅ Archivo ZIP creado: {zip_path}")
        except Exception as e:
            print(f"❌ Error al crear el archivo ZIP para el año {anio}: {e}")
        
        dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


