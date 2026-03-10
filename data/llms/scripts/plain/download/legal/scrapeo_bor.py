"""Recolector del Boletín Oficial de La Rioja (BOR).

Este script automatiza la extracción sistemática de datos y descarga masiva de decretos del BOR.
Emplea un motor Selenium en modalidad oculta (headless) para renderizar y recorrer el histórico web
de La Rioja analizando la taxonomía HTML (secciones, subsecciones, órganos, comités) de dos paradigmas visuales web distintos divididos en pre/post 2016.
Transfiere binarios nativos de red y compila tabulaciones CSV analíticas limpiando campos decodificados.

Attributes:
    anio_scrappeo (int): Marcador inicial base temporal de iteración anual obligatoria (Ej. 1979).
    calendario (dict): Formato referencial dinámico de días sobre meses, compensado.
    todas_columnas (set): Estructura global volátil de tracking.
    script_dir (str): Directorio raíz del script donde se almacenan PDFs y CSVs.
"""

import os
from bs4 import BeautifulSoup
from httpcore import TimeoutException
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
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException

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

def iniciar_driver():
    """Genera e inicializa una instancia WebDriver Chrome silenciada libre de GUI.

    Integra directivas inyectables a los binarios Chromium locales para suprimir advertencias,
    excluir entornos sandbox del OS anfitrión y evitar bloqueos en memoria compartida asíncrona (shm).

    Returns:
        webdriver.Chrome: Driver inicializado preparado para peticiones renderizadas DOM `get`.
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
    """Estiliza los campos base decodificados borrando espacios múltiples y saltos anómalos.

    Args:
        texto (str): Cadena en formato crudo obtenida por BeautifulSoup o Selenium.

    Returns:
        str: Segmento depurado sin ruidos visuales inyectables.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Loguea enlaces defectuosos absolutos que retornan 404 o exceden los timeouts de latencia base a un `txt`.

    Args:
        archivo_errores (str): Senda donde instanciar o volcar el fallo sin extensión.
        url_dia (str): Valor textual de la URL irrecuperable con fallo.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_conexion(driver, url, ruta_errores, max_reintentos=5):
    """Fuerza al driver de Selenium a asegurar una carga exitosa del DOM web con política exhaustiva re-try.

    Maneja excepciones de conexión intermitentes WebDriver y verifica en texto la validez general 404 HTTP del contenedor in-memory.

    Args:
        driver (webdriver.Chrome): Motor a cargo de refrescar peticiones puras asimétricas.
        url (str): Endpoint primario a contactar.
        ruta_errores (str): Destino ".txt" hacia el que desviar logs de fracasos absolutos.
        max_reintentos (int, optional): Cuota límite base.

    Returns:
        str | None: Retorna el DOM renderizado base `page_source` texto si logró acierto, de lo contrario `None`.
    """
    i = 0
    while i < max_reintentos:
        try:
            driver.get(url)
            print(driver.title)
            if "Página no encontrada" in driver.page_source or "404" in driver.title:
                print(f"Página no encontrada: {url}")
                return None  # Devolver None si no se encuentra la página

            return driver.page_source  # Si carga correctamente, devolver el HTML
        except WebDriverException as e:
            print(f"Error al acceder a {url}: {e}")
            time.sleep(i + 1)  # Esperar antes de reintentar
            i += 1

    print(f"Fallaron todos los intentos de conexión: {url}")
    escribir_url_errores(ruta_errores, url)  # Guardar la URL con error
    return None

def guardar_contenido(df, ruta, anio):
    """Cuelga masivamente pandas local sobre un compendio unifilar anual en formato CSV nativo.

    Args:
        df (pd.DataFrame): Dataform extraído aislado resuelto.
        ruta (str): Directorio raíz transitorio donde convive el output log del CSV base.
        anio (int|str): Identificador nomenclativo local.
    """
    if not df.empty:
        archivo_csv = f"{ruta}/{anio}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)

