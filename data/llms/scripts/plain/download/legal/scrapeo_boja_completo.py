"""Recolector del Boletín Oficial de la Junta de Andalucía (BOJA) Completo.

Este script automatiza la extracción sistemática de datos y descarga masivos de documentos
del BOJA. Recorre anualmente el histórico de boletines iterando de forma continua días y años.
Utiliza peticiones HTTP y BS4 para detectar fallos temporales y 404 estables de cierre.
Implementa rescate explícito general `descargar_errores_anio` y una lectura de respaldo mixto de 
OCR con Tesseract y lectura directa con PyMuPDF (a petición). Construye persistentes CSV de base 
fusionada de html directo extraíble.

Attributes:
    anio_scrappeo (int): El año inicial a procesar y descargar masivamente (Ej: 1979).
    script_dir (str): Directorio del cual se ejecuta el script. Actúa como base inmutable en rutas.
    dataframe_guardado (pd.DataFrame): Objeto DF de uso interno en la asignación general opcional.
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
from requests.exceptions import ChunkedEncodingError
import polars as pl
import pytesseract
import glob
import fitz  # PyMuPDF
import concurrent.futures
from tqdm import tqdm
import sys
import gc
import shutil

pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")
dataframe_guardado = pd.DataFrame()
anio_scrappeo = 1979
script_dir = os.path.dirname(os.path.abspath(__file__))

def limpiar_texto(texto):
    """Elimina tabulaciones colapsables, espacios múltiples consecutivos y saltos de línea irregulares.

    Args:
        texto (str): Segmento extraído crudo de una lectura general.

    Returns:
        str: Texto uniforme concatenado de un solo espacio en cadena.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Establece un rastro de las urls caídas o rechazadas persistido en el documento "url_errores.txt".

    Args:
        archivo_errores (str): Directorio absoluto general apuntando explícitamente a su fichero dependiente o padre base, pero eximiendo `.txt`.
        url_dia (str): La URL final objetivo que desencadenó en red problemas HTTP o caídas irrecuperables.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Resuelve la recolección HTTP GET tolerando cierres SSL y latencias web esporádicas.

    Inyecta reintentos exponenciales secuenciales (de base 5 iteraciones seguidas).
    Identifica formalmente y omite los bloqueos ciegos web del BOJA o sus errores de conexión en fragmentaciones caídas (ChunkedEncodingError).

    Args:
        url_buscar (str): Endpoint primario rastreado (generalmente html de un decreto local o índice del día/boletín).
        ruta_errores (str): Sendero padre para inyecciones manuales a fallos definitivos a escribir.

    Returns:
        tuple[requests.models.Response | None, int]: Matriz de respuesta y validación (1 exitosa general (incluso 404 nativo BOJA o vacíos válidos)).
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

def descargar_html(response, path):
    """Descarga el contenido de un boletín o texto puro procesado HTML directo a disco local.

    Args:
        response (requests.models.Response): Bloque original HTTP decodificable crudo.
        path (str): Vía del archivo final .html para volcar.
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Archivo HTML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo HTML en {path}: {e}")

def guardar_contenido_csv(df, ruta, anio):
    """Comprime de forma tabular un dataframe entero y deposita anexando dentro al sistema CSV del anio corriente BOJA.

    Construye las cabeceras condicionalmente si acaba de crearlo o simplemente sigue escribiendo los renglones masivos a posteriori.

    Args:
        df (pd.DataFrame): Matriz formateada completa resultante del indexer del parser temporal.
        ruta (str): Directorio raíz del año donde reside el CSV.
        anio (int|str): Nomenclatura pura para la compilación nominal del año referencial analógico.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Guardamos en el csv...")

