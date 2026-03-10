"""Recolector del Boletín Oficial de Navarra (BON).

Este script automatiza la extracción sistemática de datos y descarga masivos de documentos
del BON. Iterando por meses y días sobre el entorno oficial.
Usa selectores y Beautifulsoup detectando páginas indexadoras `.table-data` -> tr diarios y enrruta dinámicamente
hacia PDF directos (dependiendo del año subyacente de entrada), resoluciones de Sumario, agrupaciones seccionales/subseccionales y extraccion manual
del DOM final. Incorpora soporte tolerante en la rutina maestro `scrapear_dias_completos`.

Attributes:
    anio_scrappeo (int): El año inicial temporal ancla (Ej: 2000).
    script_dir (str): Directorio del cual se ejecuta el script. Configurado para guardado y referencias locales permanentes.
    meses (dict): Mapeo literal español-numérico para formato de fechas en la decodificación interna del BOE.
    calendario (dict): Formato referencial de días sobre los meses y listados indexados de base predefinida en días.
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

meses = {
    'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
    'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
    'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
}

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
        texto (str): Segmento extraído crudo de una lectura en BeautifulSoup u otra instancia.

    Returns:
        str: Segmento depurado sin espacios en cadena múltiples.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Escribe temporal y persistente un enlace quebrado o caído dentro de un identificador general diario manual `.txt`.

    Args:
        archivo_errores (str): Path de archivo resolutor. Omitir extensión `.txt`.
        url_dia (str): Valor fallido estricto de red de la URL intentada mediante Requests.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Protege y elabora tolerante de latencias de streaming y rechazos de host institucionales una petición Request.

    Tolera `ChunkedEncodingError` por caídas SSL en descargas parciales y genera bucles for (5) reintentadores en cierres duros `404 502 HTTP`.

    Args:
        url_buscar (str): Endpoint a consultar.
        ruta_errores (str): Fichero rastreador por si se desborda y fracasan todos los intentos cíclicos.

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta estructurada Response o iterador anulado y Booleana representativa Int `1, 0`.
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
    """Une dataframe en formato tabular estructurado en archivo plano .csv anual histórico.

    Args:
        df (pd.DataFrame): Cuadro aislado formateado originado unitario en el parser principal.
        ruta (str): Directorio raíz del año donde reside o residirá por nueva iteración el local base CSV.
        anio (int|str): Correlativo numeral temporal del año.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Embudiza stream binario a trozos sobre el destino directo sin rebosar buffer host nativo.

    Args:
        response_pdf (requests.models.Response): Instancia base devuelta validada previamente HTTP de Requests.
        enlacePDF (str): Nomenclatura del fichero meta local sobre sistema de archivos.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_html, identificador, fecha_decreto, seccion, subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Compone tabla estructurada transitoria limpia global como base DataFrame enlazando los campos de resolución en el BON.

    Args:
        enlace_html (str): Reconstrucción absoluta local o link extraido del decreto explícito (Página Web individual).
        identificador (str): Etiqueta posicional correlativa BON+Año+Dec.
        fecha_decreto (str): Referencial del boletín que alinea de dónde extrajo este valor nominal (Match originario regex).
        seccion (str): Clasificador agrupador jerárquico Padre principal BON.
        subseccion (str): Clasificador agrupador inferior Secundario o resolutivo suborgánico.
        contenido_text (str): Lo capturado o empaquetado y purgado inyector (Beautifulsoup HTML natural en web externa).
        enlace_pdf (str): El puente unívoco PDF al servidor u objeto absoluto estático si aplica origen general del script.
        ruta_guardar_pdf (str): Nombramiento y localización final local.

    Returns:
        pd.DataFrame: DataFrame mono-escala con columnas nativas uniformes e injerto base saneado por iteración simple de Series.
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
    """Orquestador iterativo asíncrono sobre el modelo web del Navarra.

    Reconstruye progresivamente sobre iteración bi-anual y meses cruzados desde predefiniciones numéricas el histórico del BON.
    Estructura jerarquización a lo largo del año actual creando los anclajes para volúmenes CSV e indexadores numéricos. 
    Lector especial sub-rutina evalúa PDFs a partir de la prehistoria del BOE oficial (En Navarra: Marzo de 2001 `pdf_si`).
    Comprende los `tr` diarios a su vista local individual subiendo recursivamente el DOM a buscar matchers sobre el boletín padre (MatchRegex temporal para fechar) y decanta en el sumario (`r-hn4`, `seccion`) hacia sus resoluciones enlazadas y su bajada masiva CSV.
    Posee resguardo implícito `.txt` sobre archivo control cruzado de mes general y `url_errores.txt`.

    Args:
        anio_scrappeo (int, kwarg): Nomenclatura pura para bucle macro-base cronológico histórico.
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
        numero_boletin = 1

        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{mes_leido},{numero_boletin}")  #leemos el dia y el mes
                print("Escribimos el mes...")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                mes_leido, numero_boletin = map(int, f.read().strip().split(','))
                numero_boletin += 1
                print("Leemos el mes...")

        print(f"EMPEZAMOS POR EL MES -> {mes_leido}-{anio}")

        for mes in range(mes_leido, 13):  # Desde el mes guardado hasta diciembre (12)

            #Marzo 2001 comienzo pdfs
            pdf_si = False

            if anio < 2001:
                pdf_si = False
            elif anio == 2001:
                if mes <= 2:
                    pdf_si = False
                else:
                    pdf_si = True
            else:
                pdf_si = True
            
            enlace_meses = f"https://bon.navarra.es/es/boletines/-/boletinmes/{anio}/{mes}"
            respuesta, encontrado = intentar_peticion(enlace_meses, ruta_archivo_errores)
            if encontrado == 1 and respuesta and respuesta.status_code == 200:
                try:
                    soup = BeautifulSoup(respuesta.text, 'html.parser')
                    tabla_encontrada = soup.find("tbody", class_ = "table-data")
                    enlaces_dias = tabla_encontrada.find_all("tr")
                    for dia in enlaces_dias:
                        try:
                            numero_boletin += 1
                            enlace_pagina = dia.find_all("td")
                            enlace = enlace_pagina[0].find("a")['href']
                            print(enlace)
                            if pdf_si:
                                enlace_pdf = enlace_pagina[1].find("a")['href']
                                if enlace_pdf:
                                    ruta_guardar_pdf = f"{base_dir_pdfs}/Resumen-Boletin-{numero_boletin}-{anio}.pdf"
                                    respuesta_pdf, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
                                    if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                        descargar_pdf(respuesta_pdf, ruta_guardar_pdf)

                            respuesta_dia, encontrado_dia = intentar_peticion(enlace, ruta_archivo_errores)
                            if encontrado_dia == 1 and respuesta_dia and respuesta_dia.status_code == 200:
                                print(f"Entramos a la página del día")
                                soup = BeautifulSoup(respuesta_dia.text, 'html.parser')
                                next_tag = soup.find("p", id="numero_boletin")

                                num_seccion = 0
                                num_decreto = 0
                                nombre_seccion = ""
                                nombre_subseccion = ""
                                while(next_tag):
                                    if next_tag.name == 'p':
                                        clases = next_tag.get('class', [])
                                        if set(['hd', 'r-hn2']).issubset(clases):
                                            texto = next_tag.get_text(strip=True)
                                            match = re.search(r"\d{1,2} de [a-zA-Z]+ de \d{4}", texto)
                                            if match:
                                                fecha_decreto = match.group(0)
                                                partes = fecha_decreto.lower().split(" de ")
                                                dia_boletin = int(partes[0])
                                                mes_boletin = int(meses[partes[1]])
                                                anio_boletin = int(partes[2])
                                                fecha_obj = f"{dia_boletin}-{mes_boletin}-{anio_boletin}"
                                                
                                        if set(['hd', 'r-hn4', 'a-seccion']).issubset(clases) or set(['hd', 'r-hn4', 'b-seccion']).issubset(clases):
                                            nombre_seccion = next_tag.get_text(strip=True)
                                            num_seccion += 1
                                            num_decreto = 0
                                            nombre_subseccion = None
                                            print(f"Nueva seccion: {nombre_seccion}")
                                        
                                        if set(['hd', 'r-hn5', 'a-subseccion']).issubset(clases) or set(['hd', 'r-hn5', 'b-subseccion']).issubset(clases):
                                            nombre_subseccion = next_tag.get_text(strip=True)
                                            print(f"Nueva subseccion: {nombre_seccion}")

                                        if next_tag.name == 'p' and not next_tag.has_attr('class'):
                                            enlace_a = next_tag.find("a")
                                            enlace_decreto = enlace_a['href']

                                            if enlace_decreto:
                                                respuesta_decreto, encontrado_decreto = intentar_peticion(enlace_decreto, ruta_archivo_errores)
                                                if encontrado_decreto == 1 and respuesta_decreto and respuesta_decreto.status_code == 200:
                                                    num_decreto += 1
                                                    identificador = f"BON-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                                                    soup = BeautifulSoup(respuesta_decreto.text, 'html.parser')
                                                    contenido = soup.find('p', class_="contenido")
                                                    contenido_texto = contenido.get_text(strip = True)
                                                    if pdf_si:
                                                        df = crear_df_temporal(enlace_decreto, identificador, fecha_obj, nombre_seccion, nombre_subseccion, contenido_texto, enlace_pdf, ruta_guardar_pdf)
                                                    else:
                                                        df = crear_df_temporal(enlace_decreto, identificador, fecha_obj, nombre_seccion, nombre_subseccion, contenido_texto, None, None)
                                                    guardar_contenido_csv(df, base_dir_csv, anio)
                                                    print(f"Guardamos contenido del decreto: Bol-{numero_boletin}-{num_seccion}-{num_decreto}-Anio-{anio}")
                                                    time.sleep(1)
                                        next_tag = next_tag.find_next_sibling()
                                        time.sleep(0.5)
                                    else:
                                        next_tag = next_tag.find_next_sibling()
                            elif encontrado == 1 and respuesta.status_code == 404:
                                print(f"No existe a partir del boletin: {numero_boletin}")


                            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                print(f"Guardamos el fichero en el boletin: {mes}-{numero_boletin - 1}")
                                f.write(f"{mes_leido},{numero_boletin}")

                        except Exception as e:
                            print(f"Error inesperado en el día {dia}: {e}")
                            dia -= 1
                            print("Volvemos a intentar descargar el dia ")
                            continue
                    
                    if mes == 12:
                        break
                except Exception as e:
                    print(f"Error inesperado en el día {dia}: {e}")
                    continue

                except ChunkedEncodingError as e:
                    print(f"Error en la transferencia de datos: {e}")
                    continue
            
                except requests.exceptions.RequestException as e:
                    print(f"Intento rechazado")
                    continue

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)


