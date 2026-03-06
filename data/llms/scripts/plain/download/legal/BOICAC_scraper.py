"""Recolector de datos web para consultas BOICAC del ICAC.

Este módulo implementa un script que descarga consultas publicadas en
el Boletín Oficial del Instituto de Contabilidad y Auditoría de Cuentas (BOICAC).
Navega por las páginas del listado de consultas y descarga los documentos PDF
correspondientes.

Attributes:
    url_base (str): URL base para las consultas del BOICAC.
    carpeta_descargas (str): Nombre del directorio local para guardar los PDFs.
"""

import requests
from bs4 import BeautifulSoup
import os
import time

def obtener_html(url):
    """Obtiene el contenido HTML de una URL dada.

    Realiza una petición GET a la URL y devuelve el código fuente HTML si la
    respuesta es exitosa. En caso de error de conexión o HTTP, imprime un
    mensaje y devuelve None.

    Args:
        url (str): La URL de la página web a obtener.

    Returns:
        str o None: El contenido HTML de la página, o None si ocurre un error.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error al obtener la página: {e}")
        return None

def obtener_enlaces_pdf(soup):
    """Extrae todos los enlaces a archivos PDF de un objeto BeautifulSoup.

    Busca en el HTML analizado todas las etiquetas de anclaje (<a>) y filtra
    aquellas cuyo atributo 'href' termine en '.pdf' (insensible a mayúsculas).

    Args:
        soup (BeautifulSoup): El objeto BeautifulSoup con el contenido HTML analizado.

    Returns:
        list[str]: Una lista con las URLs relativas o absolutas de los PDFs encontrados.
    """
    enlaces_pdf = []
    for enlace in soup.find_all('a', href=True):
        if enlace['href'].lower().endswith('.pdf'):
            enlaces_pdf.append(enlace['href'])
    return enlaces_pdf

def descargar_pdf(url_pdf, nombre_archivo):
    """Descarga un archivo PDF desde una URL y lo guarda en disco.

    Realiza una petición GET en modo streaming para descargar el archivo por
    bloques (chunks) y lo guarda en la ubicación especificada.

    Args:
        url_pdf (str): La URL directa del documento PDF a descargar.
        nombre_archivo (str): La ruta local (incluyendo nombre de archivo)
            donde se guardará el PDF.

    Returns:
        bool: True si la descarga y escritura fueron exitosas, False si
            ocurrió algún error (ej. error de conexión o HTTP).
    """
    try:
        response = requests.get(url_pdf, stream=True)
        response.raise_for_status()
        with open(nombre_archivo, 'wb') as archivo_pdf:
            for chunk in response.iter_content(chunk_size=8192):
                archivo_pdf.write(chunk)
        print(f"PDF descargado: {nombre_archivo}")
        return True 
    except requests.exceptions.RequestException as e:
        print(f"Error al descargar el PDF: {e}")
        return False 

def obtener_enlace_siguiente(soup):
    """Obtiene la URL de la página siguiente a partir de la paginación.

    Busca en el HTML analizado un enlace de paginación que tenga el atributo
    title='Ir a la página siguiente' y extrae su 'href'.

    Args:
        soup (BeautifulSoup): El objeto BeautifulSoup con el contenido HTML analizado.

    Returns:
        str o None: El atributo 'href' (URL relativa) de la página siguiente,
            o None si no se encuentra dicho enlace.
    """
    enlace_siguiente = soup.find('a', title='Ir a la página siguiente')
    if enlace_siguiente:
        return enlace_siguiente['href']
    return None

url_base = "https://www.icac.gob.es/contabilidad/consultas-boicac" 
carpeta_descargas = "pdfs_descargados2"

if not os.path.exists(carpeta_descargas):
    os.makedirs(carpeta_descargas)

url_actual = url_base
contador_pdf = 1 
while url_actual:
    html = obtener_html(url_actual)
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        enlaces_pdf = obtener_enlaces_pdf(soup)
        for enlace_pdf in enlaces_pdf:
            if not enlace_pdf.startswith('http'):
                url_pdf = url_base + enlace_pdf
            else:
                url_pdf = enlace_pdf
            nombre_archivo_original = os.path.join(carpeta_descargas, enlace_pdf.split('/')[-1])
            if descargar_pdf(url_pdf, nombre_archivo_original): 
                nuevo_nombre_archivo = os.path.join(carpeta_descargas, f"{contador_pdf}.pdf")
                os.rename(nombre_archivo_original, nuevo_nombre_archivo)
                print(f"Archivo renombrado: {nombre_archivo_original} -> {nuevo_nombre_archivo}")
                contador_pdf += 1
            time.sleep(1)
        url_siguiente = obtener_enlace_siguiente(soup)
        if url_siguiente:
            url_actual = url_base + url_siguiente
        else:
            url_actual = None
    else:
        url_actual = None

    if url_actual:
        time.sleep(2)

print("Descarga y renombrado completos.")
