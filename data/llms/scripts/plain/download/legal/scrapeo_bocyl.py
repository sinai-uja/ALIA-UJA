"""Recolector del Boletín Oficial de Castilla y León (BOCYL).

Este script automatiza la extracción de datos y descarga de documentos
del BOCYL. Navega por el boletín a través de su calendario web, extrae
secciones y subsecciones, y descarga la información en formato PDF y HTML.
Estructura los metadatos relevantes en archivos CSV para su posterior análisis.

Attributes:
    anio_scrappeo (int): Año de inicio para el proceso de recolección (por defecto 1979).
    calendario (dict): Diccionario que define la estructura de días por meses.
    todas_columnas (set): Conjunto para registrar temporalmente las columnas encontradas.
    script_dir (str): Directorio raíz donde reside el script y se crearán carpetas temporales.
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
import pytesseract
from pdf2image import convert_from_path
import xml.etree.ElementTree as ET
import time
import clize
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
import pandas as pd

anio_scrappeo = 1979

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

todas_columnas = set()

script_dir = os.path.dirname(os.path.abspath(__file__))

def limpiar_texto(texto):
    """Elimina espacios múltiples y saltos de línea de una cadena de texto.

    Args:
        texto (str): El texto original a limpiar.

    Returns:
        str: El texto limpio con un solo espacio entre palabras.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Escribe una URL fallida en un archivo de texto de registro de errores.

    Args:
        archivo_errores (str): Ruta precalculada del archivo de errores (sin la extensión '.txt').
        url_dia (str): La URL que ha causado un error durante la petición.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Realiza una petición HTTP GET con manejo de excepciones y reintentos automáticos.

    Procesa respuestas exitosas y errores 404 de inmediato. Para otros errores de red, realiza
    múltiples intentos con pausas incrementales. Si todos los intentos fallan, la URL se anota.

    Args:
        url_buscar (str): La URL del recurso al que se intenta acceder.
        ruta_errores (str): Ruta base del archivo donde apuntar las URLs que fallaron permanentemente.

    Returns:
        tuple: Un par que contiene el objeto Response de `requests` (o None si hubo un error absoluto),
               y un indicador de estado donde 1 significa que se procesó una respuesta válida, o 0 si hubo fallo de conexión.
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

def Guardar_Contenido(df, base_dir_csv, anio_scrappeo):
    """Guarda (anexando) los metadatos de un decreto en un archivo CSV anual.

    Si el archivo no existe, lo crea e inserta la cabecera correspondiente.

    Args:
        df (pd.DataFrame): DataFrame de pandas que contiene los metadatos de un decreto individual.
        base_dir_csv (str): Directorio raíz donde se almacenan los CSV.
        anio_scrappeo (int|str): El año procesado, empleado como nombre del archivo final.
    """
    if not df.empty:
        archivo_csv = f"{base_dir_csv}/{anio_scrappeo}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Guardamos en el csv...")

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga de forma segura el contenido binario de un documento PDF.

    Descarga por volúmenes (chunks de 8KB) para mitigar el excesivo uso de memoria con archivos grandes.

    Args:
        response_pdf (requests.models.Response): Objeto de respuesta HTTP original del documento objetivo.
        enlacePDF (str): Ruta completa del sistema de archivos donde alojar el PDF definitivo.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def descargar_xml(response, path):
    """Descarga el contenido binario de un documento XML a nivel local.

    Args:
        response (requests.models.Response): Objeto de respuesta HTTP originaria del XML.
        path (str): Ruta completa del sistema de archivos donde asentar el fichero XML.
    """
    try:
        with open(path, 'wb') as f:
            f.write(response.content)
        print(f"Archivo XML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo XML en {path}: {e}")

