"""Scraper de la revista médica "Información Terapéutica" (Ministerio de Sanidad).

Este módulo utiliza Selenium Webdriver y BeautifulSoup para extraer y descargar
los volúmenes de la publicación "Información Terapéutica del Sistema Nacional de Salud".
Recorre la página y descarga automáticamente los PDFs subyacentes en una
ruta definida.

Example:
    Ejecución básica::

        python Scraper_info_terapeutica.py

    Descargará los PDFs detectados de la URL de Información Terapéutica.

Note:
    Dependencia crítica de Chrome y Selenium WebDriver manager para funcionar.
    Puede requerir tiempo de carga explícito (`time.sleep`) en páginas estáticas.
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

def descargar_pdfs_selenium_fijo() -> None:
    """Busca y descarga las publicaciones en PDF presentes en la web objetivo.

    Inicializa un driver de Selenium Chrome oculto o visible y realiza peticiones HTTP
    en busca de enlaces `.pdf`. Guarda cada archivo gestionando de ser posible su 
    nombre de `Content-Disposition`.
    
    Creates:
        La estructura de carpetas `pdfs_descargados_fijo` si no existe previamente.

    Raises:
        requests.exceptions.RequestException: Captura y muestra errores de descarga del PDF.
        Exception: Atrapa problemas generales del entorno como fallos de ejecución de Selenium.
    """
    url_objetivo = "https://www.sanidad.gob.es/biblioPublic/publicaciones/recursos_propios/infMedic/porVolumen/home.htm"
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
            #Sale que ha encontrado y descargado 1 mas de los que realmente descarga porque hay un enlace duplicado
        finally:
            driver.quit()

    except Exception as e:
        print(f"Ocurrió un error: {e}")

if __name__ == "__main__":
    descargar_pdfs_selenium_fijo()
