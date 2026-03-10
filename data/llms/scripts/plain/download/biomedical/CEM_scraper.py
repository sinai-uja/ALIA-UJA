"""Scraper de publicaciones del Centro de Estudios de Madrid (CEM).

Este módulo implementa un web scraper que navega por la página web
de publicaciones del CEM y descarga los archivos PDF de forma
automatizada. Maneja paginación y registra errores en un log.

Example:
    Ejecución básica::

        python CEM_scraper.py

    Navegará por el catálogo de publicaciones y descargará los PDFs
    en el directorio especificado.

Note:
    Los PDFs son descargados de manera secuencial.
"""

import requests
from bs4 import BeautifulSoup
import os

def registrar_error(url: str, error: str) -> None:
    """Registra un error ocurrido durante la ejecución en un archivo.

    Args:
        url (str): La URL que produjo el error.
        error (str): El mensaje o detalle del error.
    """
    with open("errores.txt", "a", encoding="utf-8") as f:
        f.write(f"{url} --> {error}\n")

def descargar_pdf(url_pdf: str, nombre_archivo: str) -> None:
    """Descarga un archivo PDF desde una URL dada.

    Realiza una petición HTTP en modo bloque largo (stream) para no
    saturar la memoria descargando grandes archivos.

    Args:
        url_pdf (str): URL directa del archivo PDF.
        nombre_archivo (str): Ruta y nombre donde se guardará localmente.
        
    Raises:
        requests.exceptions.RequestException: Si existe un problema
            de conexión o estado HTTP.
    """
    try:
        response = requests.get(url_pdf, stream=True)
        response.raise_for_status()
        with open(nombre_archivo, 'wb') as pdf_file:
            for chunk in response.iter_content(chunk_size=8192):
                pdf_file.write(chunk)
        print(f"Descargado: {nombre_archivo}")
    except requests.exceptions.RequestException as e:
        print(f"Error al descargar {url_pdf}: {e}")
        registrar_error(url_pdf, f"Error al descargar PDF: {e}")
    except Exception as e:
        print(f"Error al guardar {nombre_archivo}: {e}")
        registrar_error(url_pdf, f"Error al guardar PDF: {e}")

def obtener_enlaces_en_contenedor(soup: BeautifulSoup) -> list:
    """Obtiene los enlaces <a> dentro de un contenedor web específico.

    Busca dentro del div con id `views-bootstrap-publicaciones-publicaciones-listado--2`.

    Args:
        soup (BeautifulSoup): Objeto BeautifulSoup de la página parseada.

    Returns:
        list: Una lista con los valores de los atributos href (str) 
        de los enlaces encontrados.
    """
    contenedor = soup.find('div', id='views-bootstrap-publicaciones-publicaciones-listado--2')
    if contenedor:
        enlaces = contenedor.find_all('a', href=True)
        return [enlace['href'] for enlace in enlaces]
    return []

def obtener_enlaces_fuera_footer(soup: BeautifulSoup) -> list:
    """Obtiene enlaces <a> que NO se encuentran en el footer de la página.

    Args:
        soup (BeautifulSoup): Objeto BeautifulSoup de la página parseada.

    Returns:
        list: Una lista con los atributos href de los enlaces válidos.
    """
    enlaces_todos = soup.find_all('a', href=True)
    footer = soup.find('div', class_='footer-wrapper')
    enlaces_footer = footer.find_all('a', href=True) if footer else []

    # Crear conjunto de enlaces del footer para excluirlos
    hrefs_footer = set(a['href'] for a in enlaces_footer)
    enlaces_validos = [a['href'] for a in enlaces_todos if a['href'] not in hrefs_footer]

    return enlaces_validos

def es_pdf(url: str) -> bool:
    """Verifica si una URL termina en .pdf (ignorando mayúsculas/minúsculas).

    Args:
        url (str): URL a evaluar.

    Returns:
        bool: True si la URL apunta a un PDF, False en caso contrario.
    """
    return url.lower().endswith('.pdf')

def obtener_siguiente_pagina(soup: BeautifulSoup, url_base: str) -> str | None:
    """Busca y extrae el enlace de la página siguiente en la paginación.

    Args:
        soup (BeautifulSoup): Objeto BeautifulSoup de la página parseada.
        url_base (str): URL base que se usará para resolver rutas relativas.

    Returns:
        str | None: URL completa de la siguiente página, o None si no existe.
    """
    siguiente = soup.find('a', {'rel': 'next', 'class': 'page-link'})
    if siguiente and 'href' in siguiente.attrs:
        return requests.compat.urljoin(url_base, siguiente['href'])
    return None

def scraper_pagina(url_pagina_principal: str, directorio_descarga: str = "pdfs") -> None:
    """Gestiona el flujo principal del scraper para descargar PDFs del CEM.

    Recorre la página principal y sus siguientes páginas aplicando la
    lógica pertinente para identificar y descargar los archivos PDF,
    creando la carpeta de destino si fuese necesario.

    Args:
        url_pagina_principal (str): URL inicial para empezar el scraping.
        directorio_descarga (str): Nombre del directorio de salida. 
            Por defecto es "pdfs".
            
    Raises:
        requests.exceptions.RequestException: Excepción mostrada pero
            manejada en caso de errores en las peticiones web.
    """
    if not os.path.exists(directorio_descarga):
        os.makedirs(directorio_descarga)

    urls_visitadas = set()
    urls_pendientes = [url_pagina_principal]

    while urls_pendientes:
        url_actual = urls_pendientes.pop(0)
        if url_actual in urls_visitadas:
            continue
        urls_visitadas.add(url_actual)
        print(f"Scrapeando: {url_actual}")

        try:
            response = requests.get(url_actual)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # Si es la página principal, usar el contenedor específico
            if url_actual == url_pagina_principal:
                enlaces = obtener_enlaces_en_contenedor(soup)
            else:
                enlaces = obtener_enlaces_fuera_footer(soup)

            for enlace in enlaces:
                url_completa = requests.compat.urljoin(url_actual, enlace)
                if es_pdf(url_completa):
                    nombre_archivo = os.path.join(directorio_descarga, url_completa.split('/')[-1])
                    descargar_pdf(url_completa, nombre_archivo)
                elif url_completa not in urls_visitadas and url_completa.startswith(url_pagina_principal):
                    urls_pendientes.append(url_completa)

            # Solo buscar "siguiente página" desde la principal
            if url_actual == url_pagina_principal:
                url_siguiente = obtener_siguiente_pagina(soup, url_actual)
                if url_siguiente and url_siguiente not in urls_visitadas:
                    urls_pendientes.append(url_siguiente)

        except requests.exceptions.RequestException as e:
            print(f"Error al acceder a {url_actual}: {e}")
            registrar_error(url_actual, f"Error al acceder a la página: {e}")
        except Exception as e:
            print(f"Error al procesar {url_actual}: {e}")
            registrar_error(url_actual, f"Error inesperado: {e}")

if __name__ == "__main__":
    url_principal = "https://www.cem.es/es/divulgacion/publicaciones"
    directorio_descarga_pdfs = "pdfs_descargados"

    scraper_pagina(url_principal, directorio_descarga_pdfs)
    print("Scraping completado.")
