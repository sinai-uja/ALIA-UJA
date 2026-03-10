"""Recolector del Diario Oficial de Castilla-La Mancha (DOCM).

Este script automatiza la extracción sistemática de resoluciones del DOCM.
Posee manejo de dualidad estacional (anterior vs posterior a 2008), realizando peticiones
nativas HTTP simulando user-agents de navegador comercial, así como el uso de Selenium headless
para parsear tablas detalladas en disposiciones modernas y capturar incrustaciones iframe (vistas antiguas PDF).
Genera tabulaciones analíticas a CSV combinadas con acopio binario PDF concurrente.

Attributes:
    anio_scrappeo (int): Marcador inicial base temporal de arranque unificado.
    script_dir (str): Directorio raíz local C:// referenciando despliegue y depósito archivos temporales.
    headers (dict): Parámetros spoofing Request persistentes contra bloqueos 403 `User-Agent`.
    calendario (dict): Formato referencial dinámico dict de iterador de calendario natural.
"""

import os
from bs4 import BeautifulSoup
import requests
from datasets import Dataset
from selenium import webdriver
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
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException

anio_scrappeo = 2000
script_dir = os.path.dirname(os.path.abspath(__file__))
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Referer': 'https://docm.jccm.es/docm/'
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

def iniciar_driver():
    """Genera e inicializa una instancia WebDriver Chrome silenciada libre de Interfaz Gráfica (GUI).

    Adhiere en sus setup options las evasiones para sandbox, omisión de aceleración por HW (GPU) e inhibición de loggins base Chrome
    logrando estabilizar las ejecuciones repetitivas anuales sub-enrutadas localmente.

    Returns:
        webdriver.Chrome: Driver listo para navegación automatizada de iframes web, resoluciones post-2008 y PDFs antiguos DOCM.
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
    """Estiliza los campos base decodificados borrando espacios múltiples vacíos laterales.

    Args:
        texto (str): Segmento extraído crudo de html soup o selenium elements.

    Returns:
        str: Segmento depurado sin ruidos de sangría.
    """
    return " ".join(str(texto).split()) 

def escribir_url_errores(archivo_errores, url_dia):
    """Mecanismo de contención log para caídas irrecuperables a disco con persistencia plana externa local (`.txt`).

    Args:
        archivo_errores (str): Senda donde instanciar o engrosar las fallas HTTP. Note: omitir sufijo string del archivo `.txt`.
        url_dia (str): Valor puro HTTP de URL inyectable.
    """
    try:
        with open(f"{archivo_errores}.txt", "a", encoding="utf-8") as file:
            file.write(url_dia + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def intentar_peticion(url_buscar, ruta_errores):
    """Estabilizador iterativo en bucle for (max. 5) basado en requests python `stream` que interrumpe o sella bloqueos del host (DOCM).

    Enmascara peticiones HTTP(s) inyectando `User-Agent` de Firefox Win64 actualizado junto a `Referer`.

    Args:
        url_buscar (str): Endpoint primario a consumir iterativamente.
        ruta_errores (str): Destino ".txt" file object fallback base.

    Returns:
        tuple[requests.models.Response | None, int]: Dupla del Stream vivo local y bandera paramétrica de éxito nominal base.
    """

    headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Referer': url_buscar
    }  
    i = 0 
    encontrada_respuesta = 0
    respuesta = None
    try:
        respuesta = requests.get(url_buscar, headers=headers ,stream=True)
        print(respuesta)
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
                respuesta = requests.get(url_buscar, headers=headers, stream=True) 
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
    """Engrosa el compilado DataFrame final CSV base con los registros atómicos transitorios.

    Args:
        df (pd.DataFrame): Filas y Columnas locales empaquetadas purgadas temporales.
        base_dir_csv (str): Path al almacén local maestro CSV.
        anio_scrappeo (int|str): Serial nomenclador del volumen depositario (Ej. `2015.csv`).
    """
    if not df.empty:
        archivo_csv = f"{base_dir_csv}/{anio_scrappeo}.csv"
        archivo_existe = os.path.exists(archivo_csv)
        df.to_csv(archivo_csv, mode="a", index=False, encoding='utf-8', header=not archivo_existe)
        print("Guardamos en el csv...")

def descargar_pdf(response_pdf, enlacePDF):
    """Desdobla el caudal de streaming Request encapsulado por `intentar_peticion` reensamblador a ficheros file-system.

    Args:
        response_pdf (requests.models.Response): Bloque HTTP(s) stream validado 200 directo inyectable iterator.
        enlacePDF (str): Nombramiento y dir local absoluto depositero final.
    """
    try:
        with open(enlacePDF, "wb") as pdf_file:
            for chunk in response_pdf.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado decreto: {enlacePDF}")

    except Exception as e:
        print(f"Error descargando el PDF: {e}")

def crear_df_temporal(enlace_detalle, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, contenido_text, enlace_pdf, ruta_guardar_pdf):
    """Sella y compacta valores sueltos nativos en un Dataframe `pandas` monolítico transitorio a base de diccionarios.

    Args:
        enlace_detalle (str): Construcción url pura origen sub-frame actual visitado (`Url_html`).
        identificador (str): Etiqueta combinada absoluta (DOCM-anio-M-D...).
        fecha_decreto (str): Referencia natural estática formateada (dia-mes-(anio)).
        nombre_seccion (str): Rama clasificador purgado macro titular.
        nombre_subseccion (str): `organismo` promotor u origen.
        contenido_text (str): Lo empaquetado y extraído del table html unitario `tablaDetalle`.
        enlace_pdf (str): Link persistente externo extraído en página que redirige al binario nativo oficial DOCM.
        ruta_guardar_pdf (str): Extrapolación C:// matriz file al CSV final.

    Returns:
        pd.DataFrame: Tabulación única sanitizada (`limpiar_texto` x key) lista para volcarse por index/mode=`a`.
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

