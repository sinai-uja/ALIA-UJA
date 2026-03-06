"""Recolector secundario del Butlletí Oficial de les Illes Balears (BOIB) - Versión 2.

Este script es una variante avanzada o segunda iteración del scraper BOIB.
Automatiza la extracción sistemática de metadatos, textos en HTML y documentos PDF.
Incluye procesamiento de OCR avanzado utilizando PyMuPDF para lectura rápida
y Tesseract (junto a pdf2image) como respaldo para PDFs estáticos o escaneados,
además de renderizado dinámico mediante Selenium headless. Por último, comprime
y convierte los datos resultantes anuales a Parquet y un archivo ZIP consolidado.

Attributes:
    anio_scrappeo (int): El año fijo inicial de extracción (estático, ejemplo 2000).
    script_dir (str): Directorio raíz del script para guardar temporales, archivos OCR e hitos de progreso.
    calendario (dict): Formato referencial de iteración temporal de días sobre los meses.
    meses (dict): Mapeo literal español-numérico para formato cruzado de fechas.
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
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
import pandas as pd
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
import zipfile

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

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

def iniciar_driver():
    """Inicializa y configura una instancia del navegador Chrome en modo Headless.

    Establece las opciones necesarias para ejecutar Selenium sin interfaz gráfica (headless),
    omitiendo la carga de GPU, evitando problemas de memoria compartida extrema en Docker (dev-shm-usage)
    y suprimiendo todos los reportes de consola molestos preestablecidos por Chrome.

    Returns:
        webdriver.Chrome: Objeto driver para invocar peticiones o iterar DOM dinámico.
    """
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument("--log-level=3") 
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def limpiar_texto(texto):
    """Elimina tabulaciones explícitas, espacios consecutivos inútiles y saltos de línea irregulares.

    Args:
        texto (str): Segmento extraído crudo de una lectura en BeautifulSoup.

    Returns:
        str: Texto uniforme con espacios singulares estándar.
    """
    return " ".join(str(texto).split()) 

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae la capa de texto puro directo de un archivo PDF vía PyMuPDF.

    Carga el PDF al vuelo llamando forzosamente la recolección de basura, intentando compilar 
    directamente el text-layer integrado del propio archivo original, en contraste al OCR.

    Args:
        pdf_path (str): Sendero base al documento en repositorio.
        min_chars (int, optional): Cuota condicional mínima alfanumérica de aceptación de validación. Default a 50.

    Returns:
        tuple[str, bool]: Texto puro si cumple, y bandera booleana True de confirmación. En caso nulo, (`""`, `False`).
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
    """Incide de forma textual y acumulativa un fallo URL en el listado negro de red.

    Args:
        archivo_errores (str): Path de archivo resolutor. Omitir '.txt'.
        url_dia (str): Valor puro del localizador.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Lanza y protege una recolección HTTP GET tolerando cierres y latencias web.

    Comprende los errores estándar 200 (OK), 404 (Vacío) integrándole bucle incremental
    de 5 descansos intermedios ante anomalías estructurales como desconexión SSL o latencia en el server.

    Args:
        url_buscar (str): Endpoint a consultar.
        ruta_errores (str): Fichero rastreador por si se desborda y fracasan todos los intentos cíclicos.

    Returns:
        tuple[requests.models.Response | None, int]: Dupla de objeto web con estado crudo;
            con valor 1 para su uso continuo o valor 0 ante fallas totales de servidor/cliente.
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
    """Vuelca en bloque y salvaguarda permanentemente un DataFrame Pandas de un registro en su respectivo CSV.

    Args:
        df (pd.DataFrame): Tabulado unifilar del anuncio o decreto.
        ruta (str): Directorio raíz ancla del año.
        anio (int|str): Identificador cronológico anual usado para empalmar y nombrar la BD local.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Extrae escalonadamente o in-stream un buffer continuo PDF al entorno de archivos.

    Usa paquetería de 8KB mitigando así bloqueos de asignación en RAM del host.

    Args:
        response_pdf (requests.models.Response): Instancia base devuelta validada previamente en `intentar_peticion()`.
        enlacePDF (str): Nombre final designado en disco hacia su guardado persistente.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(identificador, fecha_formateada, nombre_seccion, contenido_texto, texto_pdf_re, text, enlace_pdf, ruta_guardar_pdf):
    """Recrea y empaqueta en Panda DF un metadato tabular estructurado preestablecido completo para el BOIB.

    Registra metadatos como fecha, identificativo compuesto orgánico, titulo, resúmenes limpios originados en la red y subidas web crudas, concatenando todo globalmente.

    Args:
        identificador (str): Placa estática sintética, usualmente combinando "BOIB", Años, Boletines y Decretos.
        fecha_formateada (str): Tiempo oficial recuperado.
        nombre_seccion (str): Clasificador jerárquico principal rastreado en index principal.
        contenido_texto (str): Cuerpo extraído limpio de sub HTML si estuviese disponible.
        texto_pdf_re (str): Bloque secundario inyectable del procesamiento final derivado del sub-modulo `process_pdf`.
        text (str): Total puro adjunto y compilado del bloque `contenido_texto` + `texto_pdf_re`.
        enlace_pdf (str): Conector universal hacia el activo digital en la web origen.
        ruta_guardar_pdf (str): Reflejo local que actúa como almacenamiento persistido en la run actual.

    Returns:
        pd.DataFrame: DF formateado limpio con los campos `(id, fecha_decreto, título, contenido, url, fecha_lectura, ruta_pdf)`.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "id": identificador,
        "fecha_decreto": fecha_formateada,
        "título": nombre_seccion,
        "contenido": contenido_texto,
        "url": enlace_pdf,
        "fecha_lectura": fecha_lectura,
        "ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x))  # Limpieza de texto columna por columna

    return nuevo_df

