"""Recolector del Boletín Oficial de Canarias (BOC).

Este módulo recolecta disposiciones, resoluciones y anuncios publicados
en el BOC. Genera solicitudes de red directamente sobre la estructura de 
directorios organizados por años y boletines (p. ej /boc/year/num/index.html), 
dado que su arquitectura es predecible. Posteriormente, identifica, cruza
y descarga toda la metadata, contenido HTML y documentos PDF enlazados.

Attributes:
    anio_scrappeo (int): El año configurado para iniciar el raspado.
    calendario (dict): Formato referencial de días sobre los meses clásicos.
    script_dir (str): Directorio raíz del script donde se almacenan carpetas del proceso.
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

dataframe_guardado = pd.DataFrame()

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
    """Remueve espacios innecesarios y limpia un texto bruto usando `split`.

    Args:
        texto (str): Cadena a sanear.

    Returns:
        str: Texto limpio con un solo espacio intermedio.
    """
    return " ".join(str(texto).split())

def escribir_url_errores(archivo_errores, url_dia):
    """Guarda en un archivo de texto la URL que no pudo procesarse.

    Args:
        archivo_errores (str): Nombre base o ruta del apuntador txt.
        url_dia (str): La página destino con la que hubo problemas.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Bucle de solicitud reforzado con reconexiones tras fallos de la petición HTTP.

    Tras ejecutar el proxy iterativo 5 veces sin resolución 200/404, deniega
    el intento y expulsa la dirección hacia el registro de control de incidencias.

    Args:
        url_buscar (str): Meta o link para la descarga / consulta.
        ruta_errores (str): Destino .txt de reporte en caso de cancelación.

    Returns:
        tuple[requests.models.Response|None, int]: Tupla que cruza un elemento 
            Response y un resultado lógico (1=success, 0=fail).
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