def descargar_pdf(response_pdf, enlacePDF):
    """Transfiere el binario web iterándolo asíncronamente en paquetes pesados sobre un local.

    Args:
        response_pdf (requests.models.Response): Flujo Response HTTP nativo Request cargado del PDF matriz.
        enlacePDF (str): Nombramiento absoluto C:// del objeto resuelto.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_decreto, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, nombre_subsubseccion, contenido_texto, enlace_pdf, ruta_guardar_pdf):
    """Prepara tabulaciones CSV serializables sanitizando todos los bloques al vuelo en columnas.

    Args:
        enlace_decreto (str): URL resolutiva nativa local oficial en el DOM del servidor extraído a cadena.
        identificador (str): ID relativo cruzando BOR + anio + boletín.
        fecha_decreto (str): Referencial manual.
        nombre_seccion (str): Escalafón matriz mayor.
        nombre_subseccion (str): Capa secundaria orgánica.
        nombre_subsubseccion (str): Tercera iteración de sub capa orgánica para BOR pre-2016.
        contenido_texto (str): Lo empaquetado y resuelto puro natural interno html extract.
        enlace_pdf (str): Link PDF directo, en caso de captarse en el BOR.
        ruta_guardar_pdf (str): Local file path C:// correlativo absoluto local en sistema.

    Returns:
        pd.DataFrame: Tablero estructurado, limpiado y tipado final a pandas pre-volcado.
    """
    fecha_hoy = datetime.today()
    anio_actual = fecha_hoy.year
    mes_actual = fecha_hoy.month
    dia_actual = fecha_hoy.day
    fecha_lectura = f"{dia_actual}-{mes_actual}-{anio_actual}"

    nuevo_df = pd.DataFrame([{
        "Identificador": identificador,
        "Fecha_decreto": fecha_decreto,
        "Seccion": nombre_seccion,
        "Subseccion": nombre_subseccion,
        "Subsubseccion": nombre_subsubseccion,
        "Contenido": contenido_texto,
        "Url_pdf": enlace_pdf,
        "Url_decreto": enlace_decreto,
        "Fecha_lectura": fecha_lectura,
        "Ruta_pdf": ruta_guardar_pdf
    }])

    for col in nuevo_df.columns:
        nuevo_df[col] = nuevo_df[col].apply(lambda x: limpiar_texto(x)) 

    return nuevo_df

def verificar_carga_inicio(driver, selector, busqueda):
    """Verifica presencialmente un identificador clave en la homepage renderizada garantizando carga pasiva.

    Atiende una peculiaridad excluyente web del BOR si en la consulta natural "fecha" de su portal general resulta negativo ("No hay BOR").

    Args:
        driver (webdriver.Chrome): Motor web del hilo asíncrono consultivo en tiempo real en espera (`WebDriverWait`).
        selector (By.*): Mecanismo locador.
        busqueda (str): TGS a empalmar en match absoluto web.

    Returns:
        bool: Retorna True ante elemento y boletín cargado lícito, False ante alertas "no hay BOR" o limit-retry colapso.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((selector, busqueda)))
            div_ultimo_bor = driver.find_element(By.ID, "ultimo-bor")
            mensaje = None
            try:
                mensaje = div_ultimo_bor.find_element(By.TAG_NAME, "h3").text.strip()
                print(mensaje)
            except Exception:
                mensaje = None

            if "No hay ningún BOR publicado en esta fecha." in mensaje:
                print(f"No hay BOR en esta fecha, omitimos.")
                return False 
            else:
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