def descargar_docx(response_docx, enlacedocx):
    """Descarga el contenido de un documento de Word en disco.

    Args:
        response_docx (requests.models.Response): Objeto de respuesta HTTP correspondiente al DOCX.
        enlacedocx (str): Localización de sistema de archivos final para el fichero.
    """
    try:
        with open(enlacedocx, "wb") as pdf_file:
                pdf_file.write(response_docx.content)
        print(f"POcx descargado decreto: {enlacedocx}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def descargar_html(response, path):
    """Vuelca el fichero de un documento HTML a disco de manera estructurada en texto.

    Args:
        response (requests.models.Response): Objeto de respuesta de web cruda.
        path (str): Ubicación completa sobre la que construir el archivo web local.
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Archivo HTML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo HTML en {path}: {e}")

def crear_df_temporal(enlace_decreto, decreto, dia, mes, ruta_pdf, anio, respuesta_decreto, enlace_pdf, numero_boletin, num_decreto, num_seccion):
    """Forma y moldea un dataframe base de metadatos del BOCYL.

    Este artefacto centraliza los elementos recolectados de distintas partes e inyecta un rastreador de metadatos,
    limpiando espacios excedentes y devolviendo el contenedor para exportación a la base en crudo.

    Args:
        enlace_decreto (str): Ubicación hipertextual en BOCYL del resumen de resolución.
        decreto (dict): Estructura en crudo recuperada con título, subtipo y resumen del documento.
        dia (int|str): El día referente a la publicación.
        mes (int|str): El mes referente a la publicación.
        ruta_pdf (str): Enrutado interno hasta la descarga consolidada en el disco magnético.
        anio (int|str): El año de indexación de la norma.
        respuesta_decreto (requests.models.Response): La lectura en bruto (HTTP) del contenido web para el raspado interno profundo.
        enlace_pdf (str): Localizador web primitivo del PDF, extraído del árbol.
        numero_boletin (int): El conteo serial global de los boletines anuales.
        num_decreto (int): Subetiqueta posicional del aviso actual dentro de su respectiva subsección.
        num_seccion (int): Valor incrementante que mapea el orden superior de catalogación del boletín.

    Returns:
        pd.DataFrame: DataFrame de renglón único normalizado dispuesto para escritura persistente en formato apilado (append).
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    identificador = None
    df = pd.DataFrame()
    soup = BeautifulSoup(respuesta_decreto.text, "html.parser")

    try:
        fecha_decreto = f"{dia}-{mes}-{anio}"
        identificador = f"BOCYL-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
        titulo = decreto['seccion']
        resumen = decreto['decreto']
        subtitulo = decreto['subseccion']
        contenido = " ".join([p.get_text(strip=True) for p in soup.find_all("p") 
                      if not p.find_parent("div", class_="justificado anexo")])
        contenido_txt = "\n".join([p.get_text(strip=True) for p in soup.find_all("p") 
                           if not p.find_parent("div", class_="justificado anexo")])

                       
    except AttributeError:
        print("No se ha encontrado el atributo")

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Título": titulo,
        "Subtitulo_seccion": subtitulo,
        "Resumen": resumen,
        "Contenido": contenido,
        "Url_pdf": enlace_pdf,
        "Url_decreto": enlace_decreto,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x)) 

    return nuevo_df


