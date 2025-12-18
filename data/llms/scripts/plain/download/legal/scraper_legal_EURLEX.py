from bs4 import BeautifulSoup
import requests
import fitz
import os
from requests.exceptions import ChunkedEncodingError
import time
import polars as pl


def pdf_to_text(pdf_path):
    """
    Convert a PDF file into a text string using the PyMuPDF (fitz) library.
    """
    try:
        doc = fitz.open(pdf_path)
        text_full = ""
        
        for num_pag in range(doc.page_count):
            pag = doc.load_page(num_pag)
            text_full += pag.get_text()
        
        return text_full
    except Exception as e:
        print(f"Error al abrir/procesar el PDF {pdf_path}: {e}")
        return ""


def error_log(error_path, search_url):
    """
    Append the error URL to the error log file.
    """
    try:
        os.makedirs(os.path.dirname(error_path), exist_ok=True)
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")


def try_pet(search_url, error_path, max_retries=5):
    """
    Try to get a response from a given URL with retry logic.
    
    Parameters:
    - search_url: URL to fetch
    - error_path: Path to log errors
    - max_retries: Maximum number of retry attempts
    
    Returns:
    - tuple: (response, response_found_flag)
    """
    response_find = 0
    response = None
    
    try:
        response = requests.get(search_url, stream=True, timeout=30)
        
        if response and response.status_code == 200:
            response_find = 1
            return response, response_find
        elif response.status_code == 404:
            response_find = 1
            return response, response_find
        else:
            find = False
            for i in range(max_retries):
                print(f"No se pudo acceder a {search_url}: reintentamos ({i+1}/{max_retries})")
                time.sleep(i + 1)
                response = requests.get(search_url, timeout=30)
                
                if response and response.status_code == 200:
                    print("Se ha aceptado el reintento de conexión")
                    find = True
                    break
            
            if not find:
                error_log(error_path, search_url)
            
            response_find = 1
            return response, response_find
        
    except ChunkedEncodingError:
        print(f"Error en la transferencia de datos al acceder a {search_url}")
        error_log(error_path, search_url)
        return None, 0
        
    except requests.exceptions.RequestException as e:
        print(f"Error al acceder a {search_url}: {e}")
        error_log(error_path, search_url)
        return None, 0


