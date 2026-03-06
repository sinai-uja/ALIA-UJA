"""Scraper del Vademécum de MedlinePlus - Información de Medicamentos (EN).

Este módulo scrapea el portal de información de medicamentos de MedlinePlus 
en su versión en inglés. Utiliza un enfoque basado en índices alfabéticos
(`drug_Aa.html`, `drug_Ba.html`, etc.) para recorrer todas las fichas. 
El contenido extraído (título, texto por párrafos) se guarda en archivos 
de texto separados estructurados por letra inicial, y los metadatos se 
consolidan en un archivo `.parquet` empleando `polars`.

Example:
    Ejecución estándar::

        python scraper_MedLinePlus_druginformation_en.py

    Comenzará a iterar todas las letras, generará el txt de cada medicamento
    y un archivo final `output_en.parquet`.

Note:
    Depende de `BeautifulSoup4` para el parseo del DOM, `fitz` importado
    pero no empleado en el loop principal actual, y `polars` para el set de datos.
    Soporta recuperación ante fallos momentáneos a través de `try_pet()`.
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
    """Extrae el identificador base de un medicamento a partir de su URL.

    Toma la parte final de la ruta URL, remueve la extensión HTML/PHP,
    y adicionalmente limpia terminaciones paramétricas como `-es` (si existieran
    anomalías cruzadas, aunque el de inglés no las suela llevar).

    Args:
        url (str): Enlace completo a la ficha técnica del fármaco.

    Returns:
        str: Cadena identificadora unívoca derivada del enlace.
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
    """Obtiene la letra inicial alfabética para ordenar en carpetas.

    Busca el primer carácter del abecedario, quitando tildes y diacríticos,
    ignorando números o símbolos iniciales.

    Args:
        titulo (str): Título oficial del medicamento.

    Returns:
        str: Letra inicial mayúscula (Ej. 'A', 'B') o la cadena "Otros".
    """
    # Elimina tildes y convierte a mayúscula la primera letra alfabética válida
    titulo_normalizado = unicodedata.normalize('NFKD', titulo)
    letras = ''.join(c for c in titulo_normalizado if c.isalpha())
    return letras[0].upper() if letras else "Otros"

def safe_filename(nombre: str) -> str:
    """Convierte un string en un nombre de archivo seguro para SO.

    Sustituye los espacios por guiones bajos y elimina cualquier símbolo 
    que no sea del conjunto alfanumérico, guión o punto.

    Args:
        nombre (str): Nombre crudo base.

    Returns:
        str: Nombre compatible validado.
    """
    # Reemplaza espacios por guiones bajos y elimina caracteres no permitidos
    nombre = nombre.strip().replace(' ', '_')
    return re.sub(r'[^\w\-_.]', '', nombre)


def error_log(error_path: str, search_url: str) -> None:
    """Vuelca información de URLs fallidas en un archivo de retención.

    Args:
        error_path (str): Ruta predefinida para almacenar (sin extensión explícita pre-txt).
        search_url (str): URL involucrada.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def pdf_to_text(pdf_path: str) -> str:
    """Extracto directo de texto de PDF.
    
    Nota: Función importada utilitaria pero no integrada en el loop principal
    ya que los extractos actuales se toman puramente de HTML DOM.

    Args:
        pdf_path (str): Ubicación del PDF potencial.

    Returns:
        str: Contenido concatenado bruto.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def try_pet(search_url: str, error_path: str) -> tuple:
    """Envoltura tolerante a fallos para una solicitud Requests GET HTTP.

    Previene problemas tales como interrupciones cortas de red o Timeouts de la DB
    del backend remoto reintentando progresivamente hasta 5 iteraciones.

    Args:
        search_url (str): Dominio destino.
        error_path (str): Ruta de fallback para registrar fracaso contundente.

    Returns:
        tuple: (response|None, response_find [0 o 1])
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
    """Flujo central de raspado y curación.

    Establece las iniciales pre-mapeadas (`Aa`, `Ba`...) del índice web de 
    MedlinePlus EN. Entra a cada subíndice navegando a las URLs resultantes, 
    extrae sus divisores (`<article>`, `<h123>`, `<p>`), lo consolida localmente y 
    añade la pieza a una lista global empaquetada subsecuentemente en un `parquet`.
    """
    path ="/home/mmg/scripts/scraper/MedlinePlus/drug_information/en"
    docs = path + "/docs/"
    error_path = ""
    abecedario = ['Aa', 'Ba', 'Ca', 'Da', 'Ea', 'Fa', 'Ga', 'Ha', 'Ia', 'Ja', 'Ka', 'La', 'Ma', 'Na', 'Ña', 'Oa', 'Pa', 'Qa', 'Ra', 'Sa', 'Ta', 'Ua', 'Va', 'Wa', 'Xa', 'Ya', 'Za']
    diccionario = []
    base_url = "https://medlineplus.gov/druginfo/"

    for letra in abecedario:
        print(f"Letra: {letra}")
        url = f"https://medlineplus.gov/druginfo/drug_{letra}.html"
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
                enlace_url = urljoin(base_url, enlace)
                print(f"Procesando enlace: {enlace_url}")

                response, response_find = try_pet(enlace_url, error_path)
                if not response_find:
                    continue

                soup_palabra = BeautifulSoup(response.text, 'html.parser')

                # Extraer el título
                titulo_tag = soup_palabra.find('div', class_='page-title')
                titulo = titulo_tag.find('h1').get_text(strip=True) if titulo_tag else 'Sin título'
                print(f"Título: {titulo}")

                # Buscar el contenedor principal
                main_div = soup_palabra.find('article')
                
                textos_extraidos = []
                if main_div:
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
                    "category": "drug_information",
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
