"""Recolector del Boletín Oficial de Cantabria (BOC).

Este script automatiza la extracción de datos y descarga de documentos
del BOC. Navega por el histórico de boletines usando identificadores secuenciales,
identifica secciones y descarga los archivos PDF correspondientes. Además,
se prepara para estructurar los metadatos de los decretos en archivos CSV.

Attributes:
    anio_scrappeo (int): El año o parámetro base (aunque el script usa secuencia de boletín).
    script_dir (str): Directorio raíz donde reside el script y se crearán carpetas temporales.
    calendario (dict): Formato referencial de días sobre los meses (no activamente usado aquí).
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
    12: list(range(1, 32))  
}

def limpiar_texto(texto):
    """Elimina espacios múltiples y saltos de línea de una cadena de texto.

    Args:
        texto (str): El texto original a limpiar.

    Returns:
        str: El texto limpio con espacios simples.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Añade una URL que ha fallado al archivo de registro de errores.

    Args:
        archivo_errores (str): Ruta precalculada del archivo de errores (sin '.txt').
        url_dia (str): La URL conflictiva.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Realiza una petición HTTP GET con manejo robusto de errores y reintentos.

    Procesa respuestas exitosas (200), advertencias (404) y aplica hasta 5 reintentos
    para otro tipo de fallos de conexión, registrando el error si persiste.

    Args:
        url_buscar (str): La URL a consultar.
        ruta_errores (str): Ruta base del archivo donde apuntar URLs fallidas.

    Returns:
        tuple[requests.models.Response|None, int]: Objeto Response (o None) y
            un indicador de éxito (1) o fracaso absoluto (0).
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
            for i in range(5):
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

