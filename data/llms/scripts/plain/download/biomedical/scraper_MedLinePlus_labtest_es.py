"""Scraper de Pruebas de Laboratorio de MedlinePlus (ES).

Este módulo extrae páginas explicativas de pruebas médicas y test de laboratorio 
disponibles en MedlinePlus en su versión en español (`https://medlineplus.gov/spanish/pruebas-de-laboratorio`).
Consolida cada test listado en su índice, extrayendo textos explicativos y 
referencias bibliográficas cruzadas embebidas al final de los artículos (`mp-refs`).
La información cruda se exporta a directorios locales iterados alfabéticamente
y se compila una traza masterizada en `output_es.parquet` usando `polars`.

Example:
    Flujo de ejecución habitual::

        python scraper_MedLinePlus_labtest_es.py

    Rastreará el índice nativo de pruebas en castellano procesando, guardando y
    retornando estado en la Shell a la vez que actualiza los .txt y .parquet.
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
from requests.compat import urljoin

import unicodedata


def get_letra_directorio(titulo: str) -> str:
    """Clasifica un test en base a su inicial, desprovisto de tildados castellanos.

    Args:
        titulo (str): Título oficial de cabera h1.

    Returns:
        str: Carácter inicial estandarizado [A-Z], o "Otros".
    """
    # Elimina tildes y convierte a mayúscula la primera letra alfabética válida
    titulo_normalizado = unicodedata.normalize('NFKD', titulo)
    letras = ''.join(c for c in titulo_normalizado if c.isalpha())
    return letras[0].upper() if letras else "Otros"

def safe_filename(nombre: str) -> str:
    """Sanea una cadena de texto para conformar nombres en particiones locales.

    Args:
        nombre (str): Nombre crudo base.

    Returns:
        str: Nombre sin espacios (convertidos a `_`) ni símbolos improcedentes.
    """
    # Reemplaza espacios por guiones bajos y elimina caracteres no permitidos
    nombre = nombre.strip().replace(' ', '_')
    return re.sub(r'[^\w\-_.]', '', nombre)


def error_log(error_path: str, search_url: str) -> None:
    """Persiste en un `.txt` listado todos aquellos endpoints declinados.

    Args:
        error_path (str): Salida del txt en directorio raíz.
        search_url (str): Dominio inalcanzado tras retries.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def pdf_to_text(pdf_path: str) -> str:
    """Utilidad secundaria: Convierte contenido empaquetado PDF a strings con `fitz`.

    Args:
        pdf_path (str): Fichero objeto local.

    Returns:
        str: Texto unificado crudo.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def try_pet(search_url: str, error_path: str) -> tuple:
    """Manejador de resiliencia web HTTP para Requests.

    Evita Timeouts colgados y saltos mal formateados repitiendo accesos (hasta 5 veces).
    
    Args:
        search_url (str): Endpoint Health Web en Español.
        error_path (str): Referencia txt si la conexión desiste irresolublemente.

    Returns:
        tuple: Payload request / Status Binary Indicator.
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

def main() -> None:
    """Cuerpo ejecutor principal del listado de test médicos en español.
    
    Navega partiendo del índice español de Pruebas de Laboratorios, extrae su red
    de enlaces directos por prueba y genera por volcado de BeautifulSoup 
    textos, citas y su inserción final a `output_es.parquet` utilizando la 
    robustez vectorial de Polars.
    """
    path ="/home/mmg/scripts/scraper/MedlinePlus/lab_tests/es"
    docs = path + "/docs/"
    error_path = ""
    diccionario = []
    url = "https://medlineplus.gov/spanish/pruebas-de-laboratorio"

    contador = 0
    response, response_find = try_pet(url, error_path)
    if not response_find:
        print("No se ha encontrado respuesta")
    soup = BeautifulSoup(response.text, 'html.parser')
    try:
        ul_index  = soup.find('div', class_='main')
        textos_li = [li.get_text(strip=True) for li in ul_index.find_all('li')]
        enlaces_li = [li.a['href'] for li in ul_index.find_all('li') if li.a]
        #print(textos_li)
        print(len(enlaces_li))
        for enlace_url in enlaces_li:
            time.sleep(1)
            response, response_find = try_pet(enlace_url, error_path)
            if not response_find:
                continue
            soup_palabra = BeautifulSoup(response.text, 'html.parser')
            titulo = soup_palabra.find('div', class_='page-title').find('h1').get_text(strip=True)
            print(f"Palabra: {titulo}")
            

            # Extraer referencias como URLs y texto
            references_div = soup_palabra.find("div", class_="mp-refs")
            references_parts = []

            if references_div:
                ref_links = references_div.find_all('a')
                for ref_idx, ref in enumerate(ref_links, 1):
                    ref_url = ref.get('href', '')
                    ref_text = ref.get_text(strip=True)
                    # Crear string en formato: ref-1|url|texto
                    ref_string = f"ref-{ref_idx}|{ref_url}|{ref_text}"
                    references_parts.append(ref_string)

            # Unir todas las referencias con separador ;;
            references_final = ";;".join(references_parts) if references_parts else ""

                    

            # Buscar el contenedor principal
            main_div = soup_palabra.find('div', class_=lambda x: x in ['main', 'main-single'])
            # Crear una lista con textos visibles
            textos_extraidos = []

            if main_div:
                # Buscar todas las etiquetas relevantes, en orden
                etiquetas = ['h1', 'h2', 'h3', 'p', 'li']
                for tag in main_div.find_all(etiquetas):
                    texto = tag.get_text(separator=' ', strip=True)
                    if texto:
                        textos_extraidos.append(texto)

                contenido_txt = titulo + '\n\n' + '\n'.join(textos_extraidos)

                # Obtener la letra para organizar por carpetas
                letra = get_letra_directorio(titulo)

                # Crear la carpeta por letra si no existe
                letra_path = os.path.join(docs, letra)
                os.makedirs(letra_path, exist_ok=True)

                
                # Guardar el archivo .txt dentro de la subcarpeta
                nombre_archivo = safe_filename(titulo) + ".txt"
                ruta_completa = os.path.join(letra_path, nombre_archivo)
                with open(ruta_completa, "w", encoding="utf-8") as f:
                    f.write(contenido_txt)
                


                
                diccionario.append({
                "title": titulo,
                "link": enlace_url,
                "txt": textos_extraidos,
                "letter": letra,
                "category": "lab_test",
                "references": references_final
                })

                print(
                    "Título:", titulo,
                    "| Enlace:", enlace_url,
                    "| Letra:", letra,
                    "| Texto:", #textos_extraidos,
                    "| References:", references_final
                )

                print(f"Texto guardado en el archivo: {ruta_completa}")
            else:
                print("No se encontró el div con clase 'main' o 'main-single'")
    except Exception as e:
        print(f"Error al guardar parquet: {e}")

    df = pl.DataFrame(diccionario)
    df.write_parquet(f"{path}/output_es.parquet")



if __name__ == "__main__":
    main()
