import os
import re
import csv
import time
import gc
import sys
import requests
import zipfile
import pandas as pd
import polars as pl
import fitz  # PyMuPDF
import pytesseract
import clize
from bs4 import BeautifulSoup
from datetime import datetime
from requests.exceptions import ChunkedEncodingError
from pdf2image import convert_from_path
from tqdm import tqdm

# --- CONFIGURACIÓN GLOBAL ---
# Configuración de la ruta de Tesseract (Ajustar según tu instalación)
pytesseract.pytesseract.tesseract_cmd = r"PATH-TO-TESSERACT"
SCRAPING_YEAR = 1979
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- FUNCIONES DE UTILIDAD Y LIMPIEZA ---

def clean_text(text):
    """Elimina saltos de línea y espacios múltiples para normalizar el texto."""
    return " ".join(str(text).split()) 

def log_error_url(error_file_path, failed_url):
    """Registra las URLs que no pudieron procesarse en un archivo de texto."""
    try:
        with open(f"{error_file_path}.txt", "a", encoding="utf-8") as file:
            file.write(failed_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el registro de errores: {e}")

def attempt_request(target_url, error_log_path):
    """Realiza peticiones HTTP con lógica de reintento automático (hasta 5 veces)."""
    response_found = 0
    response = None
    try:
        response = requests.get(target_url, stream=True)
        if response and response.status_code in [200, 404]:
            response_found = 1
            return response, response_found
        else:
            success = False
            for i in range(5):
                print(f"No se pudo acceder a {target_url}: reintentando ({i+1}/5)")
                time.sleep(i + 1)
                response = requests.get(target_url) 
                if response and response.status_code == 200:
                    print("Conexión de reintento exitosa")
                    success = True
                    break
            if not success:
                log_error_url(error_log_path, target_url)
            response_found = 1
            return response, response_found
        
    except (ChunkedEncodingError, requests.exceptions.RequestException) as e:
        print(f"Error de red al acceder a {target_url}: {e}")
        log_error_url(error_log_path, target_url)
        return None, 0

# --- FUNCIONES DE MANEJO DE DATOS ---

def save_to_csv(df, folder_path, year):
    """Guarda el DataFrame en un archivo CSV de forma incremental."""
    if not df.empty:
        csv_file = f"{folder_path}/{year}.csv"
        file_exists = os.path.exists(csv_file)
        df.to_csv(csv_file, mode="a", index=False, encoding='utf-8', header=not file_exists)
        print("Datos guardados en CSV...")

def create_temp_df(doc_id, date, section, sub_section, sub_sub_section, html_content, pdf_text, pdf_url, html_url, summary, full_combined_text):
    """Estructura los datos extraídos en un DataFrame y limpia el texto de cada celda."""
    today = datetime.today()
    read_date = f"{today.day}-{today.month}-{today.year}"

    new_df = pd.DataFrame([{
        "Identificador": doc_id,
        "Fecha_decreto": date,
        "Seccion": section,
        "Subseccion": sub_section,
        "Subsubseccion": sub_sub_section,
        "Resumen": summary,
        "Contenido": html_content,
        "Pdf_text": pdf_text,
        "text": full_combined_text,
        "Url_pdf": pdf_url,
        "Url_html": html_url,
        "Fecha_lectura": read_date,
    }])

    # Aplicar limpieza de espacios a todas las columnas
    for col in new_df.columns:
        new_df[col] = new_df[col].apply(clean_text)

    return new_df

# --- FUNCIONES DE EXTRACCIÓN DE TEXTO (PDF/OCR) ---

def extract_text_direct(pdf_path, min_chars=50):
    """Intenta extraer texto directamente del PDF usando PyMuPDF (muy rápido)."""
    try:
        direct_text = ""
        gc.collect()
        doc = fitz.open(pdf_path)
        for page in doc:
            direct_text += page.get_text()
        doc.close()
        
        # Si el texto es muy corto, devolvemos False para activar el OCR
        if direct_text and len(direct_text.strip()) > min_chars:
            return direct_text, True
        return "", False
    except Exception as e:
        print(f"Error en extracción directa: {e}")
        return "", False

def extract_text_ocr(pdf_path, language='spa'):
    """Convierte el PDF a imágenes y aplica OCR con Tesseract (más lento, para archivos escaneados)."""
    try:
        pages = convert_from_path(pdf_path, 300)
        full_text = ""
        for page in tqdm(pages, desc=f"OCR en {os.path.basename(pdf_path)}", leave=False):
            text = pytesseract.image_to_string(page, lang=language)
            full_text += text + "\n\n"
        return full_text
    except Exception as e:
        print(f"Error en OCR: {e}")
        return ""

def process_pdf(pdf_file_path):
    """Lógica principal de procesamiento: prueba primero directo, si falla usa OCR."""
    filename = os.path.basename(pdf_file_path)
    try:
        text, success = extract_text_direct(pdf_file_path)
        if not success:
            print(f"Usando OCR para {filename} (texto directo insuficiente)")
            text = extract_text_ocr(pdf_file_path)
        return text
    except Exception:
        with open("error_log.txt", "a") as f:
            f.write(f"Error en {filename}: {sys.exc_info()[0]}\n")
        return ""

def download_pdf(pdf_response, destination_path):
    """Escribe el contenido binario del PDF en el disco local."""
    try:
        with open(destination_path, "wb") as pdf_file:
            for chunk in pdf_response.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
            print(f"PDF descargado: {destination_path}")
    except Exception as e:
        print(f"Error al guardar PDF: {e}")

# --- LÓGICA PRINCIPAL DE SCRAPING ---

def scrape_full_days(*, starting_year: int):
    """Función principal para scrapear el BOJA (Boletín Oficial de la Junta de Andalucía)."""
    for year in range(starting_year, starting_year + 1):
        # Definición de rutas y creación de carpetas
        base_path = os.path.join(SCRIPT_DIR, f"{year}")
        pdf_dir = os.path.join(base_path, "PDF")
        html_dir = os.path.join(base_path, "HTML")
        error_log = os.path.join(base_path, "url_errors")
        checkpoint_file = os.path.join(SCRIPT_DIR, f"{year}", f"{year}.txt")

        for folder in [base_path, pdf_dir, html_dir]:
            os.makedirs(folder, exist_ok=True)

        # Gestión del punto de reanudación (Checkpoint)
        bulletin_number = 1
        if not os.path.exists(checkpoint_file):
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                f.write(f"{bulletin_number}")
        else:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                bulletin_number = int(f.read().strip())

        print(f"Iniciando en Boletín: {bulletin_number} del año: {year}")

        # Recorremos los días del año (hasta 365/366)
        for day in range(bulletin_number, 366):
            try:
                index_url = f"https://www.juntadeandalucia.es/boja/{year}/{day}/index.html"
                response, is_found = attempt_request(index_url, error_log)
                
                if is_found and response and response.status_code == 200:
                    soup_main = BeautifulSoup(response.text, "html.parser")
                    # Selección de enlaces de secciones según la estructura de la web
                    links = [a['href'] for a in soup_main.select('ul.listado_ordenado a')] + \
                            [a['href'] for a in soup_main.select('ol.listado_ordenado a')] + \
                            [a['href'] for a in soup_main.select('ol.listado_ordenado_boja a')]
                    
                    section_idx = 1
                    for section_link in links:
                        section_res, found_sec = attempt_request(section_link, error_log)
                        if found_sec and section_res and section_res.status_code == 200:
                            soup_sec = BeautifulSoup(section_res.text, "html.parser")
                            
                            # Intentar capturar la fecha del boletín
                            try:
                                bulletin_meta = soup_sec.find("span", class_="nota")
                            except:
                                bulletin_meta = None

                            # Lógica para determinar los enlaces de decretos según el año (cambios históricos en la web)
                            if year <= 2011:
                                decree_links = [a['href'] for a in soup_sec.select('div.item a[href]:not(.item_pdf)')]
                            elif year == 2012:
                                decree_links = [a['href'] for a in soup_sec.select('div.item a[href]:not(.item_pdf)')] if day < 91 else \
                                               [a['href'] for a in soup_sec.select('ul.sumario_pdf.grid_3.alpha a.item_html')]
                            else:
                                decree_links = [a['href'] for a in soup_sec.select('ul.sumario_pdf.grid_3.alpha a.item_html')]

                            decree_idx = 1
                            for decree_url in decree_links:
                                time.sleep(1) # Respeto al servidor
                                print(f"Procesando disposición: {decree_url}")
                                dec_res, found_dec = attempt_request(decree_url, error_log)

                                if found_dec and dec_res and dec_res.status_code == 200:
                                    soup_dec = BeautifulSoup(dec_res.text, "html.parser")
                                    doc_id = f"BOJA-{year}-Boletin-{day}-Seccion-{section_idx}-Decreto-{decree_idx}"
                                    pdf_path = os.path.join(pdf_dir, f"{doc_id}.pdf")

                                    # --- PARTE 1: DESCARGA Y PROCESO DE PDF ---
                                    pdf_online_url = None
                                    pdf_extracted_text = ""
                                    try:
                                        pdf_tag = soup_dec.find('a', class_='item_pdf_disposicion')
                                        if pdf_tag:
                                            pdf_online_url = pdf_tag['href']
                                            if not os.path.exists(pdf_path):
                                                pdf_resp, found_pdf = attempt_request(pdf_online_url, error_log)
                                                if found_pdf and pdf_resp.status_code == 200:
                                                    download_pdf(pdf_resp, pdf_path)
                                            
                                            # Extraer texto del PDF y luego borrarlo para ahorrar espacio
                                            pdf_extracted_text = process_pdf(pdf_path)
                                            if pdf_extracted_text:
                                                os.remove(pdf_path)
                                                print("PDF procesado y eliminado localmente.")
                                            else:
                                                log_error_url(error_log, pdf_online_url)
                                    except Exception as e:
                                        print(f"Error procesando PDF: {e}")

                                    # --- PARTE 2: EXTRACCIÓN DE METADATOS Y CONTENIDO HTML ---
                                    try:
                                        header_div = soup_dec.find("div", class_="punteado_izquierda cabecera_detalle_disposicion")
                                        bulletin_date_str = bulletin_meta.text.strip() if bulletin_meta else ""
                                        clean_date = bulletin_date_str.split("de")[-1].strip() if "de" in bulletin_date_str else ""
                                        
                                        title_sec = header_div.find("h2").text if header_div and header_div.find("h2") else ""
                                        title_sub = header_div.find("h3").text if header_div and header_div.find("h3") else ""
                                        title_subsub = header_div.find("h5").text if header_div and header_div.find("h5") else ""
                                        
                                        # Contenido textual de la página
                                        html_body = " ".join([p.get_text(strip=True) for p in soup_dec.find_all("p") if not p.find_parent("div", class_="alerta")])
                                        summary_text = " ".join([p.get_text(strip=True) for p in soup_dec.find_all("p") if not p.find_parent("div", class_="item")])
                                        
                                        # Unión de texto HTML + texto extraído del PDF
                                        full_text = f"{html_body}\n{pdf_extracted_text}"

                                        # Crear DataFrame y guardar
                                        df = create_temp_df(doc_id, clean_date, title_sec, title_sub, title_subsub, html_body, pdf_extracted_text, pdf_online_url, decree_url, summary_text, full_text)
                                        save_to_csv(df, base_path, year)
                                    
                                    except AttributeError as e:
                                        print(f"Error de atributos en HTML: {e}")
                                        
                                    decree_idx += 1
                        section_idx += 1
                    
                    # Guardar progreso en el archivo de texto
                    with open(checkpoint_file, 'w', encoding='utf-8') as f:
                        f.write(f"{day}")

                elif is_found and response.status_code == 404:
                    print(f"Fin del año detectado en el día: {day}")
                    break

            except Exception as e:
                print(f"Error inesperado en día {day}: {e}")
                continue

        # Nota: La sección de "suplementos" (días 500-700) se puede añadir aquí siguiendo la misma lógica.

if __name__ == "__main__":
    clize.run(scrape_full_days)