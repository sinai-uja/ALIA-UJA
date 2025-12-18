import os
import time
import re
import requests
import fitz  # PyMuPDF
import polars as pl
from bs4 import BeautifulSoup
from requests.exceptions import ChunkedEncodingError, RequestException

# ==========================================
# CONFIGURACIÓN GLOBAL (Rutas y Parámetros)
# ==========================================
BASE_DIR = "./GuiaSalud"
DOCS_OUTPUT_DIR = os.path.join(BASE_DIR, "docs")
ERROR_LOG_PATH = os.path.join(BASE_DIR, "errors.txt")
MISSING_LOG_PATH = os.path.join(BASE_DIR, "missing.txt")
PARQUET_OUTPUT = os.path.join(BASE_DIR, "output.parquet")

START_URL = "https://portal.guiasalud.es/gpc/?_sfm_wpcf-estado=1"

# Headers para parecer un navegador real
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
}

# ==========================================
# FUNCIONES DE UTILIDAD
# ==========================================

def log_error(url, file_path=ERROR_LOG_PATH):
    """Registra las URLs que fallaron en un archivo de texto."""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{url}\n")
    except Exception as e:
        print(f"Error escribiendo en log: {e}")

def extract_pdf_text(pdf_path):
    """Extrae todo el texto de un archivo PDF usando PyMuPDF."""
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
        return full_text
    except Exception as e:
        print(f"Error procesando PDF {pdf_path}: {e}")
        return ""

def fetch_url(url, retries=5):
    """Intenta realizar una petición GET con reintentos y manejo de errores."""
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=HEADERS, stream=True, timeout=30)
            if response.status_code == 200:
                return response
            elif response.status_code == 404:
                print(f"Página no encontrada (404): {url}")
                return response
            
            # Si hay otro código de error, esperamos y reintentamos
            print(f"Error {response.status_code} en {url}. Reintento {attempt + 1}...")
            time.sleep(attempt + 1)
            
        except (ChunkedEncodingError, RequestException) as e:
            print(f"Fallo de conexión en {url}: {e}")
            time.sleep(attempt + 1)
            
    log_error(url)
    return None

# ==========================================
# LÓGICA PRINCIPAL DE SCRAPPING
# ==========================================

def scrape_guiasalud():
    """Función principal que orquestra el scraping."""
    
    # Crear directorios si no existen
    os.makedirs(DOCS_OUTPUT_DIR, exist_ok=True)

    data_collection = []
    
    print(f"Iniciando acceso a: {START_URL}")
    response = fetch_url(START_URL)

    if not response or response.status_code != 200:
        print("No se pudo acceder a la página principal.")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Localizar el contenedor principal de los resultados
    container = soup.find('div', class_='js-wpv-view-layout')
    if not container:
        print("No se encontró el contenedor de resultados.")
        return

    # Extraer cada ficha de guía
    guides = container.find_all('div', id='main')
    print(f"Se han encontrado {len(guides)} guías.")

    for guide in guides:
        try:
            # 1. Extraer Metadatos Básicos
            title_tag = guide.find('a')
            title = title_tag.get_text(strip=True) if title_tag else "Sin título"
            
            content_div = guide.find('div', class_='contenido-ficha')
            if not content_div:
                continue

            # Extraer ID (buscando el texto 'ID:')
            id_tag = content_div.find(string=lambda t: 'ID:' in t)
            guide_id = id_tag.next_element.strip() if id_tag else "unknown"

            # Entidad elaboradora
            entity_tag = content_div.find('a')
            entity_name = entity_tag.get_text(strip=True) if entity_tag else None

            # Fecha de edición
            date_tag = content_div.find(string=lambda t: 'Fecha de edición:' in t)
            edit_date = date_tag.next_element.strip() if date_tag else None

            # Objetivos
            desc_div = content_div.find('div', class_='descripcion')
            objectives = ' '.join(p.get_text(strip=True) for p in desc_div.find_all('p')) if desc_div else None

            # 2. Buscar enlace al PDF Completo
            pdf_url = None
            link_divs = guide.find_all('div', class_='enlace')
            for div in link_divs:
                text_div = div.find('div', class_='texto-descarga')
                if text_div and "Completa PDF" in text_div.get_text():
                    a_tag = div.find('a', href=True)
                    if a_tag:
                        pdf_url = a_tag['href']
                        break

            if not pdf_url:
                print(f"Guía {guide_id} no tiene PDF completo. Saltando...")
                continue

            # 3. Descargar y procesar el PDF
            print(f"Procesando Guía [{guide_id}]: {title}")
            pdf_res = fetch_url(pdf_url)
            
            if pdf_res and pdf_res.status_code == 200:
                pdf_filename = f"{guide_id}.pdf"
                save_path = os.path.join(DOCS_OUTPUT_DIR, pdf_filename)

                # Guardar el archivo en disco
                with open(save_path, "wb") as f:
                    f.write(pdf_res.content)
                
                # Extraer texto del PDF recién guardado
                extracted_text = extract_pdf_text(save_path)

                # Añadir al diccionario de datos
                data_collection.append({
                    "id": guide_id,
                    "title": title,
                    "entity": entity_name,
                    "date": edit_date,
                    "objectives": objectives,
                    "url": pdf_url,
                    "text": extracted_text
                })
            else:
                log_error(pdf_url, MISSING_LOG_PATH)

        except Exception as e:
            print(f"Error procesando una ficha: {e}")
            continue

    # 4. Guardar resultados en Parquet
    if data_collection:
        try:
            df = pl.DataFrame(data_collection)
            df.write_parquet(PARQUET_OUTPUT)
            print(f"\nProceso finalizado. Archivo guardado en: {PARQUET_OUTPUT}")
            print(f"Total registros: {len(data_collection)}")
        except Exception as e:
            print(f"Error al guardar el archivo Parquet: {e}")
    else:
        print("No se recolectaron datos para guardar.")

if __name__ == "__main__":
    main_start_time = time.time()
    scrape_guiasalud()
    print(f"Tiempo total: {round(time.time() - main_start_time, 2)} segundos.")