"""Recolector del Boletín Oficial de la Comunidad de Madrid (BOCM).

Este avanzado script ejecuta la extracción, guardado y estructuración central
de los edictos emitidos en el área de Madrid. Usa un sistema de seguimiento
combinado de año/mes/dia y recuento por número de boletín.
Integra potentes adaptadores capaces de lidiar con modificaciones estructurales
entre boletines históricos (solo PDF) o boletines post-2010 (HTML ricos
con estructura definida, links Epub/XML listos y metadatos explícitos en HTML).

Attributes:
    anio_scrappeo (int): El año inicial definido para la recolección, defecto 1979.
    calendario (dict): Formato referencial de estructura de días al año.
    script_dir (str): Directorio raíz base de operaciones y depósito.
    todas_columnas (set): Set global (legacy) usado en desarrollos colaterales/debug.
"""

import os
from bs4 import BeautifulSoup
import requests
from datasets import Dataset
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

#Código listo para scrapear, si se para en algunos años, simplemente volver a ejeutar
#esta preparado par continuar, ya que hay URL que no siguen patron por eso se corta


def limpiar_texto(texto):
    """Depura la cadena de texto de saltos y espaciados blancos excesivos.

    Args:
        texto (str): Texto general bruto.

    Returns:
        str: Cadena normalizada.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Guarda rastro de los accesos defectivos al directorio de errores.

    Args:
        archivo_errores (str): Path de archivo absoluto terminando en su prefijo.
        url_dia (str): Patrón http origen del error irresoluble.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Capa de red enriquecida con loops de seguridad antibloqueo.

    Reevalúa descargas a páginas caídas o mal formadas espaciando llamadas.
    Protege ante el temido ChunkedEncodingError por cortes de proxy.

    Args:
        url_buscar (str): Path objetivo del BOE de Madrid.
        ruta_errores (str): Directorio con el flag de fallo final.

    Returns:
        tuple[requests.models.Response|None, int]: Response activo e int liso indicativo del exito(1).
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
    """Acopla los resultados documentales recogidos sobre el repositorio DataFrame.

    Usa la modalidad append ('a') sobre discos para evitar cargas masivas sobre
    memoria principal de servidor/ejecutor.

    Args:
        df (pd.DataFrame): Objeto individual con la recolección actual.
        ruta (str): Directorio raíz del año donde vive el CSV.
        anio (int|str): Identificador explícito clave del CSV.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Guardamos en el csv...")

def descargar_pdf(response_pdf, enlacePDF):
    """Vuelca de forma segura el payload streaming (.Response) del documento a un file PDF.

    Args:
        response_pdf (requests.models.Response): Instancia activa retentiva del PDF.
        enlacePDF (str): Link/Directorio completo del documento.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def descargar_xml(response, path):
    """Registra los ficheros estándar XML ofrecidos en el portal moderno BOCM.

    Args:
        response (requests.models.Response): Flujo binario con el payload XML.
        path (str): Recurso completo adonde será enviado.
    """
    try:
        with open(path, 'wb') as f:
            f.write(response.content)
        print(f"Archivo XML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo XML en {path}: {e}")

def descargar_epub(response, path):
    """Guarda la variante de libro electrónico del registro si estuviera activa.

    Args:
        response (requests.models.Response): Stream que porta el archivo epub.
        path (str): Ruta preestablecida del objetivo epub.
    """
    try:
        with open(path, 'wb') as f:
            f.write(response.content)
        print(f"Archivo EPUB guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo EPUB en {path}: {e}")

def descargar_html(response, path):
    """Materializa el hipertexto extraído como un snapshot fiel (.html) a los servidores.

    Args:
        response (requests.models.Response): Sesión completada con atributo .text rico.
        path (str): Lugar destino premarcado que comparta nombre con el Identificador.
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(response.text)
        print(f"Archivo HTML guardado en: {path}")
    except Exception as e:
        print(f"Error al guardar el archivo HTML en {path}: {e}")

def almacenar_en_csv(identificador, html_enlace, pdf_enlace, soup, seccion, decreto, numero_boletin, ruta_relativa_pdf, ruta_relativa_html, ruta_relativa_xml, ruta_relativa_epub, base_dir_csv, anio, base_dir_txt,ruta_relativa_txt):
    """Recolector semántico profundo contra las variopintas plantillas web del BOCM.

    Extrae, analiza, e intenta derivar con inteligencia artificial básica los bloques
    título, subtítulo y cuerpo basándose en marcas tipográficas de Madrid ("c2", "c6", strong).
    Elimina contenido duplicado derivado entre título principal y comienzo de párrafo para dejarlo limpio
    y finalmente lo despacha al módulo de 'guardar_contenido'.

    Args:
        identificador (str): Etiqueta asignadora (Primary Key).
        html_enlace (str): Hipervínculo del origen.
        pdf_enlace (str): Hipervínculo estático del BOE descargable adjunto.
        soup (BeautifulSoup): Puntero al DOM parseado por el script superior.
        seccion (int|str): Fracción local del boletín sobre la que operaba.
        decreto (int|str): Cuenta ascendente frente al edicto.
        numero_boletin (int|str): Índice absoluto contable del boletín de la Comunidad.
        ruta_relativa_pdf (str): Cadena descriptiva de su sub-directorio.
        ruta_relativa_html (str): Cadena descriptiva interna.
        ruta_relativa_xml (str): Cadena descriptiva interna XML.
        ruta_relativa_epub (str): Cadena descriptiva interna EPUB.
        base_dir_csv (str): Ubicación root donde descansa la base de datos CSV.
        anio (int): Instancia cronológica para separar.
        base_dir_txt (str): Raíz teórica para texto crudo puro (comentada uso residual).
        ruta_relativa_txt (str): Subdivisión para depósitos TXT referida internamente (comentada).
    """
    global todas_columnas
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day

    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"    #Obtenemos fecha actual para guardar en el csv

    ruta_pdf = f"{ruta_relativa_pdf}/{identificador}.pdf"


    fecha_boletin = soup.find("span", class_="date-display-single")
    fecha = fecha_boletin.get_text(strip=True) if fecha_boletin else ""

    cabeceras = soup.find("div", id="cabeceras")
    titulo = None
    subtitulo1 = None
    subtitulo2 = None

    try:
        # Extraer título y subtítulos de años posteriores
        titulos = cabeceras.find_all("p", style="text-align:center; margin: 0; margin-bottom: 1em;")
        titulo = titulos[0].get_text(strip=True) if len(titulos) > 0 else ""
        subtitulo1 = titulos[1].get_text(strip=True) if len(titulos) > 1 else ""

        subtitulo2_ = cabeceras.find_all("p", style="text-align:center; margin: 0; margin-bottom: 0.5em;")
        subtitulo2 = subtitulo2_[0].get_text(strip=True) if len(subtitulo2_) > 0 else "" 


        #si no ha cogido de antes es que son años anteiores porque hay distintos htmls
        if not titulo:
            p_tags = soup.find_all("p", class_="c2")
            for p in p_tags:
                strong_tag = p.find("strong", class_="c6")  # Esto es el título
                if strong_tag:
                    titulo = strong_tag.get_text(strip=True)
                elif p.find("strong"):
                    big_tag = p.find("strong").find("big")  # Esto es el subtítulo
                    if big_tag:
                        if not subtitulo1:
                            subtitulo1 = big_tag.get_text(strip=True)
                        elif not subtitulo2:
                            subtitulo2 = big_tag.get_text(strip=True)
                        else:
                            break
    except Exception as e:
        print(f"Escepcion: {e}")
        pass

    try:
        # Extraer contenido dentro del cuerpo
        cuerpo = soup.find("div", id="cuerpo") or soup.find("td", valign="top")
        if cuerpo:
            parrafos = [p.get_text(strip=True) for p in cuerpo.find_all(["p", "td"])]
            contenido = " ".join(parrafos)
            
            # Excluir el título y subtítulos del contenido si los detectamos en el cuerpo
            if titulo:
                contenido = contenido.replace(titulo, "")
            if subtitulo1:
                contenido = contenido.replace(subtitulo1, "")
            if subtitulo2:
                contenido = contenido.replace(subtitulo2, "")
            
            contenidotxt = "\n".join(parrafos)
        else:
            contenido = contenidotxt = ""
    except Exception as e:
        print(f"Escepcion: {e}")
        pass

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha,
        "Comunidad": titulo,
        "Titulo": subtitulo1,
        "Subtitulo": subtitulo2,
        "Contenido": contenido,
        "Url_pdf": pdf_enlace,
        "Url_html": html_enlace,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_pdf
    }])

    """ruta_relativa_txt = f"{ruta_relativa_txt}/{identificador}.txt"
    # Guardar contenido en un archivo .txt
    try:
        nombre_archivo = os.path.join(base_dir_txt, f"{identificador}.txt")
        with open(nombre_archivo, "w", encoding="utf-8") as file:
            file.write(contenidotxt)
        print(f"Contenido guardado en {nombre_archivo}")
        nuevo_df["Ruta_txt"] = ruta_relativa_txt

    except Exception as e:
        print(f"Error al guardar el archivo de texto: {e}")"""
        
    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    guardar_contenido(nuevo_df, base_dir_csv, anio)