def main(base_url="https://eur-lex.europa.eu/search.html",
         download_url="https://eur-lex.europa.eu/legal-content",
         output_dir="data/docs",
         error_dir="data/errors",
         languages=None,
         start_page=1,
         max_pages=7816,
         overwrite=False):
    """
    Scrape EUR-Lex documents and download PDFs in multiple languages.
    
    Parameters:
    - base_url: Base URL for EUR-Lex search
    - download_url: Base URL for downloading documents
    - output_dir: Directory to save downloaded PDFs
    - error_dir: Directory to save error logs
    - languages: List of language codes to download (default: ["ES", "EN", "DE", "FR", "IT", "PT"])
    - start_page: Starting page number
    - max_pages: Maximum number of pages to process
    - overwrite: Whether to overwrite existing output files
    """
    # Setup directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(error_dir, exist_ok=True)
    
    # Default languages
    if languages is None:
        languages = ["ES", "EN", "DE", "FR", "IT", "PT"]
    
    # Error log paths
    error_path = os.path.join(error_dir, "error_log")
    error_page_path = os.path.join(error_dir, "error_page_log")
    no_language_dir = os.path.join(output_dir, "missing_languages")
    os.makedirs(no_language_dir, exist_ok=True)
    
    # Check if output already exists
    output_parquet = os.path.join(output_dir, "output.parquet")
    if os.path.exists(output_parquet) and not overwrite:
        print(f"Ya existe el archivo {output_parquet}")
        print("Usa overwrite=True para sobrescribir o elimina el archivo manualmente")
        return
    
    # Initialize data collection
    dict_id_txt = {language: [] for language in languages}
    actual_page = start_page
    id_txt = 1
    finished = False
    
    # Construct search URL
    search_params = "orAU_CODEDGroup=AU_CODED%3DCJ&sortOneOrder=desc&sortOne=TI_SORT&page="
    
    while not finished:
        # Build current page URL
        actual_eurlex_url = f"{base_url}?{search_params}{actual_page}&lang=es&type=advanced&qid=1741774396292"
        
        response, response_find = try_pet(actual_eurlex_url, error_path)
        
        if response_find == 0 or response is None:
            print(f"No se ha podido acceder a {actual_eurlex_url}")
            error_log(error_page_path, actual_eurlex_url)
            actual_page += 1
            continue
        
        if response.status_code != 200:
            print(f"Error al acceder a la página {actual_page}: status {response.status_code}")
            error_log(error_page_path, actual_eurlex_url)
            actual_page += 1
            continue
        
        print(f"Accediendo a página {actual_page}/{max_pages}")
        
        # Parse HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract document links
        try:
            options = soup.find("div", class_="EurlexContent RelocateFilteringWidget")
            
            if not options:
                print(f"No se han encontrado documentos en la página {actual_page}")
                actual_page += 1
                continue
            
            result_docs = options.find_all("ul", class_="SearchResultDoc")
            
            if not result_docs:
                print(f"No se han encontrado más documentos en la página {actual_page}")
                actual_page += 1
                continue
            
            # Process each document
            for option in result_docs:
                link_tag = option.find("a")
                if not link_tag or 'href' not in link_tag.attrs:
                    continue
                
                link = link_tag['href'].split('?uri=')[-1]
                
                # Download in all requested languages
                for language in languages:
                    language_link = link.replace("EN", language)
                    pdf_url = f"{download_url}/{language}/TXT/PDF/?uri={language_link}"
                    print(f"Accediendo a {pdf_url}")
                    
                    pdf_response, pdf_response_find = try_pet(pdf_url, error_path)
                    
                    if pdf_response_find == 0 or pdf_response is None:
                        print(f"No se ha podido acceder a {pdf_url}")
                        continue
                    
                    # Create language directory
                    language_dir = os.path.join(output_dir, language)
                    os.makedirs(language_dir, exist_ok=True)
                    
                    # Handle 404 (document not available in this language)
                    if pdf_response.status_code == 404:
                        print(f"El documento no está disponible en {language}")
                        missing_log = os.path.join(no_language_dir, f"{language}_missing.txt")
                        try:
                            with open(missing_log, "a", encoding="utf-8") as file:
                                file.write(pdf_url + "\n")
                        except Exception as e:
                            print(f"Error al escribir en el archivo de idiomas faltantes: {e}")
                        continue
                    
                    # Generate safe filename
                    if '/' in language_link:
                        safe_filename = language_link.split('?uri=')[-1].replace('/', "_")
                    else:
                        safe_filename = pdf_url.split('uri=')[-1]
                    
                    pdf_path = os.path.join(language_dir, f"{safe_filename}.pdf")
                    print(f"Guardando en {pdf_path}")
                    
                    # Save PDF
                    try:
                        with open(pdf_path, "wb") as file:
                            file.write(pdf_response.content)
                    except Exception as e:
                        print(f"Error al guardar el PDF {pdf_path}: {e}")
                        error_log(error_path, pdf_url)
                        continue
                    
                    # Extract text from PDF
                    try:
                        text = pdf_to_text(pdf_path)
                        dict_id_txt[language].append({"id": id_txt, "txt": text})
                    except Exception as e:
                        print(f"Error al convertir el PDF a texto: {e}")
                        error_log(error_path, pdf_url)
                
                id_txt += 1
        
        except Exception as e:
            print(f"Error al extraer los elementos de la página {actual_page}: {e}")
            error_log(error_page_path, actual_eurlex_url)
        
        actual_page += 1
        
        if actual_page > max_pages:
            finished = True
    
    # Save collected data to Parquet
    try:
        df = pl.DataFrame(dict_id_txt)
        df.write_parquet(output_parquet)
        print(f"Guardado archivo final en {output_parquet}")
    except Exception as e:
        print(f"Error al guardar el archivo parquet: {e}")


if __name__ == "__main__":
    # Example usage with default parameters
    main(
        base_url="https://eur-lex.europa.eu/search.html",
        download_url="https://eur-lex.europa.eu/legal-content",
        output_dir="data/docs",
        error_dir="data/errors",
        languages=["ES", "EN", "DE", "FR", "IT", "PT"],
        start_page=1,
        max_pages=7816,
        overwrite=False
    )
