import os
import re
import time
import unicodedata
import requests
import polars as pl
from bs4 import BeautifulSoup
from requests.exceptions import RequestException, ChunkedEncodingError

# --- CONFIGURACIÓN GLOBAL ---
BASE_OUTPUT_PATH = "./MedlinePlus_Data"
DOCS_SUBFOLDER = os.path.join(BASE_OUTPUT_PATH, "docs")
ERROR_LOG_PATH = os.path.join(BASE_OUTPUT_PATH, "error_log.txt")
PARQUET_OUTPUT = os.path.join(BASE_OUTPUT_PATH, "medline_data.parquet")

BASE_URL = "https://medlineplus.gov/spanish/ency/"
ALPHABET = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'Ñ', 
            'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']

# --- FUNCIONES DE UTILIDAD ---

def get_directory_letter(title: str) -> str:
    """
    Normaliza el título y extrae la primera letra para organizar carpetas.
    Elimina tildes y caracteres especiales.
    """
    normalized = unicodedata.normalize('NFKD', title)
    letters = ''.join(c for c in normalized if c.isalpha())
    return letters[0].upper() if letters else "Others"

def get_safe_filename(name: str) -> str:
    """
    Limpia el nombre del archivo eliminando caracteres no permitidos en sistemas operativos.
    """
    name = name.strip().replace(' ', '_')
    return re.sub(r'[^\w\-_.]', '', name)

def log_error(url: str):
    """
    Registra las URLs que fallaron en un archivo de texto para su posterior revisión.
    """
    try:
        os.makedirs(os.path.dirname(ERROR_LOG_PATH), exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as file:
            file.write(f"{url}\n")
    except Exception as e:
        print(f"Error crítico al escribir log: {e}")

# --- NÚCLEO DEL SCRAPER ---

def fetch_url(session: requests.Session, url: str, retries: int = 5):
    """
    Realiza una petición GET con reintentos y manejo de errores de conexión.
    """
    for i in range(retries):
        try:
            response = session.get(url, timeout=15)
            if response.status_code == 200:
                return response
            elif response.status_code == 404:
                print(f"Error 404: No encontrado en {url}")
                return None
        except (RequestException, ChunkedEncodingError) as e:
            print(f"Intento {i+1} fallido para {url}: {e}")
            time.sleep(i + 1)
    
    log_error(url)
    return None

def scrape_encyclopedia():
    """
    Función principal que orquesta el raspado de la enciclopedia.
    """
    data_collection = []
    record_id = 0
    
    # Usamos una sesión para reutilizar conexiones TCP y mejorar la velocidad
    with requests.Session() as session:
        for letter in ALPHABET:
            print(f"\n--- Procesando letra: {letter} ---")
            index_url = f"{BASE_URL}encyclopedia_{letter}.htm"
            
            response = fetch_url(session, index_url)
            if not response:
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            index_list = soup.find('ul', id='index')
            
            if not index_list:
                print(f"No se encontró índice para la letra {letter}")
                continue

            links = [li.a['href'] for li in index_list.find_all('li') if li.a]
            print(f"Encontrados {len(links)} artículos.")

            for link in links:
                # Evitar saturar el servidor
                time.sleep(0.5)
                full_url = BASE_URL + link
                
                detail_res = fetch_url(session, full_url)
                if not detail_res:
                    continue

                detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                
                # Extraer Título
                title_tag = detail_soup.find('div', class_='page-title')
                if not title_tag:
                    continue
                title = title_tag.find('h1').get_text(strip=True)
                
                # Extraer Contenido
                main_div = detail_soup.find('div', class_=lambda x: x in ['main', 'main-single'])
                if main_div:
                    relevant_tags = ['h1', 'h2', 'h3', 'p', 'li']
                    extracted_text = [
                        tag.get_text(separator=' ', strip=True) 
                        for tag in main_div.find_all(relevant_tags) 
                        if tag.get_text(strip=True)
                    ]

                    # Formatear contenido para archivo de texto
                    content_str = f"{title}\n\n" + '\n'.join(extracted_text)

                    # Organizar por carpetas alfabéticas
                    folder_letter = get_directory_letter(title)
                    folder_path = os.path.join(DOCS_SUBFOLDER, folder_letter)
                    os.makedirs(folder_path, exist_ok=True)

                    # Guardar archivo .txt
                    filename = get_safe_filename(title) + ".txt"
                    file_path = os.path.join(folder_path, filename)
                    
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content_str)

                    # Guardar en memoria para el Parquet final
                    data_collection.append({
                        "id": record_id,
                        "title": title,
                        "url": full_url,
                        "content": extracted_text,
                        "letter": folder_letter
                    })
                    
                    record_id += 1
                    print(f"Guardado: {title}")
                else:
                    print(f"Contenido no encontrado para: {full_url}")

    # --- GUARDADO DE DATOS ---
    if data_collection:
        df = pl.DataFrame(data_collection)
        df.write_parquet(PARQUET_OUTPUT)
        print(f"\nProceso finalizado. Archivo Parquet generado en: {PARQUET_OUTPUT}")
    else:
        print("No se recolectaron datos.")

if __name__ == "__main__":
    # Asegurar que el directorio base existe
    os.makedirs(BASE_OUTPUT_PATH, exist_ok=True)
    scrape_encyclopedia()