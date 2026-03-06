"""Recolector del Butlletí Oficial de les Illes Balears (BOIB).

Este script automatiza la extracción sistemática de datos y descarga de documentos
del BOIB. Recorre anualmente el histórico de boletines a nivel local usando un sistema
de peticiones HTTP secuenciales orientadas por número de boletín e intentando decodificar
el árbol DOM de la respuesta para extraer la fecha base, el identificativo único local y
el enlace absoluto definitivo hacia el documento digital primario (PDF). Almacena estos
datos relacionales crudos en CSV, con posterior serialización y compresión a `.parquet` / `.zip`.

Attributes:
    anio_scrappeo (int): El año temporal empleado actualmente como test de ejecución, estático en código.
    script_dir (str): Directorio del cual se ejecuta el script. Actúa como base inmutable en rutas de exportación.
    calendario (dict): Formato referencial de días sobre los meses (sin uso intensivo principal en este script específico).
    meses (dict): Mapeo base de lectura de cadenas a números en strings formateados ('Enero' a '01').
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

meses = {
    'Enero': '01', 'Febrero': '02', 'Marzo': '03', 'Abril': '04',
    'Mayo': '05', 'Junio': '06', 'Julio': '07', 'Agosto': '08',
    'Septiembre': '09', 'Octubre': '10', 'Noviembre': '11', 'Diciembre': '12'
}

def limpiar_texto(texto):
    """Elimina tabulaciones colapsables, espacios múltiples consecutivos y saltos de línea de una cadena.

    Args:
        texto (str): La subcadena o línea extraída en bruto con ruido espaciado.

    Returns:
        str: Cadena de texto comprimida con separación unitaria de espacios.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto eficientemente desde el fichero físico cargado de un formato PDF empleando PyMuPDF.

    Abre un entorno de punteros in-memory con un recolector de basura (GC) explícitamente forzado
    para gestionar memoria frente a iteraciones masivas. Extrae hasta el final validando
    un mínimo ponderable de caracteres esperados.

    Args:
        pdf_path (str): Ruta precalculada validada hacia el volumen binario del PDF.
        min_chars (int, optional): Filtro condicional que considera inútil a una respuesta vacía o defectuosa, por omisión 50 caracteres.

    Returns:
        tuple[str, bool]: Texto en texto crudo directo concatenado junto a un resultado tipo bandera de boolean de si alcanzó el mínimo para ser útil.
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
    """Redacta dentro de un archivo base local el nombre o enlace originario de un intento frustrado o conexión colgada permanentemente.

    Args:
        archivo_errores (str): Directorio enrutado (no incluir '.txt') que hospeda el registro de rastreo fallos.
        url_dia (str): La URL a perpetrar en el registro permanente de control.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Enlaza mediante peticiones GET (en modalidad strem) a los portales públicos.

    Frente a la debilidad propia e innata en redes con solicitudes programadas constantes y continuas
    reintenta la latencia de forma repetida (hasta un limite de 5 recargas tolerables por nodo con 
    intervalos crecientes fijos). Emite los sucesos nulos explícitamente y anómalos o codificaciones rotas a la función dependiente de logueo.

    Args:
        url_buscar (str): Enlace explícito y resolutorio requerido en el iterador central.
        ruta_errores (str): Prefijo inmutable dependiente a un archivo para apunte manual post-mortem.

    Returns:
        tuple: (Objeto estandar `requests.models.Response` de retorno o primitivo nulo (`None`),
            Indicativo condicional de logro en forma de entero escalar (0-Falla, 1-Éxito).
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
    """Transcribe bajo apendización persistente un bloque extraído en forma de DF en un fichero de registro anual de metadatos.

    Args:
        df (pd.DataFrame): Molde matricial de texto y enlaces con metadatos recolectados limpios de un boletín.
        ruta (str): Espacio absoluto de directorios sin finalizar la designación nominal.
        anio (int|str): El identificativo general numeral de año aplicable al CSV de escritura local en la raíz.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Acumula secuencialmente en el ordenador una transferencia directa PDF sin comprometer la ráfaga completa vía buffers.

    Mantiene controladamente a salvo los descriptores temporales iterando en franjas mínimas constantes (8 KB/1024 chunks). 

    Args:
        response_pdf (requests.models.Response): Bloque o archivo latente en el entorno Requests.
        enlacePDF (str): Nombre final del archivo.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha_decreto, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Inyecta un modelo tabular predefinido de campos para unificar extracciones de múltiples boletines en memoria unificada.

    Args:
        identificador (str): Acronimo prefijado BOIB adjunto al rastrego local de índices de sub-nodo generados manualmente (id general).
        fecha_decreto (str): Extraído mediante BS4 y casteado a formato 'dd-mm-AAAA' procedente del árbol oficial en servidor.
        contenido_text (str): Vacío o enmascarado si fue omitido o incapaz de escanear.
        enlace_pdf (str): Reconstrucción unida de URL absoluta y token recuperados vía parseo base para alojar las descargas futuras o presentes.
        ruta_guardar_pdf (str): Donde efectivamente aterrizará el binario de extensión .pdf en ambiente propio de directorios internos.

    Returns:
        pd.DataFrame: Molde con 1 rango estricto, totalmente preparado (`limpiar_texto`) para fundirse en la tabla agregada que conformará cada CSV general anual.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "fecha_decreto": fecha_decreto,
        "contenido": contenido_text,
        "url": enlace_pdf,
        "fecha_lectura": fecha_lectura,
        "ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def scrapear_dias_completos():
    """Arranque sistemático principal; centraliza y gestiona las rutinas de peticiones web hacia BOIB.

    El recolector opera anualmente intentando la búsqueda ciega (sobre URLs estancas a modo fuerza bruta).
    Avanza sobre `boletines` y rastrea mediante BeautifulSoup el documento principal por su fecha de boletín y link de PDF de fondo.
    Genera metadatos a cada `df_temporal`, se empalma al histórico local en fichero .csv sobre el mismo periodo `anio`. Con el recuento 
    general post-ejecutivo (por año finalizado) transforma el archivo matricial transitorio CSV local al eficiente formato `.parquet`
    apretándolo más en archivo persistido final base con zipeo (`.zip`).
    Implementa resguardo tolerante a fallos local con escritura y re-lectura del año, día, mes y boletines con `continua_por` o `[anio].txt`. 
    """

    anio_leido = 1979
    ruta_continuar =  os.path.join(script_dir, f"{anio_leido}.txt")
    mes_leido = 1
    dia_leido = 1
    numero_boletin = 8357  #hasta 10139

    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{mes_leido},{dia_leido},{numero_boletin},{anio_leido}")  #leemos el dia y el mes
            print("Escribimos el mes...")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            mes_leido, dia_leido, numero_boletin, anio_leido = map(int, f.read().strip().split(','))
            print("Leemos el mes...")

    archivo_csv_actual = ""
    for anio in range(anio_leido, 1997):

        ruta_archivo_errores = os.path.join(script_dir, "url_errores")

        for boletin in range(numero_boletin, 10139):
            base_enlace = f"https://www.caib.es/eboibfront/es/{anio}/{boletin}/"
            print(f"Dentro de: {base_enlace}")
            respuesta_enlace, encontrado_enlace = intentar_peticion(base_enlace, ruta_archivo_errores)

            if encontrado_enlace == 1 and respuesta_enlace and respuesta_enlace.status_code == 200:
                soup = ""
                try: 
                    soup = BeautifulSoup(respuesta_enlace.text, 'html.parser')
                    print(f"Entramos al Boletin -> {boletin}")

                    buscando_f = soup.find("a", class_="fijo")
                    numero = buscando_f.find('strong').get_text(strip=True)
                    texto_fecha = buscando_f.find_all('p')[1].get_text()
                    fecha_str = texto_fecha.split('-')[-1].strip()

                    dia, mes_nombre, anio = [parte.strip() for parte in fecha_str.split('/')]
                    mes_num = meses.get(mes_nombre, '00')  
                    fecha_formateada = f"{dia.zfill(2)}-{mes_num}-{anio}"

                    base_anio = os.path.join(script_dir, f"{anio}")
                    base_dir_pdfs = os.path.join(base_anio, "PDF")
                    base_dir_csv = base_anio
                    ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

                    carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                    for carpeta in carpetas:    # Crear las carpetas si no existen
                        os.makedirs(carpeta, exist_ok=True)


                    pdf_descargar = soup.find("a", class_="pdf")
                    enlace_pdf_ = pdf_descargar['href']
                    enlace = f"https://www.caib.es{enlace_pdf_}"
                    print(f"Enlace del pdf: {enlace}")
                    identificador = f"BOIB-{anio}-Boletin-{boletin}-Seccion-{1}-Decreto-{1}"
                    ruta_guardar_pdf = f"{base_dir_pdfs}/{identificador}.pdf"

                    if not os.path.exists(ruta_guardar_pdf):
                        time.sleep(2)
                        respuesta_pdf, encontrado_pdf = intentar_peticion(enlace, ruta_archivo_errores)
                        try:
                            if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                #texto_pdf_re, exito_re = extract_text_direct(ruta_guardar_pdf)
                                            
                                df_re = crear_df_temporal(identificador, fecha_formateada, None, enlace, ruta_guardar_pdf)
                                guardar_contenido_csv(df_re, base_dir_csv, anio)
                                archivo_csv_actual = f"{base_dir_csv}/{anio}.csv"
                                print(f"Guardamos contenido del decreto -> {identificador}")
                                time.sleep(3)
                        except:
                            print(f"Error al descargar el pdf: {identificador}")

                except:
                    print("Error en el boletin")

        # Convertir CSV a Parquet
        parquet_path = f"{base_dir_csv}/{anio}.parquet"
        try:
            if os.path.exists(archivo_csv_actual):
                df = pd.read_csv(archivo_csv_actual, encoding='utf-8')
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
                    zipf.write(archivo_csv_actual, os.path.basename(archivo_csv_actual))
                print(f"✅ Archivo ZIP creado: {zip_path}")
        except Exception as e:
            print(f"❌ Error al crear el archivo ZIP para el año {anio}: {e}")



if __name__ == "__main__":
    scrapear_dias_completos()