def extract_text_direct(pdf_path, min_chars=50 ):
    """Extrae texto eficientemente desde el fichero físico cargado de un formato PDF empleando PyMuPDF.

    (Función duplicada en el script)

    Args:
        pdf_path (str): Sendero base al documento en repositorio.
        min_chars (int, optional): Cuota condicional mínima alfanumérica de aceptación de validación. Default a 50.

    Returns:
        tuple[str, bool]: Texto puro y booleano indicando éxito.
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

def extract_text_ocr(pdf_path, language='spa', poppler_path=r'C:\poppler-24.08.0\Library\bin'):
    """Recurre a procesador OCR Tesseract visualmente traduciendo en matriz fotos gráficas desde pdf2image.

    Args:
        pdf_path (str): Componente de disco duro apuntando al file actual PDF.
        language (str, optional): Selector de gramática/diccionario OCR en Tesseract base. Defaults to 'spa'.
        poppler_path (str, optional): Rutina necesaria o motor nativo convertidor del framework pdf2image. defaults C/..

    Returns:
        str: Toda la conglomeración traducida extraída por bloque o páginas con terminación literal string, vacio `""` en caso de fallas masivas.
    """
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=poppler_path)
        
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
    """Enrutador automático orquestado de extracción generalizada texto-PDF.

    Determina velozmente mediante el evaluador in-memoria directo si contiene caracteres seleccionables.
    Si fuese menor del límite umbral de `min_chars`, invoca retroactivamente al subsistema puramente gráfico OCR de `pytesseract`.

    Args:
        pdf_file (str): Elemento absoluto de localización archivo.

    Returns:
        str: Recuperación general condensada limpia final, sea por capa embebida directa como por deducciones visuales o log purgado `""` de crash del driver binario.
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