def guardar_contenido_csv(df, ruta, anio,  boletin, seccion, decreto):
    """Guarda o anexa el contenido del DataFrame de un decreto a un CSV por año.

    Args:
        df (pd.DataFrame): DataFrame con la información procesada del decreto.
        ruta (str): Directorio destino para el CSV.
        anio (int|str): Año correspondiente que da nombre al CSV.
        boletin (int|str): Número del boletín (para logs).
        seccion (int|str): Número de la sección (para logs).
        decreto (int|str): Número del decreto (para logs).
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print(f"Guardamos contenido del decreto -> Boletin-{boletin}-Secc-{seccion}-Dec-{decreto}")

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga de forma segura el contenido binario de un documento PDF.

    Extrae la información por chunks (8KB) para evitar sobrecargas de memoria.

    Args:
        response_pdf (requests.models.Response): Objeto Response con el dataset directo del PDF.
        enlacePDF (str): Ruta completa donde guardar el PDF final.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_detalle, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Genera un DataFrame temporal estandarizado con los metadatos de un decreto.

    Añade un sello con la fecha de recolección y limpia el texto de todos los campos.
    
    Args:
        enlace_detalle (str): URL de la página de detalle en HTML.
        identificador (str): ID único sintético creado para el decreto.
        fecha_decreto (str): Fecha oficial de publicación.
        nombre_seccion (str): Título oficial de la sección padre.
        nombre_subseccion (str): Subtítulo si existiese.
        contenido_text (str): El texto en crudo si proviene del HTML.
        enlace_pdf (str): URL de donde se descargó el decreto PDF.
        ruta_guardar_pdf (str): Ruta local final del documento.

    Returns:
        pd.DataFrame: Un dataframe limpio listo para guardar. 
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Título": nombre_seccion,
        "Subtítulo": nombre_subseccion,
        "Contenido": contenido_text,
        "Url_pdf": enlace_pdf,
        "Url_html": enlace_detalle,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def crear_carpetas_nuevas(anio):
    """Establece la jerarquía de directorios necesaria para un nuevo año de scrap.

    Crea el root de año y las subcarpetas específicas (PDF) de forma segura.

    Args:
        anio (int|str): El año que se va a comenzar a procesar.

    Returns:
        tuple[str, str, str, str]: Rutas de (base_anio, base_dir_pdfs, archivo_errores, archivo continuacion_tracking).
    """
    base_anio = os.path.join(script_dir, f"{anio}")
    base_dir_pdfs = os.path.join(base_anio, "PDF")
    ruta_archivo_errores = os.path.join(base_anio, "url_errores")
    ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

    carpetas = [base_anio, base_dir_pdfs]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    return base_anio, base_dir_pdfs, ruta_archivo_errores, ruta_continuar

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Función núcleo que orquesta el raspado completo del BOC de Cantabria.

    A través de peticiones HTTP, avanza secuencialmente usando el parámetro `idBolOrd`
    para recorrer cada edición del boletín independientemente de la fecha.
    Rastrea el año vigente mediante expresiones regulares en los títulos devueltos.
    Identifica decretos, organiza localmente las carpetas por año de manera dinámica
    y descarga todos y cada uno de los archivos PDF vinculados a las notificaciones.
    Conserva su posición en un simple `.txt` para tolerar interrupciones programadas.

    Args:
        anio_scrappeo (int, kwarg): Parámetro base inactivo por diseño,
            reemplazado internamente por tracking secuencial numeral del boletín.
    """
    anio_actual = anio_scrappeo
    base_anio = os.path.join(script_dir, f"{anio_actual}")
    base_dir_pdfs = os.path.join(base_anio, "PDF")
    base_dir_csv = base_anio
    ruta_archivo_errores = os.path.join(base_anio, "url_errores")
    ruta_continuar =  os.path.join(script_dir, f"{anio_actual}", f"{anio_actual}.txt")

    carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

    for carpeta in carpetas:    # Crear las carpetas si no existen
        os.makedirs(carpeta, exist_ok=True)

    numero_boletin = 1

    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{numero_boletin}")  #leemos el dia y el mes
            print("Escribimos el mes...")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            numero_boletin = int(f.read())
            print("Leemos el mes...")

    print(f"EMPEZAMOS POR EL boletin -> {numero_boletin}")

    for num_boletin in range(numero_boletin, 39500):   #leemos cada dia
            try: 
                base_enlaces = f"https://boc.cantabria.es/boces/verBoletin.do?idBolOrd={num_boletin}"
                
                respuesta, encontrado = intentar_peticion(base_enlaces, ruta_archivo_errores)
                if encontrado == 1 and respuesta and respuesta.status_code == 200:
                    print(f"Entramos al boletín: {num_boletin}")
                    
                    #Tomamos las seccions y subsecciones
                    soup = BeautifulSoup(respuesta.text, 'html.parser')

                    boletin = soup.find("div", class_= "contenTitulo")
                    span_titulo = boletin.find("span", class_="titulo2")

                    if span_titulo:
                        texto_boletin = span_titulo.get_text(strip=True)
                        match = re.search(r'Boletín Oficial de Cantabria:.*?(\d{4})[,\.]', texto_boletin)
                        if match:
                            anio = match.group(1)
                            print(f"Anio recogido: {anio}")
                            if anio != anio_actual:
                                anio_actual = anio
                                base_anio_, base_dir_pdfs_, ruta_archivo_errores_, ruta_continuar_ = crear_carpetas_nuevas(anio)

                                base_anio = base_anio_
                                base_dir_pdfs = base_dir_pdfs_
                                ruta_archivo_errores = ruta_archivo_errores_
                                ruta_continuar = ruta_continuar_

                    num_seccion = 0
                    num_decreto = 0
                    decretos = soup.find("div", class_="infor")
                    base_enlace = "https://boc.cantabria.es/boces/"

                    siguiente_etiqueta = decretos.find()

                    while siguiente_etiqueta:
                        if siguiente_etiqueta.name == "h4": 
                            num_seccion += 1
                            num_decreto = 0

                            siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()
                        elif 'enlacesDoc' in siguiente_etiqueta.get('class', []):
                            seccion_pdf = siguiente_etiqueta.find("div", class_="tipoPDFanuncio") 
                            num_decreto += 1
                            enlace_pdf = seccion_pdf.find("a")['href']
                            enlace_pdf = f"{base_enlace}{enlace_pdf}"

                            identificador = f"BOCANT-{anio}-Boletin-{num_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"

                            if enlace_pdf:
                                ruta_guardar_pdf = os.path.join(base_dir_pdfs,f"{identificador}")
                                ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"
                                response_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)

                                if encontrado_pdf == 1 and response_pdf and response_pdf.status_code == 200:
                                    if os.path.exists(ruta_guardar_pdf):
                                        print(f"El pdf {identificador} ya esta descargado.")
                                    else:
                                        descargar_pdf(response_pdf, ruta_guardar_pdf)
                            siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()
                            time.sleep(0.5)
                        else:
                            siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()

                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                        print(f"Guardamos el fichero en el boletin: {num_boletin}")
                        f.write(f"{num_boletin}")

                elif encontrado == 1 and respuesta.status_code == 404:
                    print(f"No existe a partir del dia: {num_boletin}")
                    break

            except Exception as e:
                print(f"Error inesperado en el día {num_boletin}: {e}")
                continue

            except ChunkedEncodingError as e:
                print(f"Error en la transferencia de datos: {e}")
                continue
        
            except requests.exceptions.RequestException as e:
                print(f"Intento rechazado")
                continue

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


