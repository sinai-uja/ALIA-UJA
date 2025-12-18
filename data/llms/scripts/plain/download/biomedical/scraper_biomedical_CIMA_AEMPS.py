import os
import requests
import fitz
import time
import polars as pl
import gc
from requests.exceptions import ChunkedEncodingError
from multiprocessing import Pool, cpu_count
from tqdm import tqdm


def pdf_to_text(pdf_path):
    """
    Convert a PDF file into a text string using the PyMuPDF (fitz) library.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Error al abrir el PDF {pdf_path}: {e}")
        return ""
    text_full = ""
    for page_num in range(doc.page_count):
        try:
            page = doc.load_page(page_num)
            text_full += page.get_text()
        except Exception as e:
            print(f"Error al extraer texto de la página {page_num} en {pdf_path}: {e}")
    return text_full


def error_log(error_path, url):
    """
    Append the error URL (or message) to the error log file.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")


def try_pet(search_url, error_path):
    """
    Try to get a response from a given URL.
    Repeats the request (up to 5 times) in case of a failed attempt.
    Logs errors if the request ultimately fails.
    Returns a tuple of (response, response_found_flag).
    """
    i = 0
    response_found = 0
    response = None
    try:
        response = requests.get(search_url, stream=True)
        if response and response.status_code == 200:
            response_found = 1
            return response, response_found
        elif response.status_code == 404:
            response_found = 1
            return response, response_found
        else:
            found = False
            for i in range(5):
                print(f"No se pudo acceder a {search_url}: reintentamos ({i+1})")
                time.sleep(i+1)
                response = requests.get(search_url)
                if response and response.status_code == 200:
                    print("Se ha aceptado el reintento de conexión")
                    found = True
                    break
            if not found:
                error_log(error_path, search_url)
            response_found = 1
            return response, response_found
    except ChunkedEncodingError:
        print(f"Error en la transferencia de datos al acceder a {search_url}")
        error_log(error_path, search_url)
        return None, 0
    except requests.exceptions.RequestException as e:
        print(f"Intento {i+1}: error al acceder a {search_url}: {e}")
        error_log(error_path, search_url)
        return None, 0


def process_document(args):
    """
    Process a single CIMA AEMPS document.
    
    Parameters:
    - args: a tuple containing (doc_type, doc_id, base_url, output_dir, error_path)
    
    For a given document type ('P', 'FT', or 'IPE') and id, the PDF URL is constructed,
    the page is requested, the PDF saved if found, and the text is extracted.
    
    Returns a dictionary with document info if successful or None otherwise.
    """
    doc_type, doc_id, base_url, output_dir, error_path = args
    pdf_url = f"{base_url}/{doc_type.lower()}/{doc_id}/{doc_type}_{doc_id}.pdf"
    print(f"Accediendo a {pdf_url}")
    
    pdf_response, pdf_response_found = try_pet(pdf_url, error_path)
    if pdf_response_found == 0 or pdf_response is None:
        print(f"No se ha podido acceder a {pdf_url}")
        return None

    # Create destination directory for the document type if it doesn't exist
    type_dir = os.path.join(output_dir, doc_type)
    os.makedirs(type_dir, exist_ok=True)

    if pdf_response.status_code == 404:
        print(f"El documento {pdf_url} no se ha encontrado (404).")
        return None

    # Define PDF file path and check for existing file
    pdf_path = os.path.join(type_dir, f"{doc_id}.pdf")
    print(f"Guardando en {pdf_path}")
    if os.path.exists(pdf_path):
        print(f"El archivo {pdf_path} ya existe")
        return None

    # Save the PDF
    try:
        with open(pdf_path, "wb") as file:
            file.write(pdf_response.content)
    except Exception as e:
        print(f"Error al guardar el PDF {pdf_path}: {e}")
        error_log(error_path, pdf_url)
        return None

    # Convert the PDF to text
    try:
        text = pdf_to_text(pdf_path)
    except Exception as e:
        print(f"Error al convertir el PDF a texto: {e}")
        error_log(error_path, pdf_url)
        return None

    return {"type": doc_type, "id": doc_id, "text": text}