def verificar_carga(driver, selector, busqueda):
    """Comprobador pasivo directo del selector provisto operando exclusivamente retries de timeout de forma ciega.

    Args:
        driver (webdriver.Chrome): Motor web de Chrome asíncrono renderizador corriendo localmente.
        selector (By.*): Criterio identificador By paramétrico.
        busqueda (str): Query target locator explícito absoluto string.

    Returns:
        bool: Retorna confirmación positiva rápida al match exacto presencial sin evaluación semántica externa del div en curso.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((selector, busqueda)))
            print("Página cargada correctamente")
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

def scrapear_dias_completos(*, anio_scrappeo:int):
    """Disparador orquestador maestro que fusiona la recolección tabular al ecosistema "web.larioja.org/bor-portada" a lo largo de un año natural.

    Aborda la fragmentación estructural generacional web conmutando entre un bloque pre-2016 (jerarquías XML `romanos -> letras -> organos -> comite`)
    y una modernidad post-2016 enfocada en nodos a, PDFs explícitos vinculantes paralelos `Textos íntegros`.
    Construye internamente identificadores unívocos seriales para el rastreo e itera re-iniciando e invisibilizando browsers dinámicos masivos aislados por evento
    cerrándolos bajo demanda (`.quit()`). Recupera progresivamente desde logs fallos anteriores y mantiene memoria plana en sus txt state.

    Args:
        anio_scrappeo (int, kwarg): Marcador cronológico base de pre-asignación iterativa natural superior.
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

            for dia in dias_mes[dia_leido-1:]:   #leemos cada dia
                try: 
                    base_url = "https://web.larioja.org/bor-portada?fecha={}-{:02}-{:02}"
                    url = base_url.format(anio, mes, dia)
                    print(f"El url es: {url}")
                    driver = iniciar_driver()
                    driver.get(url)
                    busqueda = "ultimo-bor"
                    num_seccion = 0
                    num_decreto = 0
                    seccion_actual = None
                    entrado = 0

                    cambio_scrapeo = 0
                    if anio == 2016:
                        if mes == 7:
                            if dia <= 7:
                                cambio_scrapeo = 0
                            else:
                                cambio_scrapeo = 1
                        elif mes < 7:
                            cambio_scrapeo = 0
                        else:
                            cambio_scrapeo = 1
                    elif anio < 2016:
                        cambio_scrapeo = 0
                    else:
                        cambio_scrapeo = 1

                    if cambio_scrapeo == 0: #parte antigua
                        print("Anio antiguo")
                        if verificar_carga_inicio(driver, By.ID, busqueda):

                            lista = driver.find_element(By.CLASS_NAME, "list-unstyled.romanos")
                            secciones = lista.find_elements(By.XPATH, "./li")

                            for seccion in secciones:
                                nombre_seccion = seccion.find_element(By.TAG_NAME, "h3").text.strip()
                                sublista = seccion.find_element(By.CLASS_NAME, "list-unstyled.letras")
                                subsecciones = sublista.find_elements(By.XPATH, "./li")
                                print(f"Seccion: {nombre_seccion}")

                                if nombre_seccion != seccion_actual:
                                    num_seccion += 1
                                    num_decreto = 0
                                    seccion_actual = nombre_seccion
                            
                                for subsec in subsecciones:
                                    nombre_subseccion= None
                                    try:
                                        nombre_subseccion = subsec.find_element(By.CLASS_NAME, "letra").find_element(By.TAG_NAME, "h4").text
                                    except Exception:
                                        nombre_subsubseccion = None
                                    print(f"Subseccion: {nombre_subseccion}")
                                    subsublista = subsec.find_element(By.CLASS_NAME, "list-unstyled.organos")
                                    decretos = subsublista.find_elements(By.XPATH, "./li")
                                    
                                    
                                    for decreto in decretos:
                                        nombre_subsubseccion = decreto.find_element(By.CLASS_NAME, "organo").find_element(By.TAG_NAME, "h5").text
                                        print(f"Subsubseccion: {nombre_subsubseccion}")
                                        lista_dentro = decreto.find_element(By.CLASS_NAME, "list-unstyled.comite")
                                        decretos_dentro = lista_dentro.find_elements(By.XPATH, "./li")

                                        for decreto_comite in decretos_dentro:
                                            comite = decreto_comite.find_element(By.CLASS_NAME, "comite")
                                            comite_lista = comite.find_element(By.CLASS_NAME, "lista_anuncio")
                                            los_decretos = comite_lista.find_elements(By.CLASS_NAME, "anuncio_text")

                                            for comite_li in los_decretos:
                                                enlaces = comite_li.find_elements(By.TAG_NAME, "a")
                                                enlaces_decretos = {enlace.get_attribute("href") for enlace in enlaces if enlace.get_attribute("title") == "Texto Íntegro de la Disposición"}  

                                                for i in enlaces_decretos:
                                                    driver_decretos = iniciar_driver()
                                                    num_decreto += 1
                                                    fecha_decreto = f"{dia}-{mes}-{anio}"
                                                    identificador = f"BOR-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Decreto-{num_decreto}"
                                                    driver_decretos.get(i)

                                                    if verificar_carga(driver_decretos, By.CLASS_NAME, "anuncio_texto"):
                                                        contenido_texto = driver_decretos.find_elements(By.CLASS_NAME, "anuncio_texto")
        
                                                        texto_completo = ""
                                                        for elemento in contenido_texto:
                                                            parrafos = elemento.find_elements(By.TAG_NAME, "p")  
                                                            texto_completo = "\n".join([p.text.strip() for p in parrafos])
                                                        
                                                        df = crear_df_temporal(i, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, nombre_subsubseccion, texto_completo, None, None)
                                                        guardar_contenido(df, base_dir_csv, anio)
                                                        print(f"Guardamos en el csv: {identificador}")
                                                        entrado = 1
                                                        driver_decretos.quit()
                                                        time.sleep(0.5)

                        else:
                            escribir_url_errores(ruta_archivo_errores, url)
                    else: #parte nueva
                        print("Anio nuevo")
                        if verificar_carga_inicio(driver, By.ID, busqueda):
                            lista = driver.find_element(By.CLASS_NAME, "list-unstyled.romanos")
                            secciones = lista.find_elements(By.XPATH, "./li")

                            for seccion in secciones:
                                nombre_seccion = seccion.find_element(By.TAG_NAME, "h3").text.strip()
                                sublista = seccion.find_element(By.CLASS_NAME, "list-unstyled.letras")
                                subsecciones = sublista.find_elements(By.XPATH, "./li")
                                print(f"Seccion: {nombre_seccion}")

                                if nombre_seccion != seccion_actual:
                                    num_seccion += 1
                                    num_decreto = 0
                                    seccion_actual = nombre_seccion
                            
                                for subsec in subsecciones:
                                    nombre_subseccion= None
                                    try:
                                        nombre_subseccion = subsec.find_element(By.CLASS_NAME, "letra").find_element(By.TAG_NAME, "h4").text
                                    except Exception:
                                        nombre_subsubseccion = None
                                    print(f"Subseccion: {nombre_subseccion}")
                                    subsublista = subsec.find_element(By.CLASS_NAME, "list-unstyled.organos")
                                    decretos = subsublista.find_elements(By.XPATH, "./li")
                                    
                                    for decreto in decretos:
                                        nombre_subsubseccion = decreto.find_element(By.CLASS_NAME, "organo").find_element(By.TAG_NAME, "h5").text
                                        print(f"Subsubseccion: {nombre_subsubseccion}")
                                        lista_dentro = decreto.find_element(By.CLASS_NAME, "list-unstyled.comite")
                                        decretos_dentro = lista_dentro.find_elements(By.XPATH, "./li")

                                        for decreto_comite in decretos_dentro:
                                            comite = decreto_comite.find_element(By.CLASS_NAME, "comite")
                                            comite_lista = comite.find_element(By.CLASS_NAME, "lista_anuncio")
                                            los_decretos = comite_lista.find_elements(By.CLASS_NAME, "anuncio_text")

                                            for comite_li in los_decretos:
                                                enlaces = comite_li.find_elements(By.TAG_NAME, "a")
                                                enlaces_pdfs = {enlace.get_attribute("href") for enlace in enlaces if enlace.get_attribute("title") == "Texto Íntegro de la Disposición"}  
                                                enlaces_decretos = {enlace.get_attribute("href") for enlace in enlaces if "html" in enlace.text.lower()}
                                                num_decreto_inicial = num_decreto

                                                for i in enlaces_pdfs:
                                                    num_decreto_inicial += 1
                                                    fecha_decreto = f"{dia}-{mes}-{anio}"
                                                    identificador = f"BOR-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Decreto-{num_decreto_inicial}"
                                                    enlace_pdf = f"{base_dir_pdfs}/{identificador}.pdf"

                                                    intento = 0
                                                    conseguido = False
                                                    while intento < 5 and not conseguido:
                                                        response = requests.get(i, stream=True)
                                                        if response.status_code == 200:
                                                            conseguido = True
                                                            descargar_pdf(response,enlace_pdf)
                                                        else:
                                                            time.sleep(1)
                                                            print("Reintentamos descargar el pdf")

                                                for j in enlaces_decretos:
                                                    driver_decretos = iniciar_driver()
                                                    num_decreto += 1
                                                    driver_decretos.get(j)
                                                    if verificar_carga(driver_decretos, By.CLASS_NAME, "anuncio_texto"):
                                                        contenido_texto = driver_decretos.find_elements(By.CLASS_NAME, "anuncio_texto")
        
                                                        texto_completo = ""
                                                        for elemento in contenido_texto:
                                                            parrafos = elemento.find_elements(By.TAG_NAME, "p")  
                                                            texto_completo = "\n".join([p.text.strip() for p in parrafos])
                                                        
                                                        df = crear_df_temporal(i, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, nombre_subsubseccion, texto_completo, None, None)
                                                        guardar_contenido(df, base_dir_csv, anio)
                                                        print(f"Guardamos en el csv: {identificador}")
                                                        entrado = 1
                                                        driver_decretos.quit()
                                                        time.sleep(0.5)

                        else:
                            escribir_url_errores(ruta_archivo_errores, url)
                    if entrado == 1:
                        numero_boletin += 1
                    driver.quit()

                except Exception as e:
                    print(f"Error inesperado: {str(e)}")
                    with open(ruta_archivo_errores, "a", encoding="utf-8") as f:
                        f.write(f"Error en {url}: {str(e)}\n")
                    driver.refresh()

                except ChunkedEncodingError as e:
                    print(f"Error en la transferencia de datos: {e}")
                    continue
            
                except requests.exceptions.RequestException as e:
                    print(f"Intento rechazado")
                    continue
        dia_leido = 1

if __name__ == "__main__":
    clize.run(scrapear_dias_completos)