def comprobar_decreto(enlace_decreto, url_pdf, respuesta_decreto, numero_boletin, num_seccion, num_decreto, soup, base_dir_csv, dia, mes, anio, base_dir_pdf, ruta_archivo_errores, decreto):
    """Comprueba, descarga subarchivos asociados y envía un registro único al bloque de escritura CSV.

    Determina que la norma sea inédita detectando localmente, previendo la redescarga,
    fuerza la descarga física usando requests y empalma su metadato de sistema nativo y de escrapeo 
    a través del conector `crear_df_temporal` remitiendo al log maestro `Guardar_Contenido`.

    Args:
        enlace_decreto (str): Referencia a la notificación general.
        url_pdf (str): Referencia hacia el activo puramente en PDF extraído del nodo padre.
        respuesta_decreto (requests.models.Response): Estado HTML de conexión HTTP, de la nota extendida.
        numero_boletin (int): Rastreador diario para componer UID semántico local.
        num_seccion (int): Índice de tipo legislatura para componer UID semántico local.
        num_decreto (int): Índice numeral sucesivo de un registro al día, para el UID.
        soup (BeautifulSoup): Parseo estructural del `respuesta_decreto`. Obsoleto: reutilizado desde `crear_df`.
        base_dir_csv (str): Path de directorio raíz año.
        dia (int) : Identificador ordinal del calendario.
        mes (int) : Índice ordinal del índice calendárico.
        anio (int) : Indice anual de año base.
        base_dir_pdf (str): Path subyacente para depósito puramente binario (PDFs).
        ruta_archivo_errores (str): Path de errores de peticiones encadenadas.
        decreto (dict): Empaquetado contextual extraído desde la macro tabla principal.
    """

    ruta_relativa_pdf = f"/{anio}/PDF"

    pdf_file = f"BOCYL-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}.pdf"

    enlace_almacena_pdf = os.path.join(base_dir_pdf, pdf_file)

    df = pd.DataFrame()

    if url_pdf:
        if os.path.exists(enlace_almacena_pdf):   
            print(f"El archivo pdf ya existe. Se omite la descarga.")
        else:
            pdf_response, encontrado_pdf = intentar_peticion(url_pdf, ruta_archivo_errores)
            if encontrado_pdf == 1 and pdf_response and pdf_response.status_code == 200:
                descargar_pdf(pdf_response, enlace_almacena_pdf)
                if url_pdf:
                    ruta_pdf = f"{ruta_relativa_pdf}/{pdf_file}"
                else:
                    ruta_pdf = None
                df = crear_df_temporal(enlace_decreto, decreto, dia, mes, ruta_pdf, anio, respuesta_decreto, url_pdf, numero_boletin, num_decreto, num_seccion)
                Guardar_Contenido(df, base_dir_csv, anio)
    