def descargar_pdf(response_pdf, enlacePDF):
    """Recibe y compone el volúmen físico masivo PDF en el directorio temporal o persistente local.

    Args:
        response_pdf (requests.models.Response): Data original generacional o de descarga cruda referencial validada en 8192 chunks fijos.
        enlacePDF (str): Nombramiento y localización final para el archivo en red interna de disco.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha_decreto, Seccion, Subseccion, Subsubseccion, Contenido, Contenido_pdf, pdf_enlace, disposciones, resumen, contenido_completo):
    """Encapsulamiento Pandas estandarizado de recolector maestro adaptado a la taxonomía única jerárquica histórica del BOJA.

    Inyecta de forma masiva en limpieza de base campos relacionales textuales como resumen de red (bs4), OCR PDF y cruces de metadatos profundos combinados en su columna base `text`.

    Args:
        identificador (str): Matrícula o etiqueta correlativa posicional a lo largo de un año del BOJA.
        fecha_decreto (str): Referencial del boletín que alinea de dónde extrajo internamente en la página del día dicho valor.
        Seccion (str): H2 o derivado agrupador padre central de la Junta.
        Subseccion (str): H3 o agrupador descendiente de organismos internos en la junta.
        Subsubseccion (str): H5 resolutivo en su defecto, menor escala de indexado BOJA.
        Contenido (str): Cuerpo sustraído directo vía BeautifulSoup evadiendo cajas de alerta inútiles incrustadas.
        Contenido_pdf (str): Capa incrustada del procesador general o Pymupdf en su forma pura, si aplicase en su ciclo interno del script principal.
        pdf_enlace (str): Hiperenlace rastreado y conservado desde `.item_pdf_disposicion`.
        disposciones (str): Hiperenlace de iteración HTML origen usado de la página (La meta resolución web en vivo del decreto analizado).
        resumen (str): Introductorio directo textual desprovisto en forma previa a `Contenido`.
        contenido_completo (str): El volumen crudo de `Contenido\n` concatenado ciegamente a `Contenido_pdf`.

    Returns:
        pd.DataFrame: Conjunto serializado local tabulado listo y provisto de estandarización genérica para append final masivo anual.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Seccion": Seccion,
        "Subseccion": Subseccion,
        "Subsubseccion": Subsubseccion,
        "Resumen": resumen,
        "Contenido": Contenido,
        "Pdf_text": Contenido_pdf,
        "text": contenido_completo,
        "Url_pdf": pdf_enlace,
        "Url_html": disposciones,
        "Fecha_lectura": fecha_lectura,
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def descargar_errores_anio():
    """Analizador reparador de contingencia focalizado enteramente en la limpieza paralela de URLs fallidas históricas en el BOJA.

    Bucle interno reparador y subyacente que reabre `url_errores.txt` general y recorre todos su interior anualmente volviendo
    a tratar de recomponer el metadato parcial ignorado localmente y el reintento paralelo HTTP masivo HTML, CSV, TXT o PDFs. 
    Actúa reconstruyendo su nombre analizando con RE (`Regex`) el token nominal interno natural BOJA en la url del error caído originario.
    """
    for anio in range(anio_scrappeo, anio_scrappeo + 1):
        ruta_errores = os.path.join(script_dir, f"{anio}", "url_errores.txt")
        base_dir_pdfs = os.path.join(script_dir, f"{anio}", "PDF")
        base_dir_html = os.path.join(script_dir, f"{anio}", "HTML")
        base_dir_txt = os.path.join(script_dir, f"{anio}", "TXT")
        base_dir_csv = os.path.join(script_dir, f"{anio}")
        ruta_relativa_txt = f"/{anio}/TXT"
        ruta_relativa_html = f"/{anio}/HTML"
        ruta_relativa_pdf = f"/{anio}/PDF"

        if not os.path.exists(ruta_errores):
            print(f"No se encontró el archivo de errores para el año {anio}")
            continue

        with open(ruta_errores, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip()]

        if not urls:
            print(f"No hay URLs de error que procesar para {anio}")
            return

        print(f"Reintentando scraping de {len(urls)} URLs con error del año {anio}...")

        for url in urls:
            try:
                time.sleep(0.5)
                respuesta, encontrada = intentar_peticion(url, ruta_errores)
                if encontrada == 1 and respuesta and respuesta.status_code == 200:
                    soup = BeautifulSoup(respuesta.text, "html.parser")

                    # Extraer datos básicos
                    identificador = re.search(r'BOJA-\d+-Boletin-\d+-S-\d+-Dec-\d+', url)
                    if identificador:
                        identificador = identificador.group()
                    else:
                        identificador = "BOJA-ErrorManual"

                    pdf_file = f"{identificador}.pdf"
                    html_file = f"{identificador}.html"
                    pdf_path = os.path.join(base_dir_pdfs, pdf_file)
                    enlace_almacena_html = os.path.join(base_dir_html, html_file)

                    # PDF
                    try:
                        pdf_enlace = soup.find('a', class_='item_pdf_disposicion')['href']
                        if pdf_enlace and not os.path.exists(pdf_path):
                            respuesta_pdf, encontrada_pdf = intentar_peticion(pdf_enlace, ruta_errores)
                            if encontrada_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                descargar_pdf(respuesta_pdf, pdf_path)
                    except Exception:
                        pdf_file = None
                        pdf_enlace = None

                    # HTML y CSV
                    if not os.path.exists(enlace_almacena_html):
                        boletin = soup.find("span", class_="nota")
                        boletin_fecha = boletin.text.strip() if boletin else ""
                        fecha_decreto = boletin_fecha.split("de")[-1].strip() if "de" in boletin_fecha else ""
                        titulo = soup.find("h2").get_text(strip=True) if soup.find("h2") else ""
                        subtitulo1 = soup.find("h3").get_text(strip=True) if soup.find("h3") else ""
                        contenido = " ".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="alerta")])
                        contenido_txt = "\n".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="alerta")])

                        df = crear_df_temporal(url, contenido_txt, identificador, fecha_decreto, titulo, subtitulo1, contenido, pdf_enlace, base_dir_txt, ruta_relativa_pdf, ruta_relativa_html, ruta_relativa_txt, pdf_file, html_file)
                        guardar_contenido_csv(df, base_dir_csv, anio)

                else:
                    print(f"No se pudo recuperar la URL: {url}")
            except Exception as e:
                print(f"Error reintentando URL {url}: {e}")
 
