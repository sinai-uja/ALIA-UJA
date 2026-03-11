"""Recolector de producción científica de AETSA.

Este módulo implementa un scraper que recolecta los documentos de
producción científica publicados por la Agencia de Evaluación de
Tecnologías Sanitarias de Andalucía (AETSA) en su portal web. Los
documentos se descargan en formato PDF y se extrae su texto con
PyMuPDF, generando un archivo Parquet con todos los metadatos.

El proceso usa Selenium para navegar las páginas de resultados
(que se renderizan con JavaScript) y requests para descargar los
PDFs de cada publicación.

Example:
    Ejecución básica::

        python scraper_Prod_Cient_AETSA.py

    Esto abrirá una ventana de Chrome, paginará por todos los
    resultados de producción científica de AETSA y generará
    ``output.parquet`` en la ruta configurada.

Note:
    Los datos son de acceso público a través del portal de AETSA.
    URL: https://www.aetsa.org/produccion-cientifica
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
import urllib.parse
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# Rutas relativas al directorio donde se ejecuta el script
BASE_DIR = Path(__file__).parent / "aetsa_produccion_cientifica"
DOCS_DIR = BASE_DIR / "docs"
ERROR_PATH = BASE_DIR / "errors"


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



def cargar_pagina(driver, pagina_actual: int):
    """Espera a que la página de resultados esté cargada y la parsea.

    Utiliza WebDriverWait para esperar a que aparezcan los elementos
    de resultado (``ul.sf-result > li``) antes de parsear el HTML.

    Args:
        driver: Instancia del WebDriver de Selenium.
        pagina_actual: Número de página actual (usado en mensajes de error).

    Returns:
        Objeto BeautifulSoup con el HTML de la página, o None si falla
        la carga.
    """
    try:
        # Esperamos a que aparezcan resultados
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ul.sf-result > li"))
        )
        time.sleep(1)  # pequeño delay para estabilidad
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception as e:
        print(f"No se pudo cargar la página {pagina_actual}: {e}")
        return None
    
def click_en_pagina(driver, numero_pagina: int) -> bool:
    """Hace click en el botón de navegación a una página concreta.

    Usa WebDriverWait para esperar a que el botón de paginación sea
    interactuable antes de hacer click.

    Args:
        driver: Instancia del WebDriver de Selenium.
        numero_pagina: Número de la página a la que navegar.

    Returns:
        True si el click se realizó correctamente, False en caso contrario.
    """
    try:
        boton = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, f"//span[@class='sf-nav-click' and @data-href='{numero_pagina}']"))
        )
        boton.click()
        time.sleep(2)  # Esperar a que cargue la nueva página
        return True
    except Exception as e:
        print(f"No se pudo hacer click en la página {numero_pagina}: {e}")
        return False

def main() -> None:
    """Función principal: navega el catálogo de AETSA y guarda los datos.

    Abre el portal de producción científica de AETSA con Selenium,
    pagina por todos los resultados, descarga los PDFs de cada
    publicación y extrae su texto. Al finalizar guarda todos los
    registros en un archivo Parquet.

    Raises:
        Exception: Si se produce un error no controlado al procesar
            una página o al guardar el Parquet.
    """

    # Crear directorios si no existen
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    options = Options()
    #options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    driver.get("https://www.aetsa.org/produccion-cientifica")

    contador_pagina = 1
    diccionario = []

    finished = False
    while not finished:
        
        soup = cargar_pagina(driver, contador_pagina)
        if soup is None:
            finished = True
        
        try:
            ul = soup.find('ul', class_='sf-result')
            lista_enlaces = ul.find_all('li', recursive=False)

            if not lista_enlaces:  # Si la lista está vacía
                finished = True
                continue

            for articulo in lista_enlaces:

                # Título y enlace al artículo
                a_tag = articulo.find('h4').find('a')
                enlace_articulo = a_tag['href']
                id_publicacion = articulo.get("data-postid")

                # 1. Publicado
                publicado = articulo.find('b', string=lambda x: x and "Publicado:" in x)
                fecha_publicacion = publicado.get_text(strip=True).replace('Publicado:', '').strip() if publicado else None

                # 2. Línea de producción
                linea = articulo.find('b', string=lambda x: x and "Línea de Producción:" in x)
                linea_texto = linea.find_next_sibling(text=True).strip() if linea else None

                # 3. Tipo de tecnología
                tipo_tecnologia = articulo.find('b', string=lambda x: x and "Tipo de Tecnología:" in x)
                tipo_texto = [li.get_text(strip=True) for li in tipo_tecnologia.find_next('ul').find_all('li')] if tipo_tecnologia else []

                # 4. Áreas de conocimiento
                areas_conocimiento = articulo.find('b', string=lambda x: x and "Áreas de Conocimiento:" in x)
                areas_texto = [li.get_text(strip=True) for li in areas_conocimiento.find_next('ul').find_all('li')] if areas_conocimiento else []

                # 5. Descripción
                descripcion_tag = articulo.find('b', string=lambda x: x and "Descripción:" in x)
                descripcion = descripcion_tag.find_next('i').get_text(strip=True) if descripcion_tag else None


                print(f"Accediendo al libro: {enlace_articulo}")

                response_doc, response_find_doc = try_pet(enlace_articulo, ERROR_PATH)

                if response_find_doc == 0:
                    print(f"No se ha podido acceder a {enlace_articulo}")

                else:
                    if response_doc.status_code == 404:
                        print(f"No se han encontrado documentos")
                        continue
                    else:
                        if response_doc.status_code == 200:

                            print(f"Accedido")
                            # Parse the HTML content
                            soup_doc = BeautifulSoup(response_doc.text, 'html.parser')

                            titulo = soup_doc.find("h1", class_="h2-size entry-title").text.strip()
                            print(f"Título del libro: {titulo}")

                            a_tag_doc = soup_doc.find("a", class_="wpfb-dlbtn")

                            if a_tag_doc and a_tag_doc.has_attr('href'):
                                href = a_tag_doc['href']
                                print(f"Accediendo a {href}")
                                pdf_response, pdf_response_find = try_pet(href, ERROR_PATH)

                                if pdf_response_find == 0:
                                    try:
                                        missing_path = BASE_DIR / "missing.txt"
                                        with open(missing_path, "a", encoding="utf-8") as file:
                                            file.write(f"{href}" + "\n")
                                    except Exception as e:
                                        print(f"Error al escribir en el archivo de errores: {e}")
                                    print(f"No se han encontrado documentos")
                                    continue
                                else:
                                    pdf_path = DOCS_DIR / f"{id_publicacion}.pdf"

                                    print(f"Guardando en {pdf_path}")
                                    if pdf_path.exists():
                                        print(f"El archivo {pdf_path} ya existe")
                                        continue
                                    with open(pdf_path, "wb") as file:
                                        file.write(pdf_response.content)
                                    try:
                                        text = pdf_to_text(pdf_path)
                                    except Exception as e:
                                        print(f"Error al convertir el PDF a texto: {e}")
                                        error_log(ERROR_PATH, href)
                                        continue
                                    try:
                                        diccionario.append({"id": id_publicacion, "txt": text, "url": enlace_articulo, "fecha": fecha_publicacion, "titulo": titulo, "area": areas_texto, "linea_produccion": linea_texto, "tipo_tecnologia": tipo_texto, "descripcion": descripcion})
                                        print({
                                            "id": id_publicacion,
                                            "txt": "TEXTO",
                                            "url": enlace_articulo,
                                            "fecha": fecha_publicacion,
                                            "titulo": titulo,
                                            "area": areas_texto,
                                            "linea_produccion": linea_texto,
                                            "tipo_tecnologia": tipo_texto,
                                            "descripcion": "Descripcion"
                                        })
                                            
                                    except Exception as e:
                                        print(f"Error al añadir el texto a la lista: {e}")
                                        continue
        except Exception as e:
            print(f"Error al extraer los elementos de la página: {e}")
            continue
        
        contador_pagina += 1
        if not click_en_pagina(driver, contador_pagina):
            finished = True
            break

                        
    try:
        df = pl.DataFrame(diccionario)
        output_path = BASE_DIR / "output.parquet"
        df.write_parquet(output_path)
        print("Parquet exitosamente guardado")
        
    except Exception as e:
        print(f"Error al guardar el parquet: {e}")
        
    driver.quit()



if __name__ == "__main__":
    main()