def extraer_seccion_subseccion_con_enlace(soup, anio):
    """Función de mapeo DOM exhaustivo que captura elementos jerárquicos (sección, subsección y leyes).

    Utilizando los identificadores temporales dependientes del diseño que cambiaron drásticamente con los años
    (pre/post 2010), el algoritmo de iteración en secuencia desciende tomando padres y descendientes lógicos
    y un arreglo paralelo con extensiones de archivos PDF y .do (metamodelo web originario en Javascript).

    Args:
        soup (BeautifulSoup): Instancia de lectura HTML total de la vista del día.
        anio (int): Indicativo que determina el nivel de anidado histórico del motor de búsqueda (h3-h4 vs h4-h5).

    Returns:
        list[dict]: Array estático conteniendo diccionarios repletos por cada aviso publicado (claves `seccion`, `subseccion`, `decreto`, `pdf`, `html`).
    """
    decretos = []
    h_titulo = None
    h_subtitulo = None

    if anio < 2010:
        h_titulo = 'h3'
        h_subtitulo = 'h4'
    else:
        h_titulo = 'h4'
        h_subtitulo = 'h5'


    for seccion in soup.find_all(h_titulo):
        nombre_seccion = seccion.get_text(strip=True)

        for subseccion in seccion.find_all_next(h_subtitulo):
            if subseccion.find_previous(h_titulo) != seccion:
                break  

            nombre_subseccion = subseccion.get_text(strip=True)

            for decreto in subseccion.find_all_next('p'):
                if decreto.find_previous(h_subtitulo) != subseccion:
                    break
                
                texto_decreto = decreto.get_text(strip=True)
                
                pdf_link = None
                html_link = None

                siguiente_ul = decreto.find_next_sibling('ul', class_='descargaBoletin')

                if siguiente_ul:
                    for a in siguiente_ul.find_all('a', href=True):
                        enlace = a['href']
                        if enlace.endswith('.pdf'):
                            pdf_link = enlace
                        elif enlace.endswith('.do'):
                            html_link = enlace

                # Guardamos los datos
                decretos.append({
                    "seccion": nombre_seccion,
                    "subseccion": nombre_subseccion,
                    "decreto": texto_decreto,
                    "pdf": pdf_link,
                    "html": html_link
                })
    return decretos

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Función maestra de ejecución y recorrido interanual continuo sobre BOCYL.

    Asigna un bucle principal según el inicio declarado, crea directorios sistemáticos locales 
    e inicia un subsistema de persistencia de rastreo día/mes/boletín con recuperaciones transparentes frente a desconexiones. 
    Se alinea y itera estrictamente sobre el diccionario de `calendario`. Acumula, parsea los submenús y finaliza la carga recursiva.
    
    Args:
        anio_scrappeo (int, kwarg): Identificador temporal base, dictaminado habitualmente como el punto de inicio para la carga masiva.
    """
    global calendario
    for anio in range(anio_scrappeo,anio_scrappeo+1): #leemos cada dos años

        #Creación carpetas por anio
        carpeta_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdf = os.path.join(script_dir, f"{anio}", "PDF")
        base_dir_csv = os.path.join(script_dir,f"{anio}", "CSV")
        ruta_archivo_errores = os.path.join(script_dir, f"{anio}", "Errores")
        ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [carpeta_anio, base_dir_pdf, base_dir_csv, ruta_archivo_errores]

        # Crear las carpetas si no existen
        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        print(f"Entramos al anio: {anio}")
        mes_leido = 1
        dia_leido = 1
        numero_boletin = 1
        base_boletin = f"https://bocyl.jcyl.es/boletin.do?fechaBoletin="

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
                    url_buscar = f"{base_boletin}{dia:02}/{mes:02}/{anio}"
                    print(f"Entramos a: {url_buscar}")
                    respuesta_pagina, encontrada_pag = intentar_peticion(url_buscar, ruta_archivo_errores)

                    if encontrada_pag == 1 and respuesta_pagina and respuesta_pagina.status_code == 200:
                        print(f"Entramos a la pagina del dia: {dia} mes: {mes} anio: {anio}")
                        soup = BeautifulSoup(respuesta_pagina.text, "html.parser") 

                        decretos = extraer_seccion_subseccion_con_enlace(soup, anio)
                        num_seccion = 0
                        num_decreto = 0
                        seccion_anterior = None

                        for decreto in decretos:
                            num_decreto += 1

                            if decreto['seccion'] != seccion_anterior:
                                num_seccion += 1
                                num_decreto = 1
                                seccion_anterior = decreto['seccion']

                            try: 
                                seccion_anterior = decreto['seccion']
                                enlace_decreto = f"https://bocyl.jcyl.es/{decreto['html']}"

                                respuesta_decreto, encontrado_decreto = intentar_peticion(enlace_decreto, ruta_archivo_errores)
                                if encontrado_decreto == 1 and respuesta_decreto and respuesta_decreto.status_code == 200:
                                    soup_decreto = BeautifulSoup(respuesta_decreto.text, "html.parser")
                                    comprobar_decreto(enlace_decreto, decreto['pdf'], respuesta_decreto, numero_boletin, num_seccion, num_decreto, soup_decreto, base_dir_csv, dia, mes, anio, base_dir_pdf, ruta_archivo_errores, decreto)
                                    time.sleep(0.3)
                            except FileNotFoundError as e:
                                print(f"Error al encontrar el archivo: {e}")
                                continue
                            except Exception as e:
                                print(f"Error inesperado: {e}")
                                continue
                    else:
                        print(f"La página del dia {dia}-{mes}-{anio} -> No existe")
                        numero_boletin -= 1

                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                        print(f"Guardamos el fichero en el dia: {dia}-{mes}")
                        f.write(f"{mes},{dia},{numero_boletin}")
                
                except Exception as e:
                    print(f"Error inesperado: {e}")
                    continue

                numero_boletin += 1
            dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)

