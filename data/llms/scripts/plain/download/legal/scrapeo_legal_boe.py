import os
import re
import csv
import time
import gc
import sys
import random
import zipfile
import requests
import numpy as np
import torch
import pandas as pd
import polars as pl
import pdfplumber
import easyocr
import fitz  # PyMuPDF
import pytesseract
import clize
from bs4 import BeautifulSoup
from io import BytesIO
from datetime import datetime
from urllib.parse import urljoin
from requests.exceptions import ChunkedEncodingError
from pdf2image import convert_from_path
from PyPDF2 import PdfReader
from tqdm import tqdm

# --- CONFIGURACIÓN GLOBAL ---
SCRAPING_YEAR = 2000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Asegúrate de que la ruta a Tesseract sea correcta en tu entorno
pytesseract.pytesseract.tesseract_cmd = r"PATH-TO-TESSERACT"

# Diccionario para recorrer los días de cada mes
CALENDAR = {
    1: list(range(1, 32)), 2: list(range(1, 30)), 3: list(range(1, 32)),
    4: list(range(1, 31)), 5: list(range(1, 32)), 6: list(range(1, 31)),
    7: list(range(1, 32)), 8: list(range(1, 32)), 9: list(range(1, 31)),
    10: list(range(1, 32)), 11: list(range(1, 31)), 12: list(range(1, 32))
}

# --- FUNCIONES DE UTILIDAD Y LIMPIEZA ---

def clean_text(text):
    """Limpia espacios en blanco extra y normaliza el texto."""
    return " ".join(str(text).split()) 

def log_error_url(error_file, target_url):
    """Registra las URLs que fallaron en un archivo de texto para revisión posterior."""
    try:
        with open(f"{error_file}.txt", "a", encoding="utf-8") as file:
            file.write(target_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el registro de errores: {e}")

def attempt_request(url_to_search, error_path):
    """Realiza peticiones HTTP con una lógica de reintento de hasta 10 veces."""
    response_found = 0
    response = None
    try:
        response = requests.get(url_to_search, stream=True)
        # Si la respuesta es exitosa o un 404 (página no encontrada), se considera procesada
        if response and response.status_code in [200, 404]:
            response_found = 1
            return response, response_found
        else:
            found = False
            for i in range(10):
                print(f"No se pudo acceder a {url_to_search}: Reintentando...")
                time.sleep(i + 1)
                response = requests.get(url_to_search, stream=True) 
                if response and response.status_code == 200:
                    print("Conexión de reintento exitosa")
                    found = True
                    break
            if not found:
                log_error_url(error_path, url_to_search)
            response_found = 1
            return response, response_found
    except (ChunkedEncodingError, requests.exceptions.RequestException) as e:
        print(f"Error en la petición a {url_to_search}: {e}")
        log_error_url(error_path, url_to_search)
        return None, 0

# --- FUNCIONES DE MANEJO DE DATOS ---

def save_content_to_csv(df, path, year):
    """Guarda el DataFrame en un archivo CSV de forma incremental."""
    if not df.empty:
        csv_file = f"{path}/{year}.csv"
        file_exists = os.path.exists(csv_file)
        # Escribe la cabecera solo si el archivo se crea por primera vez
        df.to_csv(csv_file, mode="a", index=False, encoding='utf-8', header=not file_exists)
        print("Documento guardado en CSV")

def create_temp_df(doc_id, reference, pub_date, summary, section, subsection, group, content, pdf_content, full_text, url, pdf_route):
    """Estructura los datos extraídos en un DataFrame de Pandas y limpia el texto."""
    today = datetime.today()
    read_date = f"{today.day}-{today.month}-{today.year}"

    new_df = pd.DataFrame([{
        "id": doc_id,
        "publication_date": pub_date,
        "reference": reference,
        "summary": summary,
        "section": section,
        "subsection": subsection,
        "group": group,
        "content": content,
        "pdf_content": pdf_content,
        "text": full_text,
        "url": url,
        "read_date": read_date,
        "route_pdf": pdf_route
    }])

    # Limpieza de texto en todas las columnas
    for col in new_df.columns:
        new_df[col] = new_df[col].apply(clean_text)
    return new_df

# --- FUNCIONES DE EXTRACCIÓN DE TEXTO (PDF/OCR) ---

def extract_text_direct(pdf_path, min_chars=50):
    """Extrae texto plano usando PyMuPDF (método rápido)."""
    try:
        direct_text = ""
        gc.collect()
        doc = fitz.open(pdf_path)
        for page in doc:
            direct_text += page.get_text()
        doc.close()
        
        # Si el texto extraído es muy corto, probablemente sea una imagen y requiera OCR
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        print(f"Error en extracción directa: {e}")
        return "", False

def extract_text_ocr(pdf_path, language='spa', poppler_path=r'PATH-TO-POPPLER-BIN'):
    """Extrae texto mediante OCR usando Tesseract si la extracción directa falla."""
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=poppler_path)
        full_text = ""
        for page in tqdm(pages, desc="OCR Tesseract", leave=False):
            text = pytesseract.image_to_string(page, lang=language)
            full_text += text + "\n\n"
        return full_text
    except Exception as e:
        print(f"Error en OCR Tesseract: {e}")
        return ""

