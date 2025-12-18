from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import os
from urllib.parse import urljoin
import requests
import time
import re


def descargar_pdfs_selenium(target_url, output_dir="data/pdfs", timeout=5, headless=True):
    """
    Download all PDF files from a given URL using Selenium and BeautifulSoup.
    
    Parameters:
    - target_url: URL of the page to scrape for PDF links
    - output_dir: Directory where PDFs will be saved
    - timeout: Seconds to wait for page to load
    - headless: Whether to run Chrome in headless mode
    
    Returns:
    - int: Number of PDFs successfully downloaded
    """
    try:
        print(f"Directorio actual de ejecución: {os.getcwd()}")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        if not os.path.exists(output_dir):
            print(f"Error: No se pudo crear el directorio {output_dir}")
            return 0
        
        print(f"Directorio confirmado: {os.path.abspath(output_dir)}")
        
        # Setup Chrome options
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Initialize Chrome driver
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        try:
            print(f"Accediendo a: {target_url}")
            driver.get(target_url)
            time.sleep(timeout)
            
            # Parse page content
            html_source = driver.page_source
            soup = BeautifulSoup(html_source, 'html.parser')
            enlaces = soup.find_all('a', href=True)
            
            contador_descargas = 0
            enlaces_procesados = set()  # To avoid duplicates
            
            for enlace in enlaces:
                href = enlace['href']
                url_absoluta = urljoin(target_url, href)
                
                # Skip if already processed (avoid duplicates)
                if url_absoluta in enlaces_procesados:
                    continue
                
                # Check if link is a PDF
                if url_absoluta.lower().endswith('.pdf'):
                    enlaces_procesados.add(url_absoluta)
                    
                    try:
                        print(f"Descargando PDF desde: {url_absoluta}")
                        response_pdf = requests.get(url_absoluta, stream=True, timeout=30)
                        response_pdf.raise_for_status()
                        
                        # Try to get filename from Content-Disposition header
                        nombre_archivo = None
                        if 'Content-Disposition' in response_pdf.headers:
                            content_disposition = response_pdf.headers['Content-Disposition']
                            match = re.search(r'filename="([^"]+)"', content_disposition)
                            if match:
                                nombre_archivo = match.group(1)
                        
                        # Fallback to URL basename if no filename in headers
                        if not nombre_archivo:
                            nombre_archivo = url_absoluta.split('/')[-1]
                            # Clean filename if it has query parameters
                            if '?' in nombre_archivo:
                                nombre_archivo = nombre_archivo.split('?')[0]
                        
                        # Sanitize filename
                        nombre_archivo = re.sub(r'[<>:"/\\|?*]', '_', nombre_archivo)
                        
                        ruta_archivo = os.path.join(output_dir, nombre_archivo)
                        
                        # Skip if file already exists
                        if os.path.exists(ruta_archivo):
                            print(f"El archivo ya existe: {ruta_archivo} - Saltando...")
                            continue
                        
                        print(f"Guardando en: {ruta_archivo}")
                        
                        # Save PDF
                        with open(ruta_archivo, 'wb') as archivo_pdf:
                            for chunk in response_pdf.iter_content(chunk_size=8192):
                                archivo_pdf.write(chunk)
                        
                        print(f"PDF guardado como: {ruta_archivo}")
                        contador_descargas += 1
                    
                    except requests.exceptions.RequestException as e:
                        print(f"Error al descargar {url_absoluta}: {e}")
                    except Exception as e:
                        print(f"Error al guardar {url_absoluta}: {e}")
            
            print(f"\nSe descargaron {contador_descargas} archivos PDF de {target_url}.")
            return contador_descargas
        
        finally:
            driver.quit()
    
    except Exception as e:
        print(f"Ocurrió un error: {e}")
        return 0


def descargar_pdfs_multi_paginas(urls, output_dir="data/pdfs", timeout=5, headless=True):
    """
    Download PDFs from multiple URLs.
    
    Parameters:
    - urls: List of URLs to scrape
    - output_dir: Directory where PDFs will be saved
    - timeout: Seconds to wait for each page to load
    - headless: Whether to run Chrome in headless mode
    
    Returns:
    - dict: Dictionary with URL as key and download count as value
    """
    resultados = {}
    
    for url in urls:
        print(f"\n{'='*60}")
        print(f"Procesando URL: {url}")
        print(f"{'='*60}\n")
        
        # Create subdirectory for each URL (optional)
        # url_dir = os.path.join(output_dir, re.sub(r'[<>:"/\\|?*]', '_', url.split('//')[-1][:50]))
        
        count = descargar_pdfs_selenium(url, output_dir, timeout, headless)
        resultados[url] = count
        
        # Pause between URLs to avoid rate limiting
        if len(urls) > 1:
            time.sleep(2)
    
    # Summary
    print(f"\n{'='*60}")
    print("RESUMEN DE DESCARGAS")
    print(f"{'='*60}")
    total = 0
    for url, count in resultados.items():
        print(f"{url}: {count} PDFs")
        total += count
    print(f"\nTotal descargado: {total} PDFs")
    
    return resultados


if __name__ == "__main__":
    # Example 1: Single URL
    url_sanidad = "https://www.sanidad.gob.es/biblioPublic/publicaciones/recursos_propios/infMedic/porVolumen/home.htm"
    
    descargar_pdfs_selenium(
        target_url=url_sanidad,
        output_dir="data/pdfs/sanidad",
        timeout=5,
        headless=True
    )
    
    # Example 2: Multiple URLs
    """
    urls_a_procesar = [
        "https://www.example1.com/documents",
        "https://www.example2.com/resources",
    ]
    
    descargar_pdfs_multi_paginas(
        urls=urls_a_procesar,
        output_dir="data/pdfs",
        timeout=5,
        headless=True
    )
    """
