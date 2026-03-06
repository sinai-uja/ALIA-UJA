"""Scraper de Genética de MedlinePlus (ES).

Este script explora el dominio de información genética (`/spanish/genetica/`) naturalizado
en español dentro de la plataforma MedlinePlus. Rastrea la taxonomía pre-configurada 
dentro del apartado `understanding_genetics`, recolecta cada listado o agrupación 
de síndromes / explicaciones, curando los textos descriptivos (`h`, `p`, `li`) en archivos 
inmediatos e indexando su ubicación y contenido en un registro unificado Polars `.parquet`.

Example:
    Flujo de ejecución principal::

        python scraper_MedLinePlus_genetic_es.py

    Levanta el flujo de petición en la página raíz, desglosa por categorías genéticas
    y almacena iterativamente docenas de registros de texto en `docs/` catalogados.

Note:
    Su estructura diverge de las enciclopedias simples usando IDs secuenciales manuales 
    (`contador = 300`) en su formato DataFrame, albergando la misma recolección tolerante 
    a las fallas originaria del resto del repositorio web NIH.
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
    """Extrae la clave única de identificación a partir de la URL de un recurso.

    Args:
        url (str): Enlace directo a la patología.

    Returns:
        str: Cadena identificadora unívoca limpia de finalizaciones `-es`.
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
    """Obtiene la letra inicial alfabética para ordenar eliminando tildes.

    Args:
        titulo (str): Título oficial.

    Returns:
        str: Letra capitular normalizada, u 'Otros'.
    """
    # Elimina tildes y convierte a mayúscula la primera letra alfabética válida
    titulo_normalizado = unicodedata.normalize('NFKD', titulo)
    letras = ''.join(c for c in titulo_normalizado if c.isalpha())
    return letras[0].upper() if letras else "Otros"

def safe_filename(nombre: str) -> str:
    """Sanea una frase para uso lícito de archivo en el Operating System.

    Args:
        nombre (str): Cadena en texto.

    Returns:
        str: Fichero seguro y amoldado sin tabulares o saltos.
    """
    # Reemplaza espacios por guiones bajos y elimina caracteres no permitidos
    nombre = nombre.strip().replace(' ', '_')
    return re.sub(r'[^\w\-_.]', '', nombre)


def error_log(error_path: str, search_url: str) -> None:
    """Conserva el historial de URLs inaccesibles prolongadamente.

    Args:
        error_path (str): Salida del txt en directorio raíz.
        search_url (str): Dominio inalcanzable.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def pdf_to_text(pdf_path: str) -> str:
    """Lector complementario pre-configurado para documentos PDF estáticos.
    
    Args:
        pdf_path (str): Fichero físico local.

    Returns:
        str: Extraído continuo sin formato.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def try_pet(search_url: str, error_path: str) -> tuple:
    """Lanzador y regulador de Request GET para solventar demoras de conexión.

    Args:
        search_url (str): Blanco web requerido.
        error_path (str): Referencia txt si la conexión desiste irresolublemente.

    Returns:
        tuple: Objeto requests Response, sumado a un binario indicativo local (0 o 1).
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
    """Bloque de raspado principal de la Genética Médica.

    Localiza la id 'understanding_genetics' de MedlinePlus. De su árbol recaba enlaces
    e insertándose localmente sobre ellos destripa los subtítulos de las anomalías médicas 
    guardando el documento HTML unificado en variables `txt` locales y un gran DataFrame
    secuencial de contador ascendiente.
    """
    path ="/home/mmg/scripts/scraper/MedlinePlus/genetic/es"
    docs = path + "/docs/"
    error_path = ""
    diccionario = []
    url = "https://medlineplus.gov/spanish/genetica/"
    contador =300

    response, response_find = try_pet(url, error_path)

    soup = BeautifulSoup(response.text, 'html.parser')
    try:

        section = soup.find("section", id="understanding_genetics")
        # Extraer títulos (texto de los <a> dentro de <strong>)
        titulos = [a.get_text(strip=True) for a in section.select("p strong a")]

        # Extraer enlaces (atributo href de los <a>)
        enlaces = [a["href"] for a in section.select("p strong a")]


        for i, enlace_pagina in enumerate(enlaces):
            response, response_find = try_pet(enlace_pagina, error_path)
            if not response_find:
                continue
            html_especifico = BeautifulSoup(response.text, 'html.parser')
            print(f"Estamos dentro del enlace: {enlace_pagina}")
            
            ul_index = html_especifico.find("div", class_="mp-content").find("ul")

            # Extraer textos y enlaces juntos
            textos_li = []
            enlaces_li = []

            for li in ul_index.find_all("li"):
                if li.a:  # seguridad por si algún <li> no tiene <a>
                    textos_li.append(li.a.get_text(strip=True))
                    enlaces_li.append(li.a["href"])

            print(textos_li)
            print(enlaces_li)

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
                    letra = titulos[i]

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
                    "category": "genetic",
                    "id": str(contador)
                    })

                    print(
                        "Título:", titulo,
                        "| Enlace:", enlace_url,
                        "| Letra:", letra,
                        "| Texto:", #textos_extraidos,
                        "| ID:", contador
                    )
                    contador+=1

                    print(f"Texto guardado en el archivo: {ruta_completa}")
                else:
                    print("No se encontró el div con clase 'main' o 'main-single'")
    except Exception as e:
        print(f"Error al guardar parquet: {e}")

    df = pl.DataFrame(diccionario)
    df.write_parquet(f"{path}/output_es.parquet")



if __name__ == "__main__":
    main()
