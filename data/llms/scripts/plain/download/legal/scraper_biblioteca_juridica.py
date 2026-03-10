"""Recolector de códigos y colecciones de la Biblioteca Jurídica del BOE.

Este script automatiza la descarga y extracción de texto de los PDFs disponibles en la
Biblioteca Jurídica del BOE (`boe.es/biblioteca_juridica`). Itera sobre las secciones y
colecciones de la página de índice, accede a la página de cada documento, extrae el enlace
PDF de tipo `puntoPDF2` y descarga y procesa el PDF con PyMuPDF. Los resultados se guardan
en un archivo Parquet único.

Attributes:
    bibjur_url (str): URL de índice de la Biblioteca Jurídica del BOE.
    base_url (str): URL raiz del BOE.
    path (str): Directorio local donde se guardan los PDFs.
    parquet (str): Directorio de salida para los Parquets.
"""

from bs4 import BeautifulSoup
import requests
import urllib.parse
import fitz
import os
from requests.exceptions import ChunkedEncodingError
import time
import polars as pl
import sys
from multiprocessing import Pool, cpu_count

def pdf_to_text(pdf_path):
    """Extrae el texto completo de un PDF página a página usando PyMuPDF.

    Args:
        pdf_path (str): Ruta local al archivo PDF.

    Returns:
        str: Texto concatenado de todas las páginas.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def error_log(error_path, search_url):
    """Registra una URL fallida en un archivo de log.

    Args:
        error_path (str): Ruta del archivo de log (sin extensión `.txt`).
        search_url (str): URL que produjo el error.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def try_pet(search_url, error_path):
    """Ejecuta una petición GET protegida con reintentos ante caídas HTTP.

    Args:
        search_url (str): URL a consultar.
        error_path (str): Ruta del log de errores (sin extensión).

    Returns:
        tuple[requests.models.Response | None, int]: Respuesta HTTP y bandera de éxito (1) o fallo (0).
    """
    i = 0 
    response_find = 0
    response = None
    try:
        response = requests.get(search_url, stream=True)
        if response and response.status_code == 200:
            response_find = 1
            return response, response_find
        elif response.status_code == 404:
            response_find = 1
            return response, response_find
        else:
            find = False
            for i in range(5):
                print(f"No se pudo acceder a {search_url}: reintentamos")
                time.sleep(i+1)
                response = requests.get(search_url) 
                if response and response.status_code == 200:
                    print("Se ha aceptado el reintento de conexion")
                    find = True
                    break
            if find == False:
                error_log(error_path, search_url)
            response_find = 1
            return response, response_find
    except ChunkedEncodingError as e:
        print(f"Error en la transferencia de datos.")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find
    except requests.exceptions.RequestException as e:
        print(f"Intento {i+1}: error al acceder a {search_url}: {e}")
        error_log(error_path, search_url)
        response_find = 0
        response = None
        return response, response_find

def main():
    """Orquestador del scraping de la Biblioteca Jurídica del BOE.

    Accede al índice de códigos `boe.es/biblioteca_juridica`, extrae la lista de secciones y
    colecciones, y por cada documento navega a su página de detalle para obtener el enlace PDF
    de tipo `puntoPDF2`. Descarga el PDF y extrae el texto con PyMuPDF.
    Skippea documentos ya descargados. Guarda un Parquet al final.
    """
    bibjur_url = "https://www.boe.es/biblioteca_juridica/index.php?tipo=C&modo=2"
    base_url = "https://www.boe.es"
    error_path = "/home/mmg/scraper/scraper_biblioteca_juridica/errors"
    path = "/home/mmg/scraper/scraper_biblioteca_juridica/docs"
    parquet = "/home/mmg/scraper/scraper_biblioteca_juridica/parquet"
    dict_id_txt = []

    finished = False

    while not finished:
        response, response_find = try_pet(bibjur_url, error_path)
        
        if response_find == 0:
            print(f"No se ha podido acceder a {bibjur_url}")

        else:
            if response.status_code == 404:
                print(f"No se han encontrado más documentos en la página")
                continue
            else:
                if response.status_code == 200:

                    print(f"Accediendo a página {bibjur_url}")
                    # Parse the HTML content
                    soup = BeautifulSoup(response.text, 'html.parser')
                    try:
                        options = soup.find_all("div", class_="lista_bloque")
                        for option in options:
                            seccion = (option.find("span", class_="epigrafe")).text
                            for label in option.find_all("li", class_="etiqueta"):
                                a_tag = label.find("a")
                                if a_tag and a_tag.has_attr('href'):
                                    href = a_tag['href']

                                    actual_doc = f"{base_url}{href}"
                                    response_doc, response_find_doc = try_pet(actual_doc, error_path)

                                    if response_find_doc == 0:
                                        print(f"No se ha podido acceder a {actual_doc}")

                                    else:
                                        if response_doc.status_code == 404:
                                            print(f"No se han encontrado documentos")
                                            continue
                                        else:
                                            if response.status_code == 200:

                                                print(f"Accediendo a página {actual_doc}")
                                                # Parse the HTML content
                                                soup_doc = BeautifulSoup(response_doc.text, 'html.parser')

                                                a_tag_doc = soup_doc.find("li", class_="puntoPDF2").find("a")
                                                if a_tag_doc and a_tag_doc.has_attr('href'):
                                                    href = a_tag_doc['href']
                                                    print(f"Accediendo a {actual_doc}")
                                                    pdf_response, pdf_response_find = try_pet(f"https://www.boe.es/biblioteca_juridica/codigos/{href}", error_path)

                                                    if pdf_response_find == 0:
                                                        
                                                        try:
                                                            with open(f"{path}/missign.txt", "a", encoding="utf-8") as file:
                                                                file.write(f"https://www.boe.es/biblioteca_juridica/codigos/{href}" + "\n")
                                                        except Exception as e:
                                                            print(f"Error al escribir en el archivo de errores: {e}")
                                                        print(f"No se han encontrado documentos")
                                                        continue
                                                    else:
                                                       
                                                        if not os.path.exists(f"{path}"):
                                                            os.makedirs(f"{path}")
                                                        pdf_path = f"{path}/{href.split('=')[-1].split('.')[0]}.pdf"
                                                        print(f"Guardando en {pdf_path}")
                                                        if os.path.exists(pdf_path):
                                                            print(f"El archivo {pdf_path} ya existe")
                                                            continue
                                                        with open(pdf_path, "wb") as file:
                                                            file.write(pdf_response.content)
                                                        try:
                                                            text = pdf_to_text(pdf_path)
                                                        except Exception as e:
                                                            print(f"Error al convertir el PDF a texto: {e}")
                                                            error_log(error_path, href)
                                                            continue
                                                        try:
                                                            dict_id_txt.append({"id": href.split('=')[-1].split('.')[0], "txt": text, "url": actual_doc, "seccion": seccion})
                                                            print(f"Datos regogidos: \nid: {href.split('=')[-1].split('.')[0]}, txt: EL TEXTO, url:  {actual_doc}, seccion:  {seccion}")
                                                        except Exception as e:
                                                            print(f"Error al añadir el texto a la lista: {e}")
                                                            continue
                                                    if 'Codigo_de_Patronos' in actual_doc:
                                                        finished = True 
                    except Exception as e:
                        print(f"Error al extraer los elementos de la página: {e}")
                        continue
                        
    try:
        df = pl.DataFrame(dict_id_txt)
        df.write_parquet(f"{path}/output.parquet")
        
    except Exception as e:
        print(f"Error al guardar el parquet: {e}")

if __name__ == "__main__":
    main()
