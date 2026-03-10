"""Recolector de documentos PDF relacionados con los PERTEs.

Este script descarga documentos PDF de proyectos estratégicos para la recuperación
y transformación económica (PERTEs) desde la página del Plan de Recuperación del 
Gobierno de España. También busca y procesa enlaces a otros PERTEs en la página.

Aviso: El script desactiva las advertencias de certificados SSL/TLS inseguros
debido a la configuración un tanto laxa del servidor gubernamental.

Attributes:
    url_principal (str): URL de la página principal de los PERTEs.
    directorio_descarga (str): Directorio donde se guardan los PDFs descargados.
    archivo_errores (str): Nombre del archivo para registrar los errores de descarga.
"""

import requests
from bs4 import BeautifulSoup
import os

url_principal = "https://planderecuperacion.gob.es/como-acceder-a-los-fondos/pertes"
directorio_descarga = "pdfs_descargados"
os.makedirs(directorio_descarga, exist_ok=True)
archivo_errores = "errores_descarga.txt"

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

def descargar_pdf(url_pdf, nombre_archivo):
    """Descarga un archivo PDF y registra los errores si falla.

    Realiza una solicitud para descargar el archivo especificado. Si falla debido
    a un error de red o un código de estado no exitoso (por ejemplo, 404),
    registra el error en un archivo de texto definido globalmente.

    Args:
        url_pdf (str): La URL desde donde se descargará el documento PDF.
        nombre_archivo (str): La ruta local donde se guardará el PDF descargado.
    """
    try:
        response = requests.get(url_pdf, stream=True, verify=False)
        if response.status_code == 404:
            error_msg = f"❌ Error 404 - No encontrado: {url_pdf}"
        elif response.status_code != 200:
            error_msg = f"❌ Error HTTP {response.status_code}: {url_pdf}"
        else:
            with open(nombre_archivo, 'wb') as archivo:
                for chunk in response.iter_content(chunk_size=8192):
                    archivo.write(chunk)
            print(f"✅ Descargado: {nombre_archivo}")
            return
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Error SSL o de conexión: {url_pdf}"

    print(error_msg)
    with open(archivo_errores, 'a', encoding='utf-8') as f:
        f.write(f"{error_msg}\n")

def obtener_enlaces_pdf(url_pagina_perte):
    """Obtiene y descarga todos los PDFs enlazados en una página de PERTE.

    Accede a la URL proporcionada, busca todos los enlaces que terminen en '.pdf',
    construye las URLs absolutas si son relativas, y llama a 'descargar_pdf' para
    procesar la descarga para cada documento encontrado.

    Args:
        url_pagina_perte (str): La URL de la página del PERTE en la que operar.

    Returns:
        list: Siempre devuelve una lista vacía de acuerdo a la implementación actual.
    """
    try:
        response = requests.get(url_pagina_perte, verify=False)
        if response.status_code != 200:
            print(f"❌ Error al acceder a {url_pagina_perte}: {response.status_code}")
            with open(archivo_errores, 'a', encoding='utf-8') as f:
                f.write(f"❌ Error al acceder a {url_pagina_perte}: {response.status_code}\n")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                if not href.startswith(('http://', 'https://')):
                    href = url_pagina_perte.split('/')[0] + '//' + url_pagina_perte.split('/')[2] + href
                nombre_archivo = os.path.join(directorio_descarga, href.split('/')[-1])
                descargar_pdf(href, nombre_archivo)
                print(f"✅ PDF encontrado y descargado en la página {url_pagina_perte}: {href}")
        return []
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Error al acceder a {url_pagina_perte}: {e}"
        print(error_msg)
        with open(archivo_errores, 'a', encoding='utf-8') as f:
            f.write(f"{error_msg}\n")
        return []

def obtener_enlaces_perte(url_principal):
    """Extrae enlaces a las páginas individuales de diferentes PERTEs.

    Busca todos los enlaces en la página principal cuyo atributo 'href' contenga
    la palabra 'perte'. Devuelve una lista de URLs absolutas únicas de los PERTEs.

    Args:
        url_principal (str): La URL de la página principal de PERTEs.

    Returns:
        list[str]: Una lista de URLs absolutas únicas hacia las páginas individuales
            de cada PERTE encontrado. Devuelve lista vacía en caso de error HTTP/Red.
    """
    try:
        response = requests.get(url_principal, verify=False)
        if response.status_code != 200:
            error_msg = f"❌ Error al acceder a {url_principal}: {response.status_code}"
            print(error_msg)
            with open(archivo_errores, 'a', encoding='utf-8') as f:
                f.write(f"{error_msg}\n")
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
        enlaces_perte = []
        for link in soup.find_all('a', href=True):
            if 'perte' in link['href'].lower():
                href = link['href']
                if not href.startswith(('http://', 'https://')):
                    enlace_absoluto = url_principal.split('/')[0] + '//' + url_principal.split('/')[2] + href
                    enlaces_perte.append(enlace_absoluto)
                else:
                    enlaces_perte.append(href)
        return list(set(enlaces_perte))
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Error al acceder a {url_principal}: {e}"
        print(error_msg)
        with open(archivo_errores, 'a', encoding='utf-8') as f:
            f.write(f"{error_msg}\n")
        return []

def buscar_y_descargar_pdfs(url_pagina):
    """Busca enlaces PDF en una página general y los descarga.

    Abre una página web, extrae los enlaces que terminan en '.pdf' y procede a 
    descargarlos localmente. Similar a 'obtener_enlaces_pdf' pero devuelve un 
    booleano indicando el éxito de la carga inicial de la página.

    Args:
        url_pagina (str): La URL de la página web en la que se buscarán los PDFs.

    Returns:
        bool: True si se pudo acceder a la página (status 200), False en caso 
            contrario o error de petición.
    """
    try:
        response = requests.get(url_pagina, verify=False)
        if response.status_code != 200:
            print(f"❌ Error al acceder a {url_pagina}: {response.status_code}")
            with open(archivo_errores, 'a', encoding='utf-8') as f:
                f.write(f"❌ Error al acceder a {url_pagina}: {response.status_code}\n")
            return False
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                if not href.startswith(('http://', 'https://')):
                    href = url_pagina.split('/')[0] + '//' + url_pagina.split('/')[2] + href
                nombre_archivo = os.path.join(directorio_descarga, href.split('/')[-1])
                descargar_pdf(href, nombre_archivo)
        return True
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Error al acceder a {url_pagina}: {e}"
        print(error_msg)
        with open(archivo_errores, 'a', encoding='utf-8') as f:
            f.write(f"{error_msg}\n")
        return False

if __name__ == "__main__":
    with open(archivo_errores, 'w', encoding='utf-8') as f:
        f.truncate()  # Elimina el contenido del archivo antes de escribir nuevos errores
    if buscar_y_descargar_pdfs(url_principal):
        print(f"✅ PDFs encontrados y descargados directamente desde la página principal: {url_principal}")
    enlaces_perte = obtener_enlaces_perte(url_principal)
    if enlaces_perte:
        print("Enlaces a las páginas de los PERTE encontrados:")
        for enlace_perte in enlaces_perte:
            print(f"- {enlace_perte}")
            obtener_enlaces_pdf(enlace_perte)
            print("  Enlaces PDF encontrados y descargados.")
    else:
        print("No se encontraron enlaces a páginas de PERTE en la página principal.")
