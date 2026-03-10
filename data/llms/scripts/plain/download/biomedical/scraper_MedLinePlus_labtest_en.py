"""Scraper de Pruebas de Laboratorio de MedlinePlus (EN).

Este módulo extrae páginas explicativas de pruebas médicas y test de laboratorio 
disponibles en MedlinePlus en su versión en inglés (`https://medlineplus.gov/lab-tests`).
Consolida cada test listado en su índice principal, extrayendo textos explicativos y,
particularmente importante, referencias bibliográficas cruzadas embebidas al final de 
los artículos (`mp-refs`). La información cruda va a directorios `docs/` organizados 
alfabéticamente y se indexa metadatos masivos a CSV/Parquet bidireccionales vía `polars`.

Example:
    Flujo de ejecución habitual::

        python scraper_MedLinePlus_labtest_en.py

    Levanta peticiones iterando sobre la colección entera, construyendo 
    documentos sueltos y finalizando en `output_en.parquet`.

Note:
    Extrae enlaces referenciales (ej. guías de la FDA o institutos clínicos) 
    empaquetándolos como strings particionados (`ref-idx|url|text;;...`).
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
    """Extrae la primera consonante o vocal de un título para indizado en carpetas.

    Baila alrededor de caracteres numéricos puros o tildados, filtrándolos
    antes de retornar un char explícito mayúsculo.

    Args:
        titulo (str): Título oficial o nombre clínico de la entrada.

    Returns:
        str: Letra capitular normalizada, u 'Otros' de ser caso atípico.
    """
    # Elimina tildes y convierte a mayúscula la primera letra alfabética válida
    titulo_normalizado = unicodedata.normalize('NFKD', titulo)
    letras = ''.join(c for c in titulo_normalizado if c.isalpha())
    return letras[0].upper() if letras else "Otros"

def safe_filename(nombre: str) -> str:
    """Transmuta un título amigable a nivel de Front a un nombre apto de SO.

    Args:
        nombre (str): Cadena principal.

    Returns:
        str: Secuencia limpiada habilitada para persistencia de disco duro.
    """
    # Reemplaza espacios por guiones bajos y elimina caracteres no permitidos
    nombre = nombre.strip().replace(' ', '_')
    return re.sub(r'[^\w\-_.]', '', nombre)


def error_log(error_path: str, search_url: str) -> None:
    """Agrega logs de traza en caso de fallas transaccionales hacia una URL.

    Args:
        error_path (str): Destino de salida (.txt se añade dinámicamente).
        search_url (str): Endpoint generador de la inconsistencia.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def pdf_to_text(pdf_path: str) -> str:
    """Decanta bytes a string crudo proveniente de un PDF almacenado.
    
    Toma archivo referenciado por PyMuPDF y retorna el texto íntegro 
    de todo el conteo de hojas en orden. (Módulo auxiliar).

    Args:
        pdf_path (str): Ruta válida hacia binario PDF.

    Returns:
        str: Cadena de texto continua de información contenida.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def try_pet(search_url: str, error_path: str) -> tuple:
    """Intenta consumir un Endpoint soportando Timeout y caídas momentáneas.

    Aplica múltiples retries (5) frente a anomalías con timeouts incrementales.

    Args:
        search_url (str): Archivo web objeto principal.
        error_path (str): Volcado donde persistirán aquellas queries infructuosas.

    Returns:
        tuple: Tupla combinada conteniendo Request Payload y Status OK/Not OK.
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
    """Cuerpo de ejecución para raspado del índice de Test de Laboratorios.
    
    Inicia en `/lab-tests`, levanta todos los elementos presentes en lista y procede a
    extraer los textos expositivos así como un vector referencial bibliográfico por prueba
    guardando el agregado en `output_en.parquet`.
    """
    path ="/home/mmg/scripts/scraper/MedlinePlus/lab_tests/en"
    docs = path + "/docs/"
    error_path = ""
    diccionario = []
    url = "https://medlineplus.gov/lab-tests"
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
    df.write_parquet(f"{path}/output_en.parquet")



if __name__ == "__main__":
    main()