def extract_text_direct(pdf_path, min_chars=50):
    """Extrae la capa de texto puro directo de un archivo PDF vía PyMuPDF.

    Carga el PDF al vuelo llamando forzosamente la recolección de basura, intentando compilar 
    directamente el text-layer integrado.

    Args:
        pdf_path (str): Sendero base al documento en repositorio.
        min_chars (int, optional): Cuota condicional mínima alfanumérica de aceptación de validación. Default a 50.

    Returns:
        tuple[str, bool]: Texto puro si cumple y bandera true, `("", False)` caso de fallas nulas o no calificar limite.
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

def extract_text_ocr(pdf_path, language='spa'):
    """Recurre a procesador OCR Tesseract visualmente traduciendo fotogramas de `pdf2image`.

    Args:
        pdf_path (str): Componente de disco duro apuntando al file actual PDF.
        language (str, optional): Selector de gramática/diccionario OCR en Tesseract base. Defaults to 'spa'.

    Returns:
        str: Toda la compilación integral extraída OCR sin discriminar. Vacío si es dañado original.
    """
    try:
        pages = convert_from_path(pdf_path, 300)
        
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
    """Enrutador de procesamiento de texto en PDF dual; extracción directa y caída a OCR.

    Evalúa y prefiere el formato nativo interno Pymupdf al instante, evitando sobrecargas intensivas,
    y salta hacia pytesseract únicamente de comprobar que los niveles del primero retornaron una señal nula mínima 
    general, salvando cualquier crasheo final sin loguear a un tracker general del subarchivo de origen `error_log.txt`.

    Args:
        pdf_file (str): Elemento absoluto de localización de archivo final ya depositado o evaluado de la url extraída.

    Returns:
        str: Recuperación general condensada de extracción y limpia de lectura y fallos.
    """
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
    """Lanzador cronológico inifinito macro base por bloque de tiempo iterante de días sobre el BOJA.

    Comienza la compilación generalizando al extremo el rastro, evadiendo calendarios e itera a ciegas buscando estáticamente un índice index HTML `[anio]/[dia]/index.html`. 
    Captura de forma dual todos sus enlaces del index base o listado general del menú HTML. Adicionalmente integra bloques temporales dualizados inter-bucles para saltar boletines "regulares" (1 a 365 iterados) 
    hasta su versión especial de recolección de "suplementos directos" BOJA que abarcan en un extra numérico ciego (500 a 700).
    Asegura los PDFs, descargas textuales mixtas HTML/TXT con y sin OCR/PYMUPDF embebido todo ello al macro CSV transitorio con resguardos nominales directos en logs general tipo año a `[anio].txt`.
    
    Args:
        anio_scrappeo (int, kwarg): Marcador temporal inyectable de inicio que controla recorridos interanuales si fuera necesario y el nombramiento base de BD locales y fallas generales del portal oficial asimilado por fallos propios HTTP nativos.
    """

    for anio in range(anio_scrappeo,anio_scrappeo+1): #leemos cada dos años

        base_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdfs = os.path.join(base_anio, "PDF")
        base_dir_csv = base_anio
        base_dir_html = os.path.join(base_anio, "HTML")
        ruta_archivo_errores = os.path.join(base_anio, "url_errores")
        ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

        for carpeta in carpetas:    # Crear las carpetas si no existen
            os.makedirs(carpeta, exist_ok=True)

        numero_boletin = 1

        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{numero_boletin}")
                print("Escribimos el mes...")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                numero_boletin = int(f.read().strip())
                print("Leemos el mes...")

        print(f"EMPEZAMOS POR EL BOLETIN-> {numero_boletin}")
        print(f"Entramos al anio: {anio}")

        for dia in range(numero_boletin,366):

            try:
                base_enlace = f"https://www.juntadeandalucia.es/boja/{anio}/{dia}/index.html"
                respuesta, encontrada = intentar_peticion(base_enlace, ruta_archivo_errores)
                if encontrada == 1 and respuesta and respuesta.status_code == 200:
                    
                    #Estamos dentro de la página del dia 
                    soup_pagina_inicial = BeautifulSoup(respuesta.text, "html.parser")
                    enlaces = [a['href'] for a in soup_pagina_inicial.select('ul.listado_ordenado a')] + \
            [a['href'] for a in soup_pagina_inicial.select('ol.listado_ordenado a')] + \
            [a['href'] for a in soup_pagina_inicial.select('ol.listado_ordenado_boja a')]
                    
                    num_seccion = 1
                    for enlace in enlaces:    #Aqui accedemos a cada una de las secciones del 
                        respuesta_seccion, encontrada2 = intentar_peticion(enlace, ruta_archivo_errores)

                        if encontrada2 == 1 and respuesta_seccion and respuesta_seccion.status_code == 200:
                            soup_seccion = BeautifulSoup(respuesta_seccion.text, "html.parser")
                            try:
                                boletin = soup_seccion.find("span", class_="nota")
                            except AttributeError:
                                print("No se ha encontrado el atributo")

                            if anio <= 2011:
                                disposiciones_enlaces = [a['href'] for a in soup_seccion.select('div.item a[href]:not(.item_pdf)')]
                            elif anio == 2012:
                                if dia < 91:
                                    disposiciones_enlaces = [a['href'] for a in soup_seccion.select('div.item a[href]:not(.item_pdf)')]
                                else:
                                    disposiciones_enlaces = [a['href'] for a in soup_seccion.select('ul.sumario_pdf.grid_3.alpha a.item_html')]
                            else:
                                disposiciones_enlaces = [a['href'] for a in soup_seccion.select('ul.sumario_pdf.grid_3.alpha a.item_html')]

                            num_decreto = 1
                            for disposciones in disposiciones_enlaces:
                                time.sleep(1)
                                print(f"Estamos en la disposicion: {disposciones}")
                                respuesta_decreto, encontrada3 = intentar_peticion(disposciones, ruta_archivo_errores)

                                if encontrada3 == 1 and respuesta_decreto and respuesta_decreto.status_code == 200:
                                    soup = BeautifulSoup(respuesta_decreto.text, "html.parser")
                                    identificador = f"BOJA-{anio}-Boletin-{dia}-Seccion-{num_seccion}-Decreto-{num_decreto}"

                                    #Extraer todos los datos
                                    pdf_file = f"{identificador}.pdf"
                                    pdf_path = os.path.join(base_dir_pdfs, pdf_file)

                                    try:
                                        pdf_enlace = soup.find('a', class_='item_pdf_disposicion')['href']
                                        if pdf_enlace:             
                                            if os.path.exists(pdf_path):   #Comprobamos que no este el fichero ya descargado
                                                print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
                                            else:
                                                #PDF
                                                respuesta_decreto_pdf, encontrada4 = intentar_peticion(pdf_enlace, ruta_archivo_errores)
                                                if encontrada4 == 1 and respuesta_decreto_pdf and respuesta_decreto_pdf.status_code == 200:
                                                    descargar_pdf(respuesta_decreto_pdf, pdf_path)
                                        else:
                                            pdf_file = None
                                            pdf_enlace = None
                                            pdf_path = None

                                    except Exception as e:
                                        print("El pdf no existe")
                                        pdf_file = None
                                        pdf_enlace = None
                                        pdf_path = None
                                        pass

                                    #HTML
                                    html_file = f"{identificador}.html"
                                    enlace_almacena_html = os.path.join(base_dir_html, html_file)

                                    if os.path.exists(enlace_almacena_html):   #Comprobamos que no este el fichero ya descargado
                                        print(f"El archivo {html_file} ya existe. Se omite CSV, HTML y TXT")
                                    else:    
                                        #descargar_html(respuesta_decreto, enlace_almacena_html)
                                        #CSV
                                        df = pd.DataFrame()
                                        try:
                                            clase_titulos = soup.find("div", class_="punteado_izquierda cabecera_detalle_disposicion")
                                            boletin_fecha = boletin.text.strip()
                                            fecha_decreto = boletin_fecha.split("de")[-1].strip()
                                            Seccion = clase_titulos.find("h2").get_text(strip=True) if clase_titulos.find("h2") else ""
                                            Subseccion = clase_titulos.find("h3").get_text(strip=True) if clase_titulos.find("h3") else ""
                                            Subsubseccion = clase_titulos.find("h5").get_text(strip=True) if clase_titulos.find("h5") else ""
                                            Contenido = " ".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="alerta")])
                                            resumen = " ".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="item")])

                                            texto_pdf_re = ""
                                            if pdf_file != None:
                                                texto_pdf_re = process_pdf(pdf_path)
                                            
                                                if texto_pdf_re != "":
                                                    os.remove(pdf_path)
                                                    print(f"PDF leido y eliminado")
                                                else:
                                                    escribir_url_errores(ruta_archivo_errores, pdf_enlace)
                                            else:
                                                print(f"No contiene pdf...")

                                            Contenido_pdf = texto_pdf_re
                                            contenido_completo = f"{Contenido}\n{Contenido_pdf}"
                                        
                                        except AttributeError:
                                            print("No se ha encontrado el atributo")
                                            
                                        df = crear_df_temporal(identificador, fecha_decreto, Seccion, Subseccion, Subsubseccion, Contenido, Contenido_pdf, pdf_enlace, disposciones, resumen, contenido_completo)
                                        guardar_contenido_csv(df, base_dir_csv, anio)
                                        time.sleep(1)
                                        
                                    num_decreto += 1
                        num_seccion += 1
                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                            print(f"Guardamos el fichero en el boletin: {dia}")
                            f.write(f"{dia}")

                elif encontrada == 1 and respuesta.status_code == 404:
                    print(f"No existe a partir del dia: {dia}")
                    break

            except Exception as e:
                print(f"Error inesperado en el día {dia}: {e}")
                continue

        for dia in range(500,700):
                try:
                    base_enlace = f"https://www.juntadeandalucia.es/boja/{anio}/{dia}/index.html"
                    respuesta, encontrada = intentar_peticion(base_enlace, ruta_archivo_errores)
                    if encontrada == 1 and respuesta and respuesta.status_code == 200:
                        
                        #Estamos dentro de la página del dia 
                        soup_pagina_inicial = BeautifulSoup(respuesta.text, "html.parser")
                        enlaces = [a['href'] for a in soup_pagina_inicial.select('ul.listado_ordenado a')] + \
                [a['href'] for a in soup_pagina_inicial.select('ol.listado_ordenado a')] + \
                [a['href'] for a in soup_pagina_inicial.select('ol.listado_ordenado_boja a')]
                        
                        num_seccion = 1
                        for enlace in enlaces:    #Aqui accedemos a cada una de las secciones del 
                            respuesta_seccion, encontrada2 = intentar_peticion(enlace, ruta_archivo_errores)

                            if encontrada2 == 1 and respuesta_seccion and respuesta_seccion.status_code == 200:
                                soup_seccion = BeautifulSoup(respuesta_seccion.text, "html.parser")
                                try:
                                    boletin = soup_seccion.find("span", class_="nota")
                                except AttributeError:
                                    print("No se ha encontrado el atributo")

                                if anio <= 2011:
                                    disposiciones_enlaces = [a['href'] for a in soup_seccion.select('div.item a[href]:not(.item_pdf)')]
                                elif anio == 2012:
                                    if dia < 91:
                                        disposiciones_enlaces = [a['href'] for a in soup_seccion.select('div.item a[href]:not(.item_pdf)')]
                                    else:
                                        disposiciones_enlaces = [a['href'] for a in soup_seccion.select('ul.sumario_pdf.grid_3.alpha a.item_html')]
                                else:
                                    disposiciones_enlaces = [a['href'] for a in soup_seccion.select('ul.sumario_pdf.grid_3.alpha a.item_html')]

                                num_decreto = 1
                                for disposciones in disposiciones_enlaces:
                                    time.sleep(1)
                                    print(f"Estamos en la disposicion: {disposciones}")
                                    respuesta_decreto, encontrada3 = intentar_peticion(disposciones, ruta_archivo_errores)

                                    if encontrada3 == 1 and respuesta_decreto and respuesta_decreto.status_code == 200:
                                        soup = BeautifulSoup(respuesta_decreto.text, "html.parser")
                                        identificador = f"BOJA-suplemento-{anio}-Boletin-{dia}-Seccion-{num_seccion}-Decreto-{num_decreto}"

                                        #Extraer todos los datos
                                        pdf_file = f"{identificador}.pdf"
                                        pdf_path = os.path.join(base_dir_pdfs, pdf_file)

                                        try:
                                            pdf_enlace = soup.find('a', class_='item_pdf_disposicion')['href']
                                            if pdf_enlace:             
                                                if os.path.exists(pdf_path):   #Comprobamos que no este el fichero ya descargado
                                                    print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
                                                else:
                                                    #PDF
                                                    respuesta_decreto_pdf, encontrada4 = intentar_peticion(pdf_enlace, ruta_archivo_errores)
                                                    if encontrada4 == 1 and respuesta_decreto_pdf and respuesta_decreto_pdf.status_code == 200:
                                                        descargar_pdf(respuesta_decreto_pdf, pdf_path)
                                            else:
                                                pdf_file = None
                                                pdf_enlace = None
                                                pdf_path = None

                                        except Exception as e:
                                            print("El pdf no existe")
                                            pdf_file = None
                                            pdf_enlace = None
                                            pdf_path = None
                                            pass

                                        #HTML
                                        html_file = f"{identificador}.html"
                                        enlace_almacena_html = os.path.join(base_dir_html, html_file)

                                        if os.path.exists(enlace_almacena_html):   #Comprobamos que no este el fichero ya descargado
                                            print(f"El archivo {html_file} ya existe. Se omite CSV, HTML y TXT")
                                        else:    
                                            #descargar_html(respuesta_decreto, enlace_almacena_html)
                                            #CSV
                                            df = pd.DataFrame()
                                            try:
                                                clase_titulos = soup.find("div", class_="punteado_izquierda cabecera_detalle_disposicion")
                                                boletin_fecha = boletin.text.strip()
                                                fecha_decreto = boletin_fecha.split("de")[-1].strip()
                                                Seccion = clase_titulos.find("h2").get_text(strip=True) if clase_titulos.find("h2") else ""
                                                Subseccion = clase_titulos.find("h3").get_text(strip=True) if clase_titulos.find("h3") else ""
                                                Subsubseccion = clase_titulos.find("h5").get_text(strip=True) if clase_titulos.find("h5") else ""
                                                Contenido = " ".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="alerta")])
                                                resumen = " ".join([p.get_text(strip=True) for p in soup.find_all("p") if not p.find_parent("div", class_="item")])

                                                texto_pdf_re = ""
                                                if pdf_file != None:
                                                    texto_pdf_re = process_pdf(pdf_path)
                                                
                                                    if texto_pdf_re != "":
                                                        os.remove(pdf_path)
                                                        print(f"PDF leido y eliminado")
                                                    else:
                                                        escribir_url_errores(ruta_archivo_errores, pdf_enlace)
                                                else:
                                                    print(f"No contiene pdf...")

                                                Contenido_pdf = texto_pdf_re
                                            
                                            except AttributeError:
                                                print("No se ha encontrado el atributo")

                                            df = crear_df_temporal(identificador, fecha_decreto, Seccion, Subseccion, Subsubseccion, Contenido, Contenido_pdf, pdf_enlace, disposciones, resumen)
                                            guardar_contenido_csv(df, base_dir_csv, anio)
                                            time.sleep(1)
                                            
                                        num_decreto += 1
                            num_seccion += 1
                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                print(f"Guardamos el fichero en el boletin: {dia}")
                                f.write(f"{dia}")

                    elif encontrada == 1 and respuesta.status_code == 404:
                        print(f"No existe a partir del dia: {dia}")
                        break

                except Exception as e:
                    print(f"Error inesperado en el día {dia}: {e}")
                    continue

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)