def main(base_url="https://cima.aemps.es/cima/pdfs",
         output_dir="data/pdfs",
         error_dir="data/errors",
         parquet_dir="data/parquets",
         start_id=1,
         max_id=999999,
         save_interval=1000):
    """
    Scrape the CIMA AEMPS website to download PDFs of documents.
    
    Parameters:
    - base_url: Base URL for PDFs on the CIMA AEMPS website
    - output_dir: Directory to save downloaded PDFs
    - error_dir: Directory to save error logs
    - parquet_dir: Directory to save parquet files
    - start_id: Starting document ID
    - max_id: Maximum document ID to process
    - save_interval: How often to save accumulated data (in document count)
    """
    # Setup directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(error_dir, exist_ok=True)
    os.makedirs(parquet_dir, exist_ok=True)
    
    error_path = os.path.join(error_dir, "error_log")

    # Document types and download parameters
    ids_types = ["P", "FT", "IPE"]  # types of documents
    actual_id = start_id
    
    # Dictionary to accumulate extracted text for each document type
    dict_id_txt = {doc_type: [] for doc_type in ids_types}
    finished = False

    # Create a multiprocessing Pool to process tasks concurrently
    pool = Pool(processes=cpu_count())

    while not finished:
        # Prepare a list of tasks, one per document type for the current document id
        tasks = [(doc_type, actual_id, base_url, output_dir, error_path) for doc_type in ids_types]
        print(f"\nProcesando documento id: {actual_id}")
        results = pool.map(process_document, tasks)

        # Accumulate the extracted text if available
        for result in results:
            if result:
                doc_type = result["type"]
                dict_id_txt[doc_type].append({"id": result["id"], "text": result["text"]})
        
        actual_id += 1
        
        if actual_id >= max_id:
            finished = True

        # Save the collected texts periodically
        if actual_id % save_interval == 0:
            for doc_type in ids_types:
                # Determine the Parquet file path based on document type
                if doc_type == 'P':
                    parquet_filename = "cima_aemps_prospectos.parquet"
                elif doc_type == 'FT':
                    parquet_filename = "cima_aemps_fichas_tecnicas.parquet"
                elif doc_type == 'IPE':
                    parquet_filename = "cima_aemps_IPE.parquet"
                else:
                    continue

                parquet_path = os.path.join(parquet_dir, parquet_filename)

                # Only proceed if there's data to save
                if not dict_id_txt[doc_type]:
                    continue

                try:
                    df = pl.DataFrame(dict_id_txt[doc_type])
                    df.write_parquet(parquet_path, mode='a', engine='pyarrow')
                    print(f"Appended data to {parquet_path} for type {doc_type}")
                    dict_id_txt[doc_type] = []
                except Exception as e:
                    print(f"Error saving Parquet for {doc_type} at ID {actual_id}: {e}")
    
    pool.close()
    pool.join()

    # Save any remaining texts to parquet files after processing all IDs
    for doc_type in ids_types:
        if doc_type == 'P':
            parquet_filename = "cima_aemps_prospectos.parquet"
        elif doc_type == 'FT':
            parquet_filename = "cima_aemps_fichas_tecnicas.parquet"
        elif doc_type == 'IPE':
            parquet_filename = "cima_aemps_IPE.parquet"
        else:
            continue

        parquet_path = os.path.join(parquet_dir, parquet_filename)

        if not dict_id_txt[doc_type]:
            continue

        try:
            df = pl.DataFrame(dict_id_txt[doc_type])
            df.write_parquet(parquet_path, mode='a', engine='pyarrow')
            print(f"Appended final data to {parquet_path} for type {doc_type}")
        except Exception as e:
            print(f"Error saving final Parquet for {doc_type}: {e}")


def get_texts(pdf_dir="data/pdfs", parquet_dir="data/parquets"):
    """
    Extract texts from the downloaded PDFs and save to Parquet files.
    
    Parameters:
    - pdf_dir: Directory where the PDFs are stored
    - parquet_dir: Directory to save parquet files
    """
    os.makedirs(parquet_dir, exist_ok=True)
    
    # Iterate through each document type directory
    df_comp = pl.DataFrame(schema={"type": pl.Utf8, "id": pl.Utf8, "text": pl.Utf8})
    
    for doc_type in os.listdir(pdf_dir):
        df = pl.DataFrame(schema={"type": pl.Utf8, "id": pl.Utf8, "text": pl.Utf8})
        type_dir = os.path.join(pdf_dir, doc_type)
        print(f"Accediendo a {type_dir}")
        
        if os.path.isdir(type_dir):
            pdf_files = [f for f in os.listdir(type_dir) if f.endswith(".pdf")]
            for pdf_file in tqdm(pdf_files, desc=f"Procesando {doc_type}"):
                pdf_path = os.path.join(type_dir, pdf_file)
                text = pdf_to_text(pdf_path)
                if text:
                    df = df.vstack(pl.DataFrame({
                        "type": doc_type,
                        "id": pdf_file.split(".")[0],
                        "text": text
                    }))
        
        # Save the DataFrame to a Parquet file
        parquet_path = os.path.join(parquet_dir, f"cima_aemps_{doc_type}.parquet")
        try:
            df.write_parquet(parquet_path)
            print(f"Guardado parquet {parquet_path} con todos los textos")
        except Exception as e:
            print(f"Error al guardar el parquet con todos los textos: {e}")
        
        df_comp = df_comp.vstack(df)
        print(df)
        del df
        gc.collect()

    # Save complete dataset
    parquet_path = os.path.join(parquet_dir, "cima_aemps_complete.parquet")
    try:
        df_comp.write_parquet(parquet_path)
        print(f"Guardado parquet {parquet_path} con todos los textos")
    except Exception as e:
        print(f"Error al guardar el parquet con todos los textos: {e}")
    print(df_comp)


if __name__ == "__main__":
    # Example usage with default parameters
    # Adjust parameters as needed for your environment
    main(
        base_url="https://cima.aemps.es/cima/pdfs",
        output_dir="data/pdfs",
        error_dir="data/errors",
        parquet_dir="data/parquets",
        start_id=1,
        max_id=999999,
        save_interval=1000
    )