def guardar_contenido(df, ruta, anio):
    """Modifica el historial central depositando los nuevos datos CSV apendizados.

    Args:
        df (pd.DataFrame): Dataframe conteniendo toda base de metadatos del anuncio.
        ruta (str): Directorio del CSV de almacenamiento masivo.
        anio (int|str): Marca empleada para establecer el nombre del fichero.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Guardamos en el csv...")

def descargar_pdf(response_pdf, enlacePDF):
    """Descarga e inscribe de manera segmentada el resultado en la ruta final local.

    Args:
        response_pdf (requests.models.Response): Componente retornado de una 
            invocación exitosa de requests (stream=True idóneamente).
        enlacePDF (str): Nombre del PDF a asignar.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def descargar_html(response, path):
    """Anota la carga sintáctica devuelta en memoria a un documento estructurado html final.

    Args:
        response (requests.models.Response): Bloque HTTP devuelto tras la consulta web.
        path (str): Vínculo de escritura en la red de almacenamiento.
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Archivo HTML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo HTML en {path}: {e}")

def extraer_fecha_boc(soup):
    """Consulta semánticamente el nombre de la página (title) en búsqueda de la fecha de edición.

    Resuelve una expresión regular sobre el encabezado y deduce matemáticamente el día,
    y traduce la cadena a numeral de mes.

    Args:
        soup (BeautifulSoup): Parseo jerárquico del código del boletín.

    Returns:
        str | None: Marca temporal (DD-MM-YYYY) calculada o None en caso de carencia de tag title.
    """
    try:
        title_text = soup.title.text.strip()
        match = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", title_text)
        if match:
            day, month_name, year = match.groups()
            month_dict = {
                "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
                "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
            }
            month = month_dict.get(month_name.lower())
            if month:
                return f"{int(day)}-{month}-{year}"  # Formato "día/mes/año"
            else:
                print("No se pudo convertir el mes.")
                return None
        else:
            print("No se pudo extraer la fecha del título.")
            return None
    except AttributeError:
        print("No se encontró la etiqueta TITLE en el HTML.")
        return None
    
def crear_df_temporal(enlace_html, seccion, n_decreto, pdf_file, html_file, ruta_relativa_pdf, ruta_relativa_html, ruta_relativa_txt, base_dir_txt, anio, soup, enlace_pdf, boletin):
    """Transcribe y depura atributos HTML de la web hacia un objeto tabular unísono.

    Sigue una bifurcación de recolección de contenido basado en los cambios del BOC:
    para los posts antes de 2010 agrupa todos los parrafos de 'div.conten', mientras 
    que en las subsiguientes aísla identificadores 'span' indeseables.

    Args:
        enlace_html (str): Link al recurso explícito oficial web.
        seccion (str|int): Indice numeral/texto del cajón donde se aglomera la decisión.
        n_decreto (int): Entero descriptivo asociado al número de resolución cronológica en el boletín.
        pdf_file (str): Nombre local del pdf adscrito.
        html_file (str): Nombre estipulado del html auxiliar.
        ruta_relativa_pdf (str): Directorio del árbol de los PDF.
        ruta_relativa_html (str): Directorio del árbol de los HTML.
        ruta_relativa_txt (str): Directorio local si se hubiere volcado a texto.
        base_dir_txt (str): Raíz contenedora absoluta apuntando al bloque TXT.
        anio (int): Período transcurrido sobre el que asienta el proceso general.
        soup (BeautifulSoup): Objeto con la información diseccionada procedente del anuncio particular.
        enlace_pdf (str): Recurso online de donde asoma la publicación PDF final.
        boletin (str|int): Correlativo del ejemplar periódico procesado.

    Returns:
        pd.DataFrame: Tupla con la matriz extraída de un anuncio debidamente mapeado y adecentado.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    ruta_pdf = f"{ruta_relativa_pdf}/{pdf_file}"
    """ruta_html = f"{ruta_relativa_html}/{html_file}"""
    identificador = None

    try:
        identificador = f"BOC-{anio}-Boletin-{boletin}-Seccion-{seccion}-Dec-{n_decreto}"
        fecha_decreto = extraer_fecha_boc(soup)
        titulo = soup.find("h5").get_text(strip=True) if soup.find("h5") else ""
        resumen = soup.find("h3").get_text(strip=True) if soup.find("h3") else ""

        if anio < 2010:
            contenido = " ".join([p.get_text(strip=True) for p in soup.select("div.conten p") if "justificado" not in p.get("class", [])])
            contenido_txt = "\n".join([p.get_text(strip=True) for p in soup.select("div.conten p") if "justificado" not in p.get("class", [])])
        else:
            contenido = " ".join([
                p.get_text(strip=True) 
                for p in soup.select("div.conten p.justificado") 
                if not p.find("span", class_="document_info") and not p.find("span", class_="cve")
                ])

            contenido_txt = "\n".join([
                p.get_text(strip=True) 
                for p in soup.select("div.conten p.justificado") 
                if not p.find("span", class_="document_info") and not p.find("span", class_="cve")
            ])

                    
    except AttributeError:
        print("No se ha encontrado el atributo")

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Título": titulo,
        "Resumen": resumen,
        "Contenido": contenido,
        "Url_pdf": enlace_pdf,
        "Url_html": enlace_html,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_pdf
    }])
    """"Ruta_html": ruta_html"""

    """ruta_txt = f"{ruta_relativa_txt}/{identificador}.txt"

    try:
        nombre_archivo = os.path.join(base_dir_txt, f"{identificador}.txt")
        with open(nombre_archivo, "w", encoding="utf-8") as file:
            file.write(contenido_txt)
        print(f"Contenido guardado en {nombre_archivo}")
        nuevo_df["Ruta_txt"] = ruta_txt

    except Exception as e:
        print(f"Error al guardar el archivo de texto: {e}")"""

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x)) 

    return nuevo_df