def comprobar_suplementos(base_dir_pdf, base_boletin, fecha, numero_boletin, ruta_archivo_errores, dia, mes , anio, seccion):
    """Módulo auxiliar que persigue ediciones y boletines de publicación extraordinaria (Suplementos 1 y 2).

    Aprovecha patrones fijos de los suplementos (-supl-1-XX y -supl-XX) y lanza llamadas.
    Si retorna positivo con un PDF general anexo o botones de "Descargar el boletín completo", 
    asume ese suplemento lo descarga catalogado de forma unitaria en toda la cadena.

    Args:
        base_dir_pdf (str): Espacio vital del árbol PDF.
        base_boletin (str): Prefijo inmutable HTTP oficial bocm.
        fecha (str): ID temporal formato aglutinado (ej. 20240402).
        numero_boletin (int|str): Cifra identificador.
        ruta_archivo_errores (str): Path al bloque de error.
        dia (int): Referencial del día de consulta.
        mes (int): Referencial del mes.
        anio (int): Referencial del año.
        seccion (int): Número asignado lógicamente por compatibilidad al índice genérico.
    """

    enlace_suplemento = f"{base_boletin}{fecha}-supl-1-{numero_boletin}"
    enlace_suplemento2 = f"{base_boletin}{fecha}-supl-{numero_boletin}"

    #Decargamos primer suplemento
    respuesta_suplemento, encontrado = intentar_peticion(enlace_suplemento, ruta_archivo_errores)
    if encontrado == 1 and respuesta_suplemento and respuesta_suplemento.status_code == 200:
        print(f"Entramos al suplemento: {dia} mes: {mes} anio: {anio}")
        soup_suplemento = BeautifulSoup(respuesta_suplemento.text, "html.parser")
        pdf_link = soup_suplemento.find('a', string="Descargar el boletín completo")['href']
        response_pdf, encontrado_pdf = intentar_peticion(pdf_link, ruta_archivo_errores)

        if encontrado_pdf == 1 and response_pdf and response_pdf.status_code == 200:
            pdf_file = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{seccion}-Suplemento1.pdf"
            enlace_almacena_pdf = os.path.join(base_dir_pdf, pdf_file)
            descargar_pdf(response_pdf,enlace_almacena_pdf)

    #Descargamos supemento2
    respuesta_suplemento2, encontrado2 = intentar_peticion(enlace_suplemento2, ruta_archivo_errores)
    if encontrado2 == 1 and respuesta_suplemento2 and respuesta_suplemento2.status_code == 200:
        print(f"Entramos al suplemento 2: {dia} mes: {mes} anio: {anio}")
        soup_suplemento2 = BeautifulSoup(respuesta_suplemento2.text, "html.parser")
        pdf_link2 = soup_suplemento2.find('a', string="Descargar el boletín completo")['href']
        response_pdf2, encontrado_pdf2 = intentar_peticion(pdf_link2, ruta_archivo_errores)

        if encontrado_pdf2 == 1 and response_pdf2 and response_pdf2.status_code == 200:
            pdf_file2 = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{seccion}-Suplemento2.pdf"
            enlace_almacena_pdf2 = os.path.join(base_dir_pdf, pdf_file2)
            descargar_pdf(response_pdf2,enlace_almacena_pdf2)