def verificar_carga(driver, selector, busqueda):
    """Verifica presencia del marco DOM interior explícito en documentos post-2008 de detalles DOCM.

    Args:
        driver (webdriver.Chrome): Ejecutor activo operando la red e instanciado pasivamente.
        selector (By.*): Mapeador de tipo de búsqueda DOM (CLASS_NAME o similar).
        busqueda (str): Cadena query identificativa del contenedor `tablaDetalle`.

    Returns:
        bool: Exito de visibilidad o False tas 5 agudos reintentos totales.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((selector, busqueda)))
            tabla = driver.find_element(By.CLASS_NAME, "tablaDetalle")
            if tabla:
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

def verificar_carga_pdf(driver, selector, busqueda):
    """Validador específico para visuales históricas (pre-2008) donde Castila La-Mancha embebía iFrames.

    Args:
        driver (webdriver.Chrome): Motor web corriendo.
        selector (By.*): Argumento evaluador enumerador asíncrono.
        busqueda (str): Target de iframe contenedor `columnaIframe`.

    Returns:
        bool: True confirmando latencias y cargas visuales de UI antigua resolutor pdf embed nativo Web o iteracion refrescos fallback agotada.
    """
    intentos_maximos = 5  
    intento = 0
    while intento < intentos_maximos:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((selector, busqueda)))
            tabla = driver.find_element(By.CLASS_NAME, "columnaIframe")
            if tabla:
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
    """Dispositivo central conmutador dual sobre el histórico del Diario C-LM (DOCM).

    Inicia mapeos cronológicos calendario web y ejecuta condicionales divisorios `anio > 2008`.
    - **(Contemporánea post-2008)**: Rastrea portlets DOCM via Requests / BS4 extrayendo subsecciones div-organismo a, 
      descarga documentos pdf estáticos y propaga threads micro-Chrome drivers a leer tablas `html` de visualización detallada (`tablaDetalle`).
    - **(Generacional pre-2008)**: Fuerza motores `Selenium` hacia endpoints de volúmenes puramente PDF embebidos localizando atributos source iframe `framePDF`.
    Escribe tracking TXT unificados continuables para paliar saturaciones IP. Emite CSV iterativos y descargas volumétricas pesadas a disco.

    Args:
        anio_scrappeo (int, kwarg): Marcador cronológico base padrón referencial inyectable general.
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
                    if anio > 2008:
                        base_enlaces = f"https://docm.jccm.es/docm/cambiarBoletin.do?fecha={anio}{mes:02}{dia:02}"
                        base_sumarios = "https://docm.jccm.es/docm"
                    
                        respuesta, encontrado = intentar_peticion(base_enlaces, ruta_archivo_errores)
                        if encontrado == 1 and respuesta and respuesta.status_code == 200:
                            tiene_decretos = False
                            print(f"Entramos a la página del día: {dia}-{mes}-{anio}")
                        
                            #Tomamos las seccions y subsecciones
                            soup = BeautifulSoup(respuesta.text, 'html.parser')

                            num_seccion = 0
                            secciones = soup.find_all("div", class_="categoriaDiario")
                            for seccion in secciones:
                                num_seccion += 1
                                nombre_seccion = seccion.find('h3').get_text(strip=True)
                                nombre_subseccion = None
                                disposicion = seccion.find("div", class_="disposicion")
                                nombre_subseccion_ = disposicion.find("div", class_="organismo")
                                nombre_subseccion = nombre_subseccion_.get_text(strip = True)
                                num_decreto = 0

                                siguiente_etiqueta = nombre_subseccion_.find_next_sibling()

                                while siguiente_etiqueta:
                                    if siguiente_etiqueta.name == "div":
                                        if 'organismo' in siguiente_etiqueta.get('class', []):
                                            print("Cogemos el organismo")
                                            nombre_subseccion = siguiente_etiqueta.get_text(strip=True)
                                            siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()

                                        else:
                                            print("Pasamos a coger los enlaces")
                                            num_decreto += 1
                                            identificador = f"DOCM-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                                            enlace_detalle_elem = siguiente_etiqueta.find("a", title="Ver los datos detallados del documento")
                                            enlace_pdf_elem = siguiente_etiqueta.find("a", class_="new-window")

                                            enlace_detalle = enlace_detalle_elem["href"] if enlace_detalle_elem else None
                                            enlace_pdf = enlace_pdf_elem["href"] if enlace_pdf_elem else None

                                            ruta_guardar_pdf = None

                                            if enlace_detalle and enlace_detalle.startswith("."):
                                                enlace_detalle = enlace_detalle[1:]

                                            if enlace_pdf and enlace_pdf.startswith("."):
                                                enlace_pdf = enlace_pdf[1:]

                                            enlace_pdf = f"{base_sumarios}{enlace_pdf}"

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
                                            enlace_det = f"{base_sumarios}{enlace_detalle}"
                                            driver_decretos = iniciar_driver()
                                            driver_decretos.get(enlace_det)
                                            if verificar_carga(driver_decretos, By.ID, "contenido"):
                                                print("Estamos dentro de la página...")
                                                try:
                                                    tabla = driver_decretos.find_element(By.CLASS_NAME, "tablaDetalle")
                                                    filas = tabla.find_elements(By.TAG_NAME, "tr")
                                                except Exception as e:
                                                    print(f"Error al obtener la tabla: {e}")

                                                texto_tabla = []
                                                for fila in filas:
                                                    celdas = fila.find_elements(By.TAG_NAME, "td")
                                                    celdas_texto = [celda.text for celda in celdas]  
                                                    texto_tabla.append(celdas_texto)
                                                        
                                                df = crear_df_temporal(enlace_det, identificador, fecha_decreto, nombre_seccion, nombre_subseccion, texto_tabla, None, None)
                                                Guardar_Contenido(df, base_dir_csv, anio)
                                                print(f"Guardamos en el csv: {identificador}")
                                                driver_decretos.quit()
                                                time.sleep(0.5)

                                            siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()
                                    else:
                                        siguiente_etiqueta = siguiente_etiqueta.find_next_sibling()

                                    if tiene_decretos:
                                        numero_boletin += 1

                        elif encontrado == 1 and respuesta.status_code == 404:
                            print(f"No existe a partir del dia: {dia}")
                            break


                        with open(ruta_continuar, 'w', encoding='utf-8') as f:
                                print(f"Guardamos el fichero en el boletin: {mes}-{dia}-{numero_boletin - 1}")
                                f.write(f"{mes}, {dia}, {numero_boletin - 1}")
                    else:
                        num_decreto = 1
                        num_seccion = 1
                        identificador = f"DOCM-{anio}-Boletin-{numero_boletin}-Seccion-{num_seccion}-Dec-{num_decreto}"
                        base_enlace_pdf = f"https://docm.jccm.es/docm/verDiarioAntiguo.do?ruta={anio}/{mes:02}/{dia:02}"
                        ruta_guardar_pdf = os.path.join(base_dir_pdfs,f"{identificador}")
                        ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"
                        driver_decretos = iniciar_driver()
                        driver_decretos.get(base_enlace_pdf)
                        print(f"Accedemos a: {base_enlace_pdf}")

                        if verificar_carga_pdf(driver_decretos, By.CLASS_NAME, "columnaIframe"):
                            iframe = driver_decretos.find_element(By.NAME, "framePDF").get_attribute("src")

                            if iframe:
                                ruta_guardar_pdf = os.path.join(base_dir_pdfs,f"{identificador}")
                                ruta_guardar_pdf = f"{ruta_guardar_pdf}.pdf"
                                response_pdf, encontrado_pdf = intentar_peticion(iframe, ruta_archivo_errores)

                                if encontrado_pdf == 1 and response_pdf and response_pdf.status_code == 200:
                                    if os.path.exists(ruta_guardar_pdf):
                                        print("El pdf ya esta descargado.")
                                    else:
                                        descargar_pdf(response_pdf, ruta_guardar_pdf)

                                numero_boletin += 1

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


