"""Scraper de la Revista Española de Salud Pública (RESP).

Este script actúa como una araña simple utilizando Requests y BeautifulSoup4 para minar 
los archivos PDFs de las publicaciones en el sistema OJS (Open Journal Systems) de 
Sanidad (`https://ojs.sanidad.gob.es/index.php/resp/issue/archive`).
Se encarga de navegar el archivo enumerado, buscar los nodos que alberguen las casillas 
`.obj_galley_link` (descargas de PDF) resolviendo la descarga binaria hacia un
directorio específico montado en el Escritorio local del usuario.

Example:
    Uso estándar desde terminal::

        python scrapy_revista_Española_de_salud_publica.py

    Iniciará la traza desde el `url_principal`, iterando y almacenando 
    la colección completa de la revista con outputs tipo 
    `[1/130] Archivo PDF descargado: C:/Users/TuUsuario/Desktop/pdf/file.pdf`.

Note:
    A diferencia de otros scrapers estructurados en Parquet, este es puro 
    descargador binario (File Downloader). Emplea `headers` falsificadas para 
    eludir bloqueos básicos de OJS.
"""

import requests
import os
from bs4 import BeautifulSoup

url_principal = 'https://ojs.sanidad.gob.es/index.php/resp/issue/archive'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0 Safari/537.36'
}

def revisar_enlace(href: str) -> list | None:
    """Inspecciona un enlace individual de publicación buscando recursos PDF adjuntos.

    Navega dentro de un Item del archivo y extrae todos los identificadores HTML 
    que correspondan al link de la galera (`galley`) tipo PDF.

    Args:
        href (str): Enlace a la página del artículo o volumen del OJS.

    Returns:
        list | None: Lista de enlaces a las pantallas de visualización del PDF, 
        o `None` si la lectura falla o no hay adjuntos con la clase correspondiente.
    """
    try:
        response = requests.get(href, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        galley_links = soup.find_all('a', class_='obj_galley_link pdf')
        return [link['href'] for link in galley_links] if galley_links else None
    except requests.RequestException as e:
        print(f'Error al conectarse al enlace {href}: {e}')
        return None

def descargar_pdf(url_pdf: str, carpeta_destino: str, contador_actual: int, total_pdf_encontrados: int) -> bool:
    """Descarga e inscribe en disco físico un PDF desde su URL de visualización.

    Se conecta a la vista `view/download`, busca el tag de descarga final purificado 
    (`.download`) y extrae el stream para grabarlo con el trozo final de la URL como título.

    Args:
        url_pdf (str): Enlace inicial al renderizador temporal del visor PDF de OJS.
        carpeta_destino (str): Directorio raíz del sistema donde acomodar los binarios.
        contador_actual (int): Número actual en la iteración principal (para logging terminal).
        total_pdf_encontrados (int): Total numérico en la cola (para logging terminal).

    Returns:
        bool: `True` si el binario se graba exitosamente y `False` si hubiese 
        ausencia del hipertexto de descarga o fallos 4xx/5xx en la bajada.
    """
    try:
        response = requests.get(url_pdf, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        download_link = soup.find('a', class_='download')

        if download_link and download_link.get('href'):
            pdf_url = download_link['href']
            pdf_nombre = pdf_url.split("/")[-1]
            if not pdf_nombre.endswith('.pdf'):
                pdf_nombre += '.pdf'
            pdf_ruta = os.path.join(carpeta_destino, pdf_nombre)

            pdf_response = requests.get(pdf_url, headers=headers)
            pdf_response.raise_for_status()

            with open(pdf_ruta, 'wb') as f:
                f.write(pdf_response.content)

            print(f'[{contador_actual}/{total_pdf_encontrados}] Archivo PDF descargado: {pdf_ruta}')
            return True
        else:
            print(f'[{contador_actual}/{total_pdf_encontrados}] No se encontró enlace de descarga para: {url_pdf}')
            return False
    except requests.RequestException as e:
        print(f'[{contador_actual}/{total_pdf_encontrados}] Error al descargar el PDF desde {url_pdf}: {e}')
        return False

def main() -> None:
    """Subrutina madre del recolector de la Revista de Sanidad Pública.

    1. Verifica la existencia de `Desktop/pdf`. Si no está, lo crea.
    2. Ataca el Archive URL en busca de los enlaces raiz `.title` representativos de volúmenes.
    3. Construye un inventario total de Galeras cruzando todos los endpoints.
    4. Procede cíclicamente a descargar informando contadores `success`/`total` en consola.
    """
    carpeta_pdf = os.path.join(os.path.expanduser('~'), 'Desktop', 'pdf')
    if not os.path.exists(carpeta_pdf):
        os.makedirs(carpeta_pdf)

    try:
        response = requests.get(url_principal, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        hrefs = [a['href'] for a in soup.find_all('a', class_='title')]
        print(f"Se han encontrado {len(hrefs)} enlaces con la clase 'title'.")

        all_pdf_links = []

        for href in hrefs:
            print(f'Analizando enlace: {href}')
            resultados = revisar_enlace(href)
            if resultados:
                print(f'Enlaces con PDF encontrados en {href}:')
                for resultado in resultados:
                    print(f' - {resultado}')
                    all_pdf_links.append(resultado)
            else:
                print(f'No se encontraron enlaces con PDF en {href}.')

        total_pdf_encontrados = len(all_pdf_links)
        print(f"\nSe han encontrado un total de {total_pdf_encontrados} enlaces con PDFs. Descargando...\n")

        total_pdf_descargados = 0
        for idx, pdf_url in enumerate(all_pdf_links, 1):
            descargado = descargar_pdf(pdf_url, carpeta_pdf, idx, total_pdf_encontrados)
            if descargado:
                total_pdf_descargados += 1

        print(f'\nDescarga completa. {total_pdf_descargados} de {total_pdf_encontrados} PDFs fueron descargados exitosamente.')

    except requests.RequestException as e:
        print(f'Error al conectarse a la página principal: {e}')

if __name__ == "__main__":
    main()