def verificar_carga(driver, selector, busqueda):
    """Comprobador recurrente implacable con refresco para las páginas altamente dinámicas o inconsistentes.

    Mediante el motor dinámico de Selenium intercepta hasta un límite de 5 refrescos activos de página entera
    la visibilidad de un elemento crítico del dom. Otorga al framework web 5 segundos de espera activa de render (`WaitUntil`).

    Args:
        driver (webdriver.Chrome): Pasarela originada vigente o el cursor dinámico actual a la pantalla web.
        selector (By.*): Indicador enumerador de búsqueda en clase, o etiqueta HTML a través de By.CLASS_NAME, By.ID.
        busqueda (str): Cadena nominal explícita que corresponda al query param que persigue capturarse.

    Returns:
        bool: Existo o frascazo tras una recarga de 5 rotaciones sucesivas, para forzar salidas rápidas hacia links siguientes o de boletín.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((selector, busqueda)))
            return True
            
        except Exception as e:
            intento += 1
            print(f"Intento {intento}/{intentos_maximos}: Error:{e}. Reintentando...")

            if intento < intentos_maximos:
                print("Recargando la página...")
                driver.refresh()
                time.sleep(2)  

    print("Error: La página no se cargó después de varios intentos.")
    return False

def scrapear_dias_completos():
    """Arranque sistemático principal que gobierna la carga inter-boletín dinámicamente sobre BOIB a través de WebDrivers.

    Inicia procesos recursivos sobre el index en una franja `(boletin in range(5559, 12106))` buscando la carga dinámica del CSS. 
    Usa interceptores con Selenium headless en sub-secciones porque algunas de listadas carecen de anclas tradicionales para ser scrapeadas puro HTTP en `bs4`.
    Busca paralelamente la disponibilidad alterna entre versión de texto HTML puro renderizado incrustado o la versión binaria base inyectando finalmente
    al CSV y al pipeline final hacia compresión Zip de extensiones masivas optimizadas `.parquet` para ahorrar carga estructural.
    Activa también resguardo resiliente tolerante a cortes con el block de metadatos general index local `f"{anio_leido}.txt"`.
    """

    anio_leido = 1997
    ruta_continuar =  os.path.join(script_dir, f"{anio_leido}.txt")
    mes_leido = 1
    dia_leido = 1
    numero_boletin = 5021  #hasta 12083
    ruta_archivo_errores = os.path.join(script_dir, "url_errores")

    if not os.path.exists(ruta_continuar):
        with open(ruta_continuar, 'w', encoding='utf-8') as f:
            f.write(f"{mes_leido},{dia_leido},{numero_boletin},{anio_leido}")  #leemos el dia y el mes
            print("Escribimos el mes...")
    else:
        with open(ruta_continuar, 'r', encoding='utf-8') as f:
            mes_leido, dia_leido, numero_boletin, anio_leido = map(int, f.read().strip().split(','))
            print("Leemos el mes...")

    csv_actual = ""
    anio=1997
    for boletin in range(5559, 12106):
        base_enlace = f"https://www.caib.es/eboibfront/es/{anio}/{boletin}/"
        respuesta_enlace, encontrado_enlace = intentar_peticion(base_enlace, ruta_archivo_errores)

        if encontrado_enlace == 1 and respuesta_enlace and respuesta_enlace.status_code == 200:
            soup = ""
            try: 
                soup = BeautifulSoup(respuesta_enlace.text, 'html.parser')
                print(f"Entramos al Boletin -> {boletin}")

                menu_secciones = soup.find("ul", class_="contenidomenuLateral")
                hijos_secciones = menu_secciones.find("li", class_="primerElemento")
                enlaces = hijos_secciones.find_all('a', attrs={'rel': 'section'})

                buscando_f = soup.find("a", class_="fijo")
                numero = buscando_f.find('strong').get_text(strip=True)
                texto_fecha = buscando_f.find_all('p')[1].get_text()
                fecha_str = texto_fecha.split('-')[-1].strip()

                dia, mes_nombre, anio = [parte.strip() for parte in fecha_str.split('/')]
                base_anio = os.path.join(script_dir, f"{anio}")
                base_dir_pdfs = os.path.join(base_anio, "PDF")
                base_dir_csv = base_anio
                ruta_continuar =  os.path.join(script_dir, f"{anio}", f"{anio}.txt")

                carpetas = [base_anio, base_dir_pdfs, base_dir_csv]

                for carpeta in carpetas:    # Crear las carpetas si no existen
                    os.makedirs(carpeta, exist_ok=True)

                mes_num = meses.get(mes_nombre, '00')  
                fecha_formateada = f"{dia.zfill(2)}-{mes_num}-{anio}"


                num_seccion = 0
                for enlace_seccion in enlaces:
                    nombre_seccion = enlace_seccion.text
                    num_seccion += 1
                    enlace_ = enlace_seccion['href']
                    base_seccion = f"https://www.caib.es{enlace_}"
                    print(base_seccion)
                    driver = iniciar_driver()
                    driver.get(base_seccion)
                    num_decreto = 0

                    if verificar_carga(driver, By.CLASS_NAME, "llistat"):
                        lista_decretos = driver.find_element(By.CLASS_NAME, "llistat")
                        decretos = lista_decretos.find_elements(By.CSS_SELECTOR, "ul.entitats > li")

                        print(f"Tenemos {len(decretos)} decretos")

                        for decret in decretos:
                            try:
                                documentos = decret.find_element(By.CLASS_NAME, "documents")
                                enlace_html = None
                                try:
                                    enlaces_html = documentos.find_element(By.XPATH, ".//a[contains(text(), 'Versión HTML')]")
                                    if enlaces_html:
                                        print("Si tiene enlace a html")
                                        enlace_html = enlaces_html.get_attribute("href")
                                        print(enlace_html)
                                except:
                                    pass
                                    print("No tiene html")
                                print("Continuamos")
                                contenido_texto = ""
                                if enlace_html:
                                    print(f"Tenemos el enlace: {enlace_html}")
                                    driver_html = iniciar_driver()
                                    driver_html.get(enlace_html)
                                    contenido_texto = ""
                                    if verificar_carga(driver_html, By.ID, "contenidoEdicto"):
                                        contenido_texto = driver_html.find_element(By.ID, "contenidoEdicto").text.strip()

                                enlace_pdf = decret.find_element(By.XPATH, './/a[text()="Versión PDF"]')
                                pdf_url = enlace_pdf.get_attribute('href')
                                num_decreto += 1
                                identificador = f"BOIB-{anio}-Boletin-{boletin}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                ruta_guardar_pdf = f"{base_dir_pdfs}\{identificador}.pdf"

                                respuesta_pdf, encontrado_pdf = intentar_peticion(pdf_url, ruta_archivo_errores)
                                try:
                                    if encontrado_pdf == 1 and respuesta_pdf and respuesta_pdf.status_code == 200:
                                        descargar_pdf(respuesta_pdf, ruta_guardar_pdf)
                                        #texto_pdf_re = process_pdf(ruta_guardar_pdf)
                                        #text = contenido_texto + " " + texto_pdf_re
                                        """if texto_pdf_re != "":
                                            os.remove(ruta_guardar_pdf)
                                            print(f"PDF leído y eliminado")
                                        else:
                                            escribir_url_errores(ruta_archivo_errores, pdf_url)"""
                                except:
                                    print(f"Error al descargar el pdf: {identificador}")

                                df_re = crear_df_temporal(identificador, fecha_formateada, nombre_seccion, contenido_texto, None, None, pdf_url, ruta_guardar_pdf)
                                guardar_contenido_csv(df_re, base_dir_csv, anio)
                                csv_actual = f"{base_dir_csv}/{anio}.csv"
                                print(f"Guardamos contenido del decreto -> {identificador}")
                                time.sleep(0.5)
                            except:
                                print("No es decreto...")
                    driver.quit()
            except:
                print("Error en el boletin")

        
    # Convertir CSV a Parquet
    parquet_path = f"{base_dir_csv}/{anio}.parquet"
    try:
        if os.path.exists(csv_actual):
            df = pd.read_csv(csv_actual, encoding='utf-8')
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
                zipf.write(csv_actual, os.path.basename(csv_actual))
            print(f"✅ Archivo ZIP creado: {zip_path}")
    except Exception as e:
        print(f"❌ Error al crear el archivo ZIP para el año {anio}: {e}")

if __name__ == "__main__":
    scrapear_dias_completos()


