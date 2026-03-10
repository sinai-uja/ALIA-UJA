"""Recolector del Boletín Oficial de la Provincia de Jaén (BOP).

Este script automatiza la extracción sistemática de datos y descarga masiva de documentos
del BOP Jaén publicadas en formato PDF y HTML.
Recorre subpáginas web navegando anualmente y a través de calendarios predefinidos locales iterando días y meses.
Identifica y extrae "Rectificación de Errores" fuera del DOM normal seccionado. Descarga masiva paralela textual
y su respectivo PDF, en inyección opcional PyMuPDF evaluativa para fallas nativas.
Adicionalmente incorpora paquetería tolerante (Requests Chunked y logs txt persistentes sobre urls caídas).

Attributes:
    anio_scrappeo (int): Marcador inicial base en la configuración general.
    script_dir (str): Directorio del cual se ejecuta el script.
    calendario (dict): Formato referencial de iteración temporal de días sobre los doce meses del año.
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
        texto (str): Cadena en formato crudo obtenida por BeautifulSoup u otra instancia de Scraper.

    Returns:
        str: Segmento depurado sin ruidos visuales inyectables.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto puro leyendo la capa incrustada directamente usando `PyMuPDF` (fitz).

    Pide un límite mínimo analítico de caracteres. Invoca antes forzosamente `gc.collect()` para liberar 
    posible saturación RAM. 

    Args:
        pdf_path (str): Sendero base al documento físico descargado.
        min_chars (int, optional): Cuota condicional mínima alfanumérica de aceptación de validación. Default a 50.

    Returns:
        tuple[str, bool]: Texto en buffer string crudo y booleano indicando que existo con los `min_chars`. Vacío si falla o cae debajo del parámetro.
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
    """Loguea y estampa links defectuosos o resoluciones del BOP vacías en registro maestro histórico.

    Args:
        archivo_errores (str): Path sin extensión donde acantonar las url con fallo absoluto terminal HTTP.
        url_dia (str): Valor fallido.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Protege y abre sesión Request aislada para soportar caídas directas o latencias temporales.

    Engloba protecciones de flujo para Stream Chunked al Host nativo de Diputación de Jaén y recicla peticiones web fallidas mediante descansos `time.sleep()`.

    Args:
        url_buscar (str): Meta estricta HTTP URL base a consultar.
        ruta_errores (str): Destino ".txt" hacia el que desviar logs en caso terminal tras 5 caídas duras del request loop.

    Returns:
        tuple[requests.models.Response | None, int]: Dupla matriz estructurada de la petición (Obj. Web Response / o None null) y la señal en bits nominal (1 - exito / 0 - caida irrecuperable).
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
    """Cuelga masivamente de una llamada una fila data frame local temporal hacia el compendio unifilar anual CSV de la matriz genérica local.

    Args:
        df (pd.DataFrame): Dataform extraído aislado resuelto y depurado unitario sobre su fila.
        ruta (str): Directorio raíz del año donde reside el CSV base.
        anio (int|str): Identificador nomenclativo puro natural o de subdirectorios para armar correlación de index.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Transfiere y asienta la lectura binaria web sobre un stream particionado físico local al vuelo.

    Args:
        response_pdf (requests.models.Response): Origen web Stream directo asimilable en iteradores.
        enlacePDF (str): Nombramiento y localización base C// de la run en curso.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha_decreto, seccion, subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Construcción analítica tabular final limpia serializable en el bucle iterador BOP para volcar un dato al CSV.

    Args:
        identificador (str): Placa estática sintética cruzando origen textual "BOP" + año + boletín de turno + seccion + decreto.
        fecha_decreto (str): Referencia natural estática formateada (dia-mes-(anio)).
        seccion (str): Rama clasificador general matriz de jerarquía en página (Padre).
        subseccion (str): Escala secundaria o nula si aplica de organismos de junta general de origen del decreto unitario.
        contenido_text (str): Lo empaquetado y resuelto de PDF incrustado `fitz`.
        enlace_pdf (str): Link persistente externo extraído en página que redirige al binario nativo oficial red.
        ruta_guardar_pdf (str): Extrapolación matriz ruta interna C// para uso local directo en el entorno actual.

    Returns:
        pd.DataFrame: Tabulación única sanitizada lista con todas las cabeceras relacionales base de metadatos integradas.
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
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Iniciador matriz masivo asíncrono sobre ecosistema portal estricto provincial BOP_Jaen.

    Orquesta barridos completos desde el `anio_scrappeo` de fondo avanzando secuencialmente.
    Asume por default la base url "bop.dipujaen.es". Mapea el DOM con tolerante HTTP `chunk` iterativo bs4 HTML parser general.
    Contempla la irregularidad web regional detectando resoluciones externas o anómalas puestas a la misma escala de jerarquías listadas
    como `Rectificación de Errores` ignorando clasificados y anexándolas extra temporalmente por debajo a la pila CSV.
    Extrae, comprueba pdf local inyectando capa textual pyMupdf e inyecta pandas sobre los `error_log` por cada descarte web inútil u opaco local a PDF.

    Args:
        anio_scrappeo (int, kwarg): Marcador cronológico que actúa como base cero de run e inyección matriz a los directorios anidados.
    """

    for anio in range(anio_scrappeo,anio_scrappeo+7): 
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
                                                    
                                                    if exito:
                                                        df = crear_df_temporal(identificador, f"{dia}-{mes}-{anio}", seccion_actual, subseccion_actual, texto_pdf, enlace_pdf, ruta_guardar_pdf)
                                                        guardar_contenido_csv(df, base_dir_csv, anio)
                                                        print(f"Guardamos contenido del decreto -> Boletin-{numero_boletin}-Secc-{num_seccion}-Dec-{num_decreto}")
                                                    else:
                                                        with open(f"{base_anio}\error_log.txt", "a") as f:
                                                            f.write(f"Error en la lectura del pdf con id:: {identificador}")

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
        dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


