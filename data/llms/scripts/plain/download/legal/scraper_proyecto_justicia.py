"""Descargador de PDFs del Portal de Proyectos de Transformación Digital de Justicia.

Este script usa Selenium para renderizar la página de proyectos del Ministerio de Justicia
(`mjusticia.gob.es`), extrae todos los enlaces a archivos PDF y los descarga localmente.
El nombre del archivo se deduce del encabezado `Content-Disposition` de la respuesta o de
la última parte de la URL.

Attributes:
    directorio_descarga (str): Directorio de destino para los PDFs descargados.
"""

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
import requests
import time
import re

def descargar_pdfs_selenium_fijo():
    """Descarga todos los PDFs enlazados en la página de proyectos de Transformación Digital de Justicia.

    Usa Selenium (Chrome) para renderizar la página con JavaScript, extrae los enlaces
    de todos los elementos `<a href>`, filtra los que apuntan a archivos `.pdf` y los
    descarga con `requests`. Intenta obtener el nombre del archivo desde la cabecera
    `Content-Disposition` o lo deduce del último segmento de la URL.
    """
    url_objetivo = "https://www.mjusticia.gob.es/es/servicio-justicia/proyectos-transformacion/transformacion-digital-justicia/documentos-presentaciones/proyectos"
    directorio_descarga = "pdfs_descargados_fijo"

    try:

        print(f"Directorio actual de ejecución: {os.getcwd()}")
        

        os.makedirs(directorio_descarga, exist_ok=True)
        

        if not os.path.exists(directorio_descarga):
            print(f"Error: No se pudo crear el directorio {directorio_descarga}")
        else:
            print(f"Directorio confirmado: {os.path.abspath(directorio_descarga)}")
        
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service)
        
        try:
            driver.get(url_objetivo)
            time.sleep(5)  
            html_source = driver.page_source
            soup = BeautifulSoup(html_source, 'html.parser')
            enlaces = soup.find_all('a', href=True)

            contador_descargas = 0
            for enlace in enlaces:
                href = enlace['href']
                url_absoluta = urljoin(url_objetivo, href)

                if url_absoluta.lower().endswith('.pdf'):
                    try:
                        print(f"Descargando PDF desde: {url_absoluta}")
                        response_pdf = requests.get(url_absoluta, stream=True)
                        response_pdf.raise_for_status()
                        
                        nombre_archivo = None
                        if 'Content-Disposition' in response_pdf.headers:
                            content_disposition = response_pdf.headers['Content-Disposition']
                            match = re.search(r'filename="([^"]+)"', content_disposition)
                            if match:
                                nombre_archivo = match.group(1)

                        if not nombre_archivo:
                            nombre_archivo = url_absoluta.split('/')[-1]

                        ruta_archivo = os.path.join(directorio_descarga, nombre_archivo)
                        print(f"Guardando en: {ruta_archivo}")

                        with open(ruta_archivo, 'wb') as archivo_pdf:
                            for chunk in response_pdf.iter_content(chunk_size=8192):
                                archivo_pdf.write(chunk)
                        
                        print(f"PDF guardado como: {ruta_archivo}")
                        contador_descargas += 1

                    except requests.exceptions.RequestException as e:
                        print(f"Error al descargar {url_absoluta}: {e}")
                    except Exception as e:
                        print(f"Error al guardar {url_absoluta}: {e}")

            print(f"\nSe encontraron y descargaron {contador_descargas} archivos PDF de {url_objetivo}.")
        
        finally:
            driver.quit()

    except Exception as e:
        print(f"Ocurrió un error: {e}")

if __name__ == "__main__":
    descargar_pdfs_selenium_fijo()