def process_pdf(pdf_file):
    """Lógica principal de procesamiento de PDF: intenta extracción directa y si no, usa OCR."""
    filename = os.path.basename(pdf_file)
    try:
        # Intento 1: Extracción directa
        text, success = extract_text_direct(pdf_file)
        
        if not success:
            # Intento 2: OCR
            print(f"Usando OCR para {filename}")
            text = extract_text_ocr(pdf_file)
    except:
        with open("error_log.txt", "a") as f:
            f.write(f"Error en {filename}: {sys.exc_info()[0]}\n")
        text = ""
    return text

def download_pdf(pdf_response, destination_path):
    """Descarga el archivo PDF binario al disco local."""
    try:
        with open(destination_path, "wb") as pdf_file:
            for chunk in pdf_response.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado: {destination_path}")
    except Exception as e:
        print(f"Error descargando el PDF: {e}")

# --- LÓGICA PRINCIPAL DE SCRAPPING ---

def scrape_full_days(*, scraping_year: int):
    """Función principal que recorre el BOE por fechas y extrae los decretos."""
    for year in range(scraping_year, scraping_year + 1):
        # Configuración de carpetas
        base_csv_dir = os.path.join(SCRIPT_DIR, f"{year}")
        base_pdf_dir = os.path.join(base_csv_dir, "pdf")
        error_log_path = os.path.join(base_csv_dir, "url_errors")
        
        for folder in [base_csv_dir, base_pdf_dir, error_log_path]:
            os.makedirs(folder, exist_ok=True)

        # Gestión del punto de continuación (Checkpoint)
        checkpoint_path = os.path.join(base_csv_dir, "continue_from.txt")
        if not os.path.exists(checkpoint_path):
            day_read, month_read, boletin_num = 24, 2, 46 # Valores por defecto del script original
            with open(checkpoint_path, 'w', encoding='utf-8') as f:
                f.write(f"{day_read}, {month_read}, {boletin_num}")
        else:
            with open(checkpoint_path, 'r', encoding='utf-8') as f:
                day_read, month_read, boletin_num = map(int, f.read().strip().split(","))

        current_boletin = boletin_num

        # Iteración por el calendario (mes y día)
        for month in sorted(CALENDAR):
            if month < month_read: continue
            for day in CALENDAR[month]:
                if month == month_read and day < day_read: continue

                day_url = f"https://www.boe.es/boe/dias/{year}/{month:02}/{day:02}/"
                response, found = attempt_request(day_url, error_log_path)

                if found and response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    current_boletin += 1
                    
                    summary_div = soup.find("div", class_="sumario")
                    if not summary_div: continue
                    
                    sibling = summary_div.find()
                    section_count = 0
                    current_section = ""
                    current_subsection = ""
                    current_group = ""

                    while sibling:
                        # Identifica la jerarquía de secciones del sumario
                        if sibling.name == 'h3':
                            current_section = sibling.text
                            section_count += 1
                            decree_count = 0
                        elif sibling.name == 'h4':
                            current_subsection = sibling.text
                        elif sibling.name == 'h5':
                            current_group = sibling.text
                        
                        # Procesa la lista de decretos bajo cada sección
                        elif sibling.name == 'ul':
                            all_li = sibling.find_all("li", class_="dispo")
                            for decree in all_li:
                                decree_count += 1
                                doc_id = f"BOE-{year}-Bulletin-{current_boletin}-Section-{section_count}-Decree-{decree_count}"
                                summary = decree.find("p").text if decree.find("p") else ""
                                
                                doc_links = decree.find("div", class_="enlacesDoc")
                                if not doc_links: continue
                                
                                # Lógica para procesar el PDF
                                pdf_link_li = doc_links.find("li", class_="puntoPDF2") or doc_links.find("li", class_="puntoPDF")
                                target_pdf_url = None
                                pdf_text_extracted = None
                                pdf_save_path = None
                                
                                if pdf_link_li and pdf_link_li.find("a"):
                                    pdf_href = pdf_link_li.find("a")['href']
                                    target_pdf_url = f"https://www.boe.es{pdf_href}"
                                    pdf_save_path = f"{base_pdf_dir}/{doc_id}.pdf"
                                    
                                    pdf_res, pdf_enc = attempt_request(target_pdf_url, error_log_path)
                                    if pdf_enc and pdf_res.status_code == 200:
                                        download_pdf(pdf_res, pdf_save_path)
                                        pdf_text_extracted = process_pdf(pdf_save_path)

                                # Lógica para procesar el HTML (Metadatos y texto web)
                                html_link_li = doc_links.find("li", class_="puntoHTML")
                                web_text = None
                                reference = None
                                if html_link_li and html_link_li.find("a"):
                                    html_url = f"https://www.boe.es{html_link_li.find('a')['href']}"
                                    html_res, html_enc = attempt_request(html_url, error_log_path)
                                    if html_enc and html_res.status_code == 200:
                                        decree_soup = BeautifulSoup(html_res.text, 'html.parser')
                                        # Extracción de Referencia
                                        meta = decree_soup.find("div", class_="metadatos")
                                        if meta:
                                            dts = meta.find_all("dt")
                                            dds = meta.find_all("dd")
                                            for dt, dd in zip(dts, dds):
                                                if "Referencia" in dt.text:
                                                    reference = dd.text.strip()
                                        # Extracción del contenido textual
                                        text_div = decree_soup.find(id="textoxslt")
                                        if text_div:
                                            paragraphs = text_div.find_all("p")
                                            if not any("Texto no disponible" in p.get_text() for p in paragraphs):
                                                web_text = " ".join(p.get_text(strip=True) for p in paragraphs)

                                # Consolidación del texto final de diversas fuentes
                                consolidated_text = ""
                                if web_text and pdf_text_extracted:
                                    consolidated_text = f"{web_text}\n{pdf_text_extracted}"
                                elif web_text:
                                    consolidated_text = web_text
                                elif pdf_text_extracted:
                                    consolidated_text = pdf_text_extracted
                                
                                # Guardado de datos en CSV
                                df = create_temp_df(
                                    doc_id, reference, f"{day}-{month}-{year}", 
                                    summary, current_section, current_subsection, 
                                    current_group, web_text, pdf_text_extracted, 
                                    consolidated_text, target_pdf_url, pdf_save_path
                                )
                                save_content_to_csv(df, base_csv_dir, year)
                                # Pausa aleatoria para evitar bloqueos del servidor
                                time.sleep(random.randint(2, 4))
                        
                        sibling = sibling.find_next_sibling()

        # --- POST-PROCESAMIENTO (Conversión a Parquet y Compresión ZIP) ---
        csv_path = f"{base_csv_dir}/{year}.csv"
        parquet_path = f"{base_csv_dir}/{year}.parquet"
        
        try:
            if os.path.exists(csv_path):
                final_df = pd.read_csv(csv_path, encoding='utf-8')
                final_df.to_parquet(parquet_path, index=False)
                print(f"✅ Convertido a Parquet: {parquet_path}")
        except Exception as e:
            print(f"❌ Error en conversión a Parquet: {e}")

        zip_path = os.path.join(SCRIPT_DIR, f"{year}.zip")
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if os.path.exists(parquet_path): zipf.write(parquet_path, os.path.basename(parquet_path))
                if os.path.exists(csv_path): zipf.write(csv_path, os.path.basename(csv_path))
            print(f"✅ Archivo ZIP creado: {zip_path}")
        except Exception as e:
            print(f"❌ Error al crear el archivo ZIP: {e}")

if __name__ == "__main__":
    clize.run(scrape_full_days)