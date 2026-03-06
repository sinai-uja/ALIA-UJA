"""Recolector del Boletín Oficial del Principado de Asturias (BOPA).

Este script automatiza la extracción sistemática de datos y descarga masivos de documentos
del BOPA a lo largo de un bucle de iteradores paralelos de tiempo calendario y url por defecto.
Utiliza peticiones HTTP y BS4 para detectar index web iterándolo y analizando sus DL HTML y H5 para detectar seccionamientos directos.
Maneja transiciones estructurales desde subida puramente en PDF pre-2000 a subidas web puras post-2000 usando urls Liferay portlet (`p_p_id=pa_sede_bopa`).

Attributes:
    anio_scrappeo (int): El año temporal referencial (Ej. 2000).
    script_dir (str): Directorio del cual se ejecuta el script hacia el entorno de descargas de compilación CSV.
    calendario (dict): Formato referencial de días sobre los meses y listados iteradores.
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
    """Estiliza los campos base decodificados borrando espacios múltiples.

    Args:
        texto (str): Cadena en formato crudo obtenida.

    Returns:
        str: Segmento depurado y formateado lineal.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Crea una bitácora local plana acumulando errores inyectables nativos y de red puros HTTP limitados originados en Request.

    Args:
        archivo_errores (str): Path de archivo absoluto base resolutor (`Omitir '.txt'`).
        url_dia (str): Valor fallido inalcanzable de URL.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Garantiza la lectura por Streaming a host e incorpora protección cíclica de timeouts duros HTTP caídos.

    Args:
        url_buscar (str): Meta de localización HTTP(s).
        ruta_errores (str): Senda '.txt' paralela para reportes en fallo crudo terminal de los requests.

    Returns:
        tuple[requests.models.Response | None, int]: Dupla de la data obtenida con un status booleano nominal.
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

def guardar_contenido_csv(df, ruta, anio, boletin, seccion, decreto):
    """Añade los sets extraídos e incorporados aislados y los fusiona de inmediato con el acumulable analógico ".csv".

    Args:
        df (pd.DataFrame): Formato procesado tabulado en array de columnas unitarias.
        ruta (str): Path preformateado en origen transitorio de volcado.
        anio (int|str): Identificador nomenclativo puro.
        boletin (int|str): Identificador general diario natural para bitácora local prompt.
        seccion (int|str): Valor clasificador subdirector web superior.
        decreto (int|str): Escala nominal menor unitaria.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print(f"Guardamos contenido del decreto -> Boletin-{boletin}-Secc-{seccion}-Dec-{decreto}")

def descargar_pdf(response_pdf, enlacePDF):
    """Empaqueta iteradores estáticos `Chunked` limitados al alojamiento C originado en `Requests`.

    Args:
        response_pdf (requests.models.Response): Instancia devuelta binariamente decodificada validada proveniente HTTPS.
        enlacePDF (str): Nomenclatura del fichero físico en sistema interno con su terminación.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion, subsubseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Estructura estatuariamente los recolectores dispersos Web hacia la homogeneidad del DataFrame analizable final unifilar.

    Args:
        enlace_html (str): Reconstrucción absoluta local o link extraído del decreto individual (Directo de las anclas HTML o Liferay).
        identificador (str): Matrícula BOPA transitable.
        fecha_decreto (str): Impresión formal temporal originaria en portal.
        seccion (str): Rama clasificador general matriz jerarquía h4 superior (Padre Titular).
        subseccion (str): Rama orgánica inferior a secciones h5 (Sub-Órganos asturianos).
        subsubseccion (str): Ultima capa interna h6 para el marco individual.
        contenido_text (str): Lo empaquetado y resuelto nativo de web individual decantada `col-md-12 article-disposition`.
        enlace_pdf (str): El puente unívoco PDF al servidor.
        ruta_guardar_pdf (str): Equivalencia depositada en disco.

    Returns:
        pd.DataFrame: Tabulación lista normal en estructura y texto con filtrado previo unitario de arrays y carateres (`limpiar_texto`).
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
        "Subsubtitulo": subsubseccion,
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
    """Iniciador matriz macro general sobre subred y alojamiento mixto "BOPA".

    Recorre internamente calendarios dinámicamente y adapta la url al modelo del host temporalmente condicionado BOPA.
    Pre-2000 resuelve vía links planos puramente al PDF del volumen unificado diario depositado (`enlace_pag_base`).
    Post-actualidad resuelve navegando sumarios dinámicos parametrizados Liferay buscando agrupadores "dl" (h5 padre de ordenanzas) 
    y resoluciones anexadas con sus textos nativos individuales.

    Args:
        anio_scrappeo (int, kwarg): Marcador cronológico que actúa como base de arranque masivo en los bucles principales anidados for.
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
                    if anio > 1999:
                        base_enlaces = f"https://sede.asturias.es/bopa-sumario?p_p_id=pa_sede_bopa_web_portlet_SedeBopaSummaryWeb&p_p_lifecycle=0&p_r_p_summaryDate={dia:02}/{mes:02}/{anio}&p_r_p_summaryIsSearch=false"
                    
                        respuesta, encontrado = intentar_peticion(base_enlaces, ruta_archivo_errores)
                        if encontrado == 1 and respuesta and respuesta.status_code == 200:
                            tiene_decretos = False
                            print(f"Entramos a la página del día: {dia}-{mes}-{anio}")
                        
                            #Tomamos las seccions y subsecciones
                            soup = BeautifulSoup(respuesta.text, 'html.parser')

                            num_seccion = 0
                            num_decreto = 0
                            next_tag = soup.find(["h5"])
                            while next_tag:
                                if next_tag.name == "h5":  # Detecta una nueva SUBSECCIÓN
                                    num_seccion += 1
                                    num_decreto = 0
                                    next_tag = next_tag.find_next_sibling()

                                elif next_tag.name == "dl":     #Cogemos cada dl de decretos
                                    num_decreto += 1
                                    identificador = f"BOPA-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                                    enlace_html_tag = next_tag.find("a", title="Texto de la disposición")
                                    enlace_pdf_tag = next_tag.find("a", title="PDF de la disposición")

                                    enlace_html = enlace_html_tag["href"] if enlace_html_tag else None
                                    enlace_pdf = enlace_pdf_tag["href"] if enlace_pdf_tag else None

                                    ruta_guardar_pdf = None
                                    if enlace_pdf:
                                        ruta_guardar_pdf = os.path.join(base_dir_pdfs,f"{identificador}")
                                        ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"
                                        response_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)

                                        if encontrado_pdf == 1 and response_pdf and response_pdf.status_code == 200:
                                            if os.path.exists(ruta_guardar_pdf):
                                                print("El pdf ya esta descargado.")
                                            else:
                                                descargar_pdf(response_pdf, ruta_guardar_pdf)

                                    fecha_decreto = f"{dia}-{mes}-{anio}"
                                    response_texto, encontrado_texto = intentar_peticion(enlace_html, ruta_archivo_errores)
                                    contenido_text = ""

                                    if encontrado_texto == 1 and response_texto and response_texto.status_code == 200:
                                        soup_texto = BeautifulSoup(response_texto.text, 'html.parser')
                                        columna_texto = soup_texto.find("div", class_ = "row")
                                        seccion = columna_texto.find("h4")
                                        if seccion:
                                            seccion = seccion.get_text()
                                        subseccion = columna_texto.find("h5")
                                        if subseccion:
                                            subseccion = subseccion.get_text()
                                        subsubseccion = columna_texto.find("h6")
                                        if subsubseccion:
                                            subsubseccion = subsubseccion.get_text()
                                        contenido_text = " ".join([p.get_text(strip=True) for p in columna_texto.select("div.col-md-12.article-disposition p")])
                                        df = crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion,subsubseccion, contenido_text, enlace_pdf, ruta_guardar_pdf)
                                        tiene_decretos = True
                                        guardar_contenido_csv(df, base_dir_csv, anio, numero_boletin, num_seccion, num_decreto)
                                        time.sleep(0.5)
                                    next_tag = next_tag.find_next_sibling()
                                else:
                                    next_tag = next_tag.find_next_sibling()
                            
                            if tiene_decretos:
                                numero_boletin += 1

                        elif encontrado == 1 and respuesta.status_code == 404:
                            print(f"No existe a partir del dia: {dia}")
                            break


                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                print(f"Guardamos el fichero en el boletin: {mes}-{dia}-{numero_boletin - 1}")
                                f.write(f"{mes}, {dia}, {numero_boletin - 1}")

                    else:
                        enlace_pag_base = f"https://sede.asturias.es/bopa/{anio}/{mes:02}/{dia:02}/{anio}{mes:02}{dia:02}.pdf"
                        respuesta_base, encontrado_base = intentar_peticion(enlace_pag_base, ruta_archivo_errores)
                        
                        if encontrado_base == 1 and respuesta_base and respuesta_base.status_code == 200:
                            num_seccion = 1
                            num_decreto = 1
                            identificador = f"BOPA-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"

                            ruta_guardar_pdf = os.path.join(base_dir_pdfs,f"{identificador}")
                            ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"

                            if os.path.exists(ruta_guardar_pdf):
                                print("El pdf ya esta descargado.")
                            else:
                                descargar_pdf(respuesta_base, ruta_guardar_pdf)
                                time.sleep(0.5)
                            numero_boletin += 1

                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                print(f"Guardamos el fichero en el boletin: {mes}-{dia}-{numero_boletin}")
                                f.write(f"{mes}, {dia}, {numero_boletin}")

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