def comprobar_seccion(seccion,n_decreto, enlace_pdf, enlace_html, base_dir_pdf, base_dir_html, base_dir_txt, ruta_archivo_errores, boletin, anio):
    """Comanda la ejecución secundaria del hilo encargada de la descarga de cada resolución.

    Confirma si los archivos (PDF/HTML) existen localmente para salvar peticiones de bajada redundantes y, en su interín,
    descarga la red o elabora invocaciones de lectura, para más tarde transferir control al ensamblador semántico 'crear_df_temporal'.

    Args:
        seccion (str|int): Referencia global de agrupación jerárquica canaria.
        n_decreto (int): Ubicación interna contable asignada frente a los demás en el cuerpo del sumario.
        enlace_pdf (str): Path abosulto de hipervínculo para su archivo oficial.
        enlace_html (str): Path absoluto online de reenvío referencial localizando los datos.
        base_dir_pdf (str): Depósito raíz local /PDF general.
        base_dir_html (str): Depósito raíz local /HTML general.
        base_dir_txt (str): Depósito raíz local /TXT general.
        ruta_archivo_errores (str): Path de loggueo de fallos.
        boletin (str|int): Cuantil identificando el documento del período vigente.
        anio (int): Marcador estacional temporal del bucle maestro.

    Returns:
        pd.DataFrame: El compendio resuelto aportado por los análisis HTML albergando de metadata y cuerpo literario procesado de forma unívoca.
    """

    ruta_relativa_html = f"/{anio}/HTML"
    ruta_relativa_pdf = f"/{anio}/PDF"
    ruta_relativa_txt = f"/{anio}/TXT"
    pdf_file = None
    dataframe = pd.DataFrame()

    if enlace_pdf:
        pdf_file = f"BOC-{anio}-Boletin-{boletin}-Seccion-{seccion}-Dec-{n_decreto}.pdf"
        enlace_almacena_pdf = os.path.join(base_dir_pdf, pdf_file)
        if os.path.exists(enlace_almacena_pdf):  
            print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
        else:
            pdf_response, encontrado_pdf = intentar_peticion(enlace_pdf, ruta_archivo_errores)
            if encontrado_pdf == 1 and pdf_response and pdf_response.status_code == 200:
                descargar_pdf(pdf_response, enlace_almacena_pdf)

    if enlace_html:
        html_file = f"BOC-{anio}-Boletin-{boletin}-Seccion-{seccion}-Dec-{n_decreto}.html"
        enlace_almacena_html = os.path.join(base_dir_html, html_file)
        if os.path.exists(enlace_almacena_html): 
            print(f"El archivo {html_file} ya existe. Se omite la descarga.")
        else:
            html_response, encontrado_html = intentar_peticion(enlace_html, ruta_archivo_errores)
            if encontrado_html == 1 and html_response and html_response.status_code == 200:
                #descargar_html(html_response, enlace_almacena_html)
                #Guardamos csv
                soup = BeautifulSoup(html_response.text, "html.parser")
                dataframe = crear_df_temporal(enlace_html, seccion, n_decreto, pdf_file, html_file, ruta_relativa_pdf, ruta_relativa_html, ruta_relativa_txt, base_dir_txt, anio, soup, enlace_pdf, boletin)
    return dataframe

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Punto de inicialización primario para la absorción de los Boletines de Canarias (BOC).

    Configura subdirectorios para resguardar CSVs o archivos binarios. Su ciclo
    central se apoya en URLs estéticas deducibles partiendo de preposiciones de fecha (anio, numero_boletin).
    Itera buscando validaciones 200/404 frente al catálogo de URLs, y una vez visibilizados aparta
    las direcciones a PDFs (diferentes en metodología base 2009 respecto a las postetiores) y transfiere la recolección fina a otras ramas lógicas. Se preserva
    con registro secuencial local si fuese interceptado/cerrado.

    Args:
        anio_scrappeo (int, kwarg): Marcador con el año originario de proceso introducido vía comando (CLIze).
    """
    global calendario
    global dataframe_guardado

    for anio in range(anio_scrappeo,anio_scrappeo+1): #leemos cada dos años

        #Creación carpetas por anio
        carpeta_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdf = os.path.join(script_dir, f"{anio}", "PDF")
        base_dir_csv = os.path.join(script_dir,f"{anio}")
        base_dir_txt = os.path.join(script_dir,f"{anio}", "TXT")
        base_dir_html = os.path.join(script_dir, f"{anio}", "HTML")
        ruta_archivo_errores = os.path.join(script_dir, f"{anio}", "Errores")
        ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [carpeta_anio, base_dir_pdf, base_dir_csv, ruta_archivo_errores]

        # Crear las carpetas si no existen
        for carpeta in carpetas:
            os.makedirs(carpeta, exist_ok=True)

        archivo_csv = f"{base_dir_csv}/{anio}.csv"
        if os.path.exists(archivo_csv): 
            dataframe_guardado = pd.read_csv(archivo_csv, encoding='utf-8')

        print(f"Entramos al anio: {anio}")
        numero_boletin = 1

        if not os.path.exists(ruta_continuar):
            with open(ruta_continuar, 'w', encoding='utf-8') as f:
                f.write(f"{numero_boletin}")  
                print("Escribimos el mes...")
        else:
            with open(ruta_continuar, 'r', encoding='utf-8') as f:
                numero_boletin = int(f.read().strip())
                print("Leemos el mes...")

        if anio == 1981:
            numero_boletin = 5
        elif anio == 1982:
            numero_boletin = 11

        print(f"EMPEZAMOS POR EL BOLETÍN -> {numero_boletin}-{anio}")

        while numero_boletin < 366:
            try: 
                url_dia = f"https://www.gobiernodecanarias.org/boc/{anio:03}/{numero_boletin:03}/index.html"

                respuesta, encontrado = intentar_peticion(url_dia, ruta_archivo_errores)

                if encontrado == 1 and respuesta and respuesta.status_code == 200:
                    print(f"Entramos al boletin: {numero_boletin}")
                    soup = BeautifulSoup(respuesta.text, "html.parser")

                    disposiciones = []
                    base_para_enlaces = "https://www.gobiernodecanarias.org/"

                    enlace_html_ = None
                    enlace_pdf_ = None

                    num_seccion = 0

                    if anio < 2009:
                        print(f"Entramos a por enlaces del boletin: {numero_boletin}")

                        for item in soup.find_all("ul", class_="summary"):    # Por cada sección
                            num_seccion += 1
                            num_decreto = 0
                            for li in item.find_all("li", class_="justificado"):    # Leer cada decreto y coger enlaces
                                num_decreto += 1
                                enlace_html_tag = li.find("a", class_="abstract")
                                enlace_pdf_tag = li.find("a", class_="nouline", title=lambda t: t and "Descarga" in t)

                                enlace_html = enlace_html_tag["href"] if enlace_html_tag else None
                                enlace_pdf = enlace_pdf_tag["href"] if enlace_pdf_tag else None

                                if enlace_html or enlace_pdf:
                                    enlace_html_ = f"{base_para_enlaces}{enlace_html}"
                                    enlace_pdf_ = f"{base_para_enlaces}{enlace_pdf}"
                                    disposiciones.append({
                                        "html": enlace_html_,
                                        "pdf": enlace_pdf_,
                                        "seccion": num_seccion,
                                        "decreto": num_decreto
                                    })
                    else:   
                        num_decreto = 0
                        for section in soup.find_all(["h4", "h5"]):  # cada sección
                            if section.name == "h5":
                                num_seccion += 1
                                num_decreto = 0
                                next_tag = section.find_next_sibling()

                                while next_tag and next_tag.name == "ul":  # Captura todos los <ul> después del <h5>
                                    for li in next_tag.find_all("li", class_="justificado_boc"):  # cada decreto
                                        num_decreto += 1
                                        div_cve_tag = li.find("div", class_="cve justificado")

                                        html_tag = li.find("a", href=True) 
                                        pdf_tag = next((a for a in li.find_all("a", href=True) if a['href'].endswith('.pdf')), None)

                                        enlace_html = f"https://www.gobiernodecanarias.org{html_tag['href']}" if html_tag and html_tag['href'].endswith('.html') else None
                                        enlace_pdf = f"https://www.gobiernodecanarias.org{pdf_tag['href']}" if pdf_tag and pdf_tag['href'].endswith('.pdf') else None

                                        """enlace_html_tag = div_cve_tag.find("a", title="Vista previa (VersiÃ³n no oficial)") if div_cve_tag else None
                                        enlace_pdf_tag = li.find("a", title="Descargar en formato PDF")

                                        enlace_html = enlace_html_tag["href"] if enlace_html_tag else None
                                        enlace_pdf = enlace_pdf_tag["href"] if enlace_pdf_tag else None"""

                                        if enlace_html or enlace_pdf:
                                            disposiciones.append({
                                                "html": enlace_html,
                                                "pdf": enlace_pdf,
                                                "seccion": num_seccion,
                                                "decreto": num_decreto
                                            })
                                    
                                    next_tag = next_tag.find_next_sibling()

                    for decreto in disposiciones:
                        try:
                            time.sleep(0.3)
                            enlace_html_ = decreto['html']
                            enlace_pdf_ = decreto['pdf']
                            seccion = decreto['seccion']
                            n_decreto = decreto['decreto']
                            dataframe = comprobar_seccion(seccion,n_decreto, enlace_pdf_, enlace_html_, base_dir_pdf, base_dir_html, base_dir_txt, ruta_archivo_errores, numero_boletin, anio)
                            guardar_contenido(dataframe, base_dir_csv, anio)

                        except Exception as e:
                            print(f"Error inesperado: {e}")
                            continue

                    with open(ruta_continuar, 'w', encoding='utf-8') as f:
                        print(f"Guardamos en el fichero el numero del boletin: {numero_boletin}")
                        f.write(f"{numero_boletin}")
                    
                    numero_boletin += 1

                elif encontrado == 1 and respuesta.status_code == 404:
                    print(f"No existe a partir de {numero_boletin}...")
                    break
 
            except Exception as e:
                print(f"Error inesperado: {e}")
                continue

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)

