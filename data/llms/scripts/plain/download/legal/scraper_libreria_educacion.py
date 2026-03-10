"""Recolector de publicaciones de la Librería de Educación del Gobierno de España.

Este script automatiza la descarga y extracción de texto de publicaciones digitales
disponibles en `libreria.educacion.gob.es`. Itera página a página sobre el catálogo
(lote 2831), accede a la página de cada libro, localiza el enlace al PDF en el bloque
`box-price`, lo descarga y extrae el texto con PyMuPDF. Los resultados se guardan en un
archivo Parquet único.

Attributes:
    url (str): URL base del catálogo paginado.
    path (str): Directorio raíz del proyecto.
    docs_path (str): Subcarpeta de PDFs descargados.
    error_path (str): Subcarpeta para logs de errores.
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
import re


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
    """Orquestador del scraping de la Librería de Educación.

    Itera página a página sobre el catálogo paginado. Por cada libro:
    - Navega a la página de detalle
    - Extrae el título y año de publicación (con regex)
    - Localiza el enlace al PDF en el bloque `box-price`
    - Descarga el PDF y extrae el texto con PyMuPDF
    - Acumula los datos en una lista
    La iteración termina cuando no se encuentran más libros en la página.
    Al finalizar guarda un Parquet único.
    """
    url = "https://www.libreria.educacion.gob.es/lote/2831/?p="
    path ="/home/mmg/scraper/libreria_educacion_gob"
    docs_path ="/home/mmg/scraper/libreria_educacion_gob/docs"
    error_path = "/home/mmg/scraper/libreria_educacion_gob/errors"
    contador_pagina = 0

    diccionario = []

    finished = False
    while not finished:
        url_completa = f"{url}{contador_pagina}"
        contador_pagina +=1

        response, response_find = try_pet(url_completa, error_path)

        if response_find == 0:
            print(f"No se ha podido acceder a {url_completa}")

        else:
            if response.status_code == 404:
                print(f"No se han encontrado más documentos en la página")
                continue

            else:
                if response.status_code == 200:

                    print(f"Accediendo a página {url_completa}")
                    # Parse the HTML content
                    soup = BeautifulSoup(response.text, 'html.parser')
                    try:
                        enlaces_libros = soup.find_all("li", class_="book")
                        if not enlaces_libros:  # Si la lista está vacía
                            finished = True
                            print(f"No se encontraron libros en la página {url_completa}. Finalizando.")
                            continue
                        for libro in enlaces_libros:
                            enlace_relativo = libro.find("a")["href"]
                            enlace_libro_completo = "https://www.libreria.educacion.gob.es" + enlace_relativo
                            print(f"Accediendo al libro: {enlace_libro_completo}")

                            response_doc, response_find_doc = try_pet(enlace_libro_completo, error_path)

                            if response_find_doc == 0:
                                print(f"No se ha podido acceder a {enlace_libro_completo}")

                            else:
                                if response_doc.status_code == 404:
                                    print(f"No se han encontrado documentos")
                                    continue
                                else:
                                    if response.status_code == 200:

                                        print(f"Accediendo a página {enlace_libro_completo}")
                                        # Parse the HTML content
                                        soup_doc = BeautifulSoup(response_doc.text, 'html.parser')

                                        titulo = soup_doc.find("h1", class_="book-title").text.strip()
                                        print(f"Título del libro: {titulo}")
                                        match = re.search(r"\b(19|20)\d{2}(?:-\d)?\b", titulo)
                                        anio = match.group(0)


                                        a_tag_doc = soup_doc.find("div", class_="box-price").find("a")

                                        if a_tag_doc and a_tag_doc.has_attr('href'):
                                            href = a_tag_doc['href']
                                            print(f"Accediendo a {href}")
                                            pdf_response, pdf_response_find = try_pet(f"https://www.libreria.educacion.gob.es/{href}", error_path)

                                            if pdf_response_find == 0:
                                                
                                                try:
                                                    with open(f"{path}/missign.txt", "a", encoding="utf-8") as file:
                                                        file.write(f"https://www.libreria.educacion.gob.es/{href}" + "\n")
                                                except Exception as e:
                                                    print(f"Error al escribir en el archivo de errores: {e}")
                                                print(f"No se han encontrado documentos")
                                                continue
                                            else:
                                                
                                                if not os.path.exists(f"{path}"):
                                                    os.makedirs(f"{path}")

                                                ebook_id = href.split("/")[2]
                                                print(ebook_id)

                                                pdf_path = f"{docs_path}/{anio}_{ebook_id}.pdf"

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
                                                    diccionario.append({"id": ebook_id, "txt": text, "url": enlace_libro_completo, "anio": anio})
                                                    print(f"Datos regogidos: \nid: {ebook_id}, txt: EL TEXTO, url:  {enlace_libro_completo}, anio:  {anio}")
                                                except Exception as e:
                                                    print(f"Error al añadir el texto a la lista: {e}")
                                                    continue
                    except Exception as e:
                        print(f"Error al extraer los elementos de la página: {e}")
                        continue
                        
    try:
        df = pl.DataFrame(diccionario)
        df.write_parquet(f"{path}/output.parquet")
        
    except Exception as e:
        print(f"Error al guardar el parquet: {e}")
        



if __name__ == "__main__":
    main()