def comprobar_seccion(soup, num_seccion, num_decreto, apartado, base_dir_pdf, dia, mes, anio, numero_boletin, ruta_archivo_errores, base_dir_html, base_dir_epub, base_dir_xml, base_dir_csv, base_dir_txt):
    """Lógica delegada que disecciona links alternos (HTML/XML/EPUB/PDF) ubicuos en portales contemporáneos BOCM.

    Es llamada por el controlador si se ha logrado acceso total, identifica en la grid div HTML las fuentes
    existentes para descargar los complementos o la ficha troncal que se trasladará despues al 'almacenar_en_csv'.

    Args:
        soup (BeautifulSoup): Controlador activo web parseando la zona de ese decreto.
        num_seccion (int): Número autoincrementado relativo al tema.
        num_decreto (int): Subnúmero autoincrementado de documento.
        apartado (bs4.element.Tag): Etiqueta aislada referenciando este grupo HTML puntual procesado.
        base_dir_pdf (str): Raíz hacia los descargables PDF locales.
        dia (int): Cifra de iteración actual del dia.
        mes (int): Cifra de iteración mensual.
        anio (int): Año temporal de trabajo maestro.
        numero_boletin (int|str): Identificador.
        ruta_archivo_errores (str): Link de error para traspasarla a 'intentar_peticion'.
        base_dir_html (str): Ruta asignada para volcado web si necesario.
        base_dir_epub (str): Ruta asignada para volcado epub.
        base_dir_xml (str): Ruta asignada para documentos XML.
        base_dir_csv (str): Enlace principal hacia el núcleo datos en hoja CSV.
        base_dir_txt (str): Raíz destino en disco de transcripciones brutas texto puras.
    """
    #cogemos los enlaces
    pdf_link = apartado.select_one("div.field-name-field-pdf-file a")
    html_link = apartado.select_one("div.field-name-field-html-file a")
    epub_link = apartado.select_one("div.field-name-field-epub-file a")
    xml_link = apartado.select_one("div.field-name-orden-xml a")

    ruta_relativa_xml = f"/{anio}/XML"
    ruta_relativa_html = f"/{anio}/HTML"
    ruta_relativa_pdf = f"/{anio}/PDF"
    ruta_relativa_epub = f"/{anio}/EPUB"
    ruta_relativa_txt = f"/{anio}/TXT"

    pdf_enlace = pdf_link["href"] if pdf_link else None
    html_enlace = f"https://www.bocm.es{html_link['href']}" if html_link else None
    epub_enlace = epub_link["href"] if epub_link else None
    xml_enlace = f"https://www.bocm.es{xml_link['href']}" if xml_link else None

    if pdf_enlace:
        pdf_file = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{num_seccion}-Dec-{num_decreto}.pdf"
        enlace_almacena_pdf = os.path.join(base_dir_pdf, pdf_file)
        if os.path.exists(enlace_almacena_pdf):   #Comprobamos que no este el fichero ya descargado
            print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
        else:
            pdf_response, encontrado_pdf = intentar_peticion(pdf_enlace, ruta_archivo_errores)
            if encontrado_pdf == 1 and pdf_response and pdf_response.status_code == 200:
                descargar_pdf(pdf_response, enlace_almacena_pdf)
    """if xml_link:
        xml_file = f"BOCM-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}.xml"
        enlace_almacena_xml = os.path.join(base_dir_xml, xml_file)
        if os.path.exists(enlace_almacena_xml):   #Comprobamos que no este el fichero ya descargado
            print(f"El archivo {xml_file} ya existe. Se omite la descarga.")
        else:
            xml_response, encontrado_xml = intentar_peticion(xml_enlace, ruta_archivo_errores)
            if encontrado_xml == 1 and xml_response and xml_response.status_code == 200:
                descargar_xml(xml_response, enlace_almacena_xml)"""

    if html_enlace:
        html_file = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{num_seccion}-Dec-{num_decreto}.html"
        identificador = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{num_seccion}-Dec-{num_decreto}"
        enlace_almacena_html = os.path.join(base_dir_html, html_file)
        if os.path.exists(enlace_almacena_html):   #Comprobamos que no este el fichero ya descargado
            print(f"El archivo {html_file} ya existe. Se omite la descarga.")
        else:
            html_response, encontrado_html = intentar_peticion(html_enlace, ruta_archivo_errores)
            soup_html = BeautifulSoup(html_response.text, "html.parser")
            if encontrado_html == 1 and html_response and html_response.status_code == 200:
                #descargar_html(html_response, enlace_almacena_html)
                almacenar_en_csv(identificador, html_enlace, pdf_enlace, soup_html, num_seccion, num_decreto, numero_boletin, ruta_relativa_pdf, ruta_relativa_html, ruta_relativa_xml, ruta_relativa_epub, base_dir_csv, anio, base_dir_txt, ruta_relativa_txt)
            
    """if epub_enlace:
        epub_file = f"BOCM-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}.epub"
        enlace_almacena_epub = os.path.join(base_dir_epub, epub_file)
        if os.path.exists(enlace_almacena_epub):   #Comprobamos que no este el fichero ya descargado
            print(f"El archivo {epub_file} ya existe. Se omite la descarga.")
        else:
            epub_response, encontrado_epub = intentar_peticion(epub_enlace, ruta_archivo_errores)
            if encontrado_epub == 1 and epub_response and epub_response.status_code == 200:
                descargar_epub(epub_response, enlace_almacena_epub)"""
    
