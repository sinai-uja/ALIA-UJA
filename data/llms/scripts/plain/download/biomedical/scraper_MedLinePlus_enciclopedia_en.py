"""Scraper de la Enciclopedia Médica de MedlinePlus (EN).

Este módulo recopila los artículos de la enciclopedia de salud de MedlinePlus 
en su versión en inglés (`https://medlineplus.gov/ency/`). Se basa en el índice
alfabético general (`A` a `Z`) para extraer página a página las entradas (enfermedades, 
síntomas, pruebas, etc.). Los datos recolectados se depositan en disco como ficheros 
`.txt` sueltos agrupados por letra inicial, a la vez que se registra todo en un log
tabular estructurado formato `.parquet` mediante `polars`.

Example:
    Flujo de uso desatendido::

        python scraper_MedLinePlus_enciclopedia_en.py

    Iniciará procesos de rastreo en el root, creará carpetas como `docs/A`
    y alojará el volcado individual y el set de datos final `output_en.parquet`.

Note:
    Depende de `BeautifulSoup4` para el enrutamiento dentro del DOM y `polars`
    para el registro masivo de datos crudos. Las extracciones PDF (`fitz`) conviven 
    como utilidad legacy pero prima el consumo programático del HTML con la lógica
    tolerante de `try_pet`.
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

def extraer_meds_id(url: str) -> str:
    """Consigue el token unívoco referencial a partir del path de una URL.

    Elimina sufijos de idioma potenciales o extensiones (`.htm`) para
    extraer un string identificador canónico de la entrada de la enciclopedia.

    Args:
        url (str): Dirección web de la hoja enciclopédica.

    Returns:
        str: ID nominal saneado.
    """
    import os
    # Tomar la parte final del URL
    base = os.path.basename(url)
    # Quitar la extensión
    nombre = os.path.splitext(base)[0]
    # Quitar sufijo '-es' si existe
    if nombre.endswith('-es'):
        nombre = nombre[:-3]  # eliminar los últimos 3 caracteres
    return nombre

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
    de todo el conteo de hojas en orden.

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

    Aplica múltiples retries (5) frente a anomalías con timeouts incremental.

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
    """Rutina troncal del pipeline extractor enciclopédico de MedlinePlus EN.

    Ataca un índice de URLs fijas basadas en un array predefinido de letras
    de la A a la Z. Con cada petición extrae un subíndice (etiquetas 'li') y navega 
    iterativamente a los apartados enciclopédicos. Acumula la narrativa hallada en etiquetas
    centrales e hila reportes crudos y estructurados a disco.
    """
    path ="/home/mmg/scripts/scraper/MedlinePlus/enciclopedia/en"
    docs = path + "/docs/"
    error_path = ""
    abecedario = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'Ñ', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
    diccionario = []
    base_url = "https://medlineplus.gov/ency/"

    for letra in abecedario:
        print(f"Letra: {letra}")
        url = f"https://medlineplus.gov/ency/encyclopedia_{letra}.htm"
        response, response_find = try_pet(url, error_path)
        if not response_find:
            continue
        soup = BeautifulSoup(response.text, 'html.parser')
        try:
            ul_index  = soup.find('ul', id='index')
            textos_li = [li.get_text(strip=True) for li in ul_index.find_all('li')]
            enlaces_li = [li.a['href'] for li in ul_index.find_all('li') if li.a]
            #print(textos_li)
            print(len(enlaces_li))
            for enlace in enlaces_li:
                time.sleep(1)
                enlace_url = base_url + enlace
                response, response_find = try_pet(enlace_url, error_path)
                if not response_find:
                    continue
                soup_palabra = BeautifulSoup(response.text, 'html.parser')
                titulo = soup_palabra.find('div', class_='page-title').find('h1').get_text(strip=True)
                print(f"Palabra: {titulo}")
                



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
                    
                    
                    id_med = extraer_meds_id(enlace_url)
                    
                    diccionario.append({
                    "title": titulo,
                    "link": enlace_url,
                    "txt": textos_extraidos,
                    "letter": letra,
                    "category": "encyclopedia",
                    "id": id_med
                    })

                    print(
                        "Título:", titulo,
                        "| Enlace:", enlace_url,
                        "| Letra:", letra,
                        "| Texto:", #textos_extraidos,
                        "| ID:", id_med
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
