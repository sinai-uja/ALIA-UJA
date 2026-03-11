"""Recolector de consultas del BOICAC (Boletin del ICAC).

Este módulo extrae las consultas contables publicadas en el Boletin
Oficial del Instituto de Contabilidad y Auditoría de Cuentas (BOICAC),
descarga sus PDFs y serializa los metadatos en un archivo Parquet.

El proceso pagina el listado de consultas del portal web del ICAC,
accede a cada consulta individual para extraer su título, número
de BOICAC, descripción y respuesta publicada, descarga el PDF
correspondiente con PyMuPDF y acumula todos los registros en un
DataFrame de polars.

Example:
    Ejecución básica::

        python scraper_BOICAC.py

    Esto paginará todas las consultas publicadas en el BOICAC y
    generará el archivo ``output.parquet`` en la ruta configurada.

Note:
    Los datos son de acceso público a través del portal del ICAC.
    URL: https://www.icac.gob.es/contabilidad/consultas-boicac
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
from pathlib import Path
from requests.compat import urljoin
import unicodedata


# Rutas relativas al directorio donde se ejecuta el script
BASE_DIR = Path(__file__).parent / "BOICAC"
DOCS_DIR = BASE_DIR / "docs"
ERROR_PATH = BASE_DIR / "errors"


def safe_filename(nombre: str) -> str:
    """Convierte un string en un nombre de archivo seguro.

    Elimina caracteres no válidos para nombres de archivo, reemplaza
    espacios por guiones bajos y elimina el punto final si existe.

    Args:
        nombre: Cadena original a sanear.

    Returns:
        Nombre de archivo seguro y compatible con el sistema de ficheros.
    """
    nombre = nombre.strip().replace(' ', '_')
    nombre = re.sub(r'[^\w\-_.]', '', nombre)
    if nombre.endswith('.'):
        nombre = nombre[:-1]
    return nombre

def error_log(error_path: Path, search_url: str) -> None:
    """Registra una URL fallida en el fichero de errores.

    Args:
        error_path: Ruta base del fichero de errores (sin extensión).
        search_url: URL que no pudo ser accedida correctamente.
    """
    try:
        with open(f"{error_path}.txt", "a", encoding="utf-8") as file:
            file.write(search_url + "\n")
    except Exception as e:
        print(f"Error al escribir en el archivo de errores: {e}")

def pdf_to_text(pdf_path: Path) -> str:
    """Extrae el texto completo de un archivo PDF.

    Abre el PDF con PyMuPDF e itera sobre todas sus páginas
    concatenando el texto plano extraído de cada una.

    Args:
        pdf_path: Ruta al archivo PDF del que extraer el texto.

    Returns:
        String con el texto completo del PDF.
    """
    doc = fitz.open(pdf_path)
    text_full = ""
    for num_pag in range(doc.page_count):
        pag = doc.load_page(num_pag)
        text_full += pag.get_text()
    return text_full

def try_pet(search_url: str, error_path: Path) -> tuple:
    """Realiza una petición HTTP con reintentos ante fallos.

    Intenta acceder a la URL dada y, si la respuesta no es exitosa,
    reintenta hasta 5 veces con espera incremental. Los fallos
    definitivos se registran en el fichero de errores.

    Args:
        search_url: URL a la que realizar la petición GET.
        error_path: Ruta base del fichero de errores (sin extensión).

    Returns:
        Tupla ``(response, response_find)`` donde ``response`` es el
        objeto Response de requests (o None si falló) y
        ``response_find`` es 1 si se obtuvo respuesta o 0 si no.
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
    """Función principal: pagina el BOICAC y guarda las consultas.

    Itera por todas las páginas del listado de consultas del BOICAC,
    accede a cada consulta para extraer su título, número, descripción
    y respuesta, descarga el PDF y acumula los registros en un
    archivo Parquet final.

    Raises:
        Exception: Si se produce un error al guardar el Parquet o al
            procesar una consulta individual.
    """
    # Crear directorios si no existen
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    base_url = "https://www.icac.gob.es"
    diccionario = []

    id_txt = 0
    contador = 0
    Finished = False

    while not Finished:
        print(f"Accediendo a la pagina: {contador}")
        url = f"https://www.icac.gob.es/contabilidad/consultas-boicac?combine=&combine_1=&page={contador}"
        response, response_find = try_pet(url, ERROR_PATH)
        if not response_find:
            continue
        soup = BeautifulSoup(response.text, 'html.parser')
        try:
            div = soup.find('div', class_='item-list')

            if not div:
                Finished = True

            ul_index = div.find('ul')

            enlaces_li = [li.a['href'] for li in ul_index.find_all('li') if li.a]
            print(f"enlaces: {enlaces_li}")
            print(len(enlaces_li))

            for enlace in enlaces_li:
                time.sleep(1)
                enlace_url = base_url + enlace
                response, response_find = try_pet(enlace_url, ERROR_PATH)
                print(f"Accediendo a: {enlace_url}")
                if not response_find:
                    continue
                soup_articulo = BeautifulSoup(response.text, 'html.parser')

                titulo = soup_articulo.find('span', class_='field field--name-title field--type-string field--label-hidden').get_text(strip=True)

                num_boicac = ""
                for li in soup_articulo.find_all('li'):
                    if 'Número BOICAC' in li.text:
                        texto = li.get_text(separator=" ", strip=True)
                        num_boicac = texto.replace("Número BOICAC:", "").replace("Número BOICAC", "").replace(":", "").strip()
                        num_boicac = num_boicac.replace("/", "-")

                # Extraer la descripción de la consulta
                desc_consulta = ""
                desc_tag = soup_articulo.find('label', string="Descripción de la consulta:")
                if desc_tag:
                    p_tag = desc_tag.find_parent('li').find('p')
                    if p_tag:
                        desc_consulta = p_tag.get_text(strip=True)

                # Extraer la respuesta publicada
                respuesta = ""
                resp_tag = soup_articulo.find('label', string="Respuesta publicada:")
                if resp_tag:
                    p_tag = resp_tag.find_parent('li').find('p')
                    if p_tag:
                        respuesta = p_tag.get_text(" ", strip=True)

                enlace_descarga = soup_articulo.find('span', id='consultas-pdf').find('a')['href']

                pdf_response, pdf_response_find = try_pet(enlace_descarga, ERROR_PATH)
                if pdf_response_find == 0:
                    print(f"No se ha podido acceder a {enlace_descarga}")

                else:
                    if pdf_response.status_code == 200:

                        print(f"Accediendo a {enlace_descarga}")
                        # Crear carpeta por página
                        pagina_folder = DOCS_DIR / f"pagina_{contador}"
                        pagina_folder.mkdir(parents=True, exist_ok=True)

                        # Definir ruta completa del PDF
                        pdf_path = pagina_folder / f"{num_boicac}.pdf"

                        print(f"Guardando archivo en {pdf_path}")
                        if pdf_path.exists():
                            print(f"El archivo {pdf_path} ya existe")
                            continue

                        with open(pdf_path, "wb") as file:
                            file.write(pdf_response.content)

                        text = pdf_to_text(pdf_path)
                        diccionario.append({"id": id_txt, "text": text, "num_boicac": num_boicac, "url": enlace_descarga, "descripcion": desc_consulta, "respuesta": respuesta, "titulo": titulo})
                        print(f"[ID {id_txt}] Título: {titulo}\nNúmero BOICAC: {num_boicac}\nDescripción: {desc_consulta}\nRespuesta: {respuesta[:15]}...\nTexto extraído: {text[:15]}...\nURL: {enlace_descarga}\n{'-'*80}")
                        id_txt += 1

        except Exception as e:
            print(f"Error al guardar parquet: {e}")

        contador += 1

    df = pl.DataFrame(diccionario)
    df.write_parquet(BASE_DIR / "output.parquet")


if __name__ == "__main__":
    main()