def scrapear_dias_completos(*, anio_scrappeo:int):
    """Bucle raíz integral para el raspado y extracción por calendario del BOCM.

    Usa bucles inmensos año->mes->días preconfigurados y construye sus targets de URL uniendo 
    un contador histórico ("numero_boletin"). Genera estructuras de datos si no existen y 
    restaura configuraciones de reinicios pasados (archivo.txt).
    Frente a la versión vieja (sin secciones de links, pre 2005/2010), descarga el global usando links CSS incrustados;
    frente a versiones nuevas recorre las vistas y lanza a `comprobar_seccion` todos los anexos detectados en el html.

    Args:
        anio_scrappeo (int, kwarg): Marcador con el año origen inicial introducido sobre consola vía "clize".
    """
    global calendario
    global dataframe_guardado
    for anio in range(anio_scrappeo,anio_scrappeo+1): #leemos cada dos años

        carpeta_anio = os.path.join(script_dir, f"{anio}")
        base_dir_pdfs = os.path.join(script_dir, f"{anio}", "PDF")
        base_dir_csv = os.path.join(script_dir,f"{anio}")
        base_dir_epub = os.path.join(script_dir,f"{anio}", "EPUB")
        base_dir_xml = os.path.join(script_dir,f"{anio}", "XML")
        base_dir_html = os.path.join(script_dir, f"{anio}", "HTML")
        base_dir_txt = os.path.join(script_dir, f"{anio}", "TXT")
        ruta_archivo_errores = os.path.join(script_dir, f"{anio}", "Errores")
        ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

        carpetas = [carpeta_anio, base_dir_pdfs, base_dir_csv, ruta_archivo_errores]

        for carpeta in carpetas:    # Crear las carpetas si no existen
            os.makedirs(carpeta, exist_ok=True)
        
        archivo_csv = f"{base_dir_csv}/{anio}.csv"
        if os.path.exists(archivo_csv):  
            dataframe_guardado = pd.read_csv(archivo_csv, encoding='utf-8')

        print(f"Entramos al anio: {anio}")
        mes_leido = 1
        dia_leido = 1
        numero_boletin = 1
        base_boletin = f"https://www.bocm.es/boletin/bocm-"

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
                    fecha = f"{anio}{mes:02}{dia:02}"
                    url_buscar = f"{base_boletin}{anio}{mes:02}{dia:02}-{numero_boletin}"
                    print(f"Entramos a: {url_buscar}")
                    respuesta_pagina, encontrada_pag = intentar_peticion(url_buscar, ruta_archivo_errores)
                    seccion = 1
                    decreto = 1

                    if encontrada_pag == 1 and respuesta_pagina and respuesta_pagina.status_code == 200:
                        print(f"Entramos a la pagina del dia: {dia} mes: {mes} anio: {anio}")
                        soup = BeautifulSoup(respuesta_pagina.text, "html.parser")

                        enlaces = []
                        base = "https://www.bocm.es/"

                        for link in soup.find_all('a', href=True):
                            if '/boletin-completo/' in link['href']:  # Aquí están todas las secciones
                                enlaces.append(base + link['href'].lstrip('/'))  # Concatenar con la base y limpiar "/"

                        if enlaces:
                            enlaces.pop(0)

                        pdf_file = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{seccion}-Dec-{decreto}.pdf"
                        enlace_almacena_pdf = os.path.join(base_dir_pdfs, pdf_file)

                        try:
                            if len(enlaces) == 0:   #Si no hay secciones es que solo hay pdf
                                if os.path.exists(enlace_almacena_pdf):   #Comprobamos que no este el fichero ya descargado
                                    print(f"El archivo {pdf_file} ya existe. Se omite la descarga.")
                                else:
                                    enlace_boletin = soup.select_one(".field-name-field-pdf-file a")
                                    pdf_boletin = enlace_boletin["href"] if enlace_boletin else None
                                    respuesta_pdf_solo, encontrado_pdf = intentar_peticion(pdf_boletin, ruta_archivo_errores)

                                    if encontrado_pdf == 1 and respuesta_pdf_solo and respuesta_pdf_solo.status_code == 200:
                                        descargar_pdf(respuesta_pdf_solo, enlace_almacena_pdf)

                                    comprobar_suplementos(base_dir_pdfs, base_boletin, fecha, numero_boletin, ruta_archivo_errores, dia, mes, anio, 1)
                            else:
                                num_seccion = 0
                                for enlace in enlaces:
                                    num_seccion += 1
                                    print(f"Entramos a : {enlace}")
                                    respuesta_enlace, encontrado_enlace = intentar_peticion(enlace, ruta_archivo_errores)

                                    if encontrado_enlace == 1 and respuesta_enlace and respuesta_enlace.status_code == 200:
                                        soup = BeautifulSoup(respuesta_enlace.text, "html.parser")
                                        secciones = soup.select("div.view-content div.views-row")
                                        num_decreto = 0
                                        for apartado in secciones:
                                            try:
                                                time.sleep(0.3)
                                                num_decreto += 1
                                                pdf_file = f"BOCM-{dia}-{mes}-{anio}-Boletin-{numero_boletin}-S-{seccion}-Dec-{decreto}.pdf"
                                                enlace_almacena_pdf = os.path.join(base_dir_pdfs, pdf_file)
                                                comprobar_seccion(soup, num_seccion, num_decreto, apartado, base_dir_pdfs, dia, mes, anio, numero_boletin, ruta_archivo_errores, base_dir_html, base_dir_epub, base_dir_xml, base_dir_csv, base_dir_txt)
                                            except Exception as e:
                                                print(f"Escepcion: {e}")
                            numero_boletin += 1

                        except FileNotFoundError as e:
                            print(f"Error al encontrar el archivo: {e}")
                            continue
                        except Exception as e:
                            print(f"Error inesperado: {e}")
                            continue

                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                            print(f"Guardamos el fichero en el dia: {dia}-{mes}")
                            f.write(f"{mes},{dia},{numero_boletin}")


                except Exception as e:
                    print(f"Error inesperado: {e}")
                    continue

            dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)

