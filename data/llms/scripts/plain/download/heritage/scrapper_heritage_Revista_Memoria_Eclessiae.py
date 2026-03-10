"""Descargador de PDFs de la Revista Memoria Ecclesiae.

Este módulo descarga los archivos PDF publicados en la página de la
Revista Memoria Ecclesiae, editada por la Asociación de Archiveros de la
Iglesia en España. Los PDFs se detectan analizando los enlaces del
contenido principal de la página y se descargan con soporte para
reintento automático en caso de error 404 por mayúsculas/minúsculas.

La Revista Memoria Ecclesiae contiene:
    - Estudios de archivística eclesiástica
    - Publicaciones sobre patrimonio documental de la Iglesia en España

Example:
    Ejecución básica::

        python scrapper_heritage_Revista_Memoria_Eclessiae.py

    Esto descargará todos los PDFs disponibles en la página de publicaciones
    de la revista en la carpeta ``pdfs/``.

Attributes:
    CORRECCIONES (dict): Diccionario de URLs incorrectas y sus correcciones
        manuales para evitar errores 404 conocidos.

Note:
    Los PDFs son de acceso público a través de la web de Scrinia.
    URL: https://scrinia.org/publicaciones/memoria/
"""

import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote

# --- Diccionario de correcciones manuales de URLs conocidas con errores ---
CORRECCIONES = {
    "https://scrinia.org/wp-content/uploads/2019/05/Indice_MemoriaEcclesiaeXXVIII.pdf": "https://scrinia.org/wp-content/uploads/2022/02/Memoria-Ecclesiae-28-indice.pdf",
}


def limpiar_doble_barra(url: str) -> str:
    """Elimina dobles barras ``//`` generadas por error en una URL.

    Conserva el ``://`` del protocolo (``http://`` o ``https://``) pero
    elimina cualquier duplicado de barra en el resto de la ruta.

    Args:
        url: URL a limpiar.

    Returns:
        URL con las dobles barras eliminadas, excepto en el protocolo.
    """
    if not url.startswith("http"):
        return url
    partes = url.split('://')
    protocolo = partes[0]
    resto = partes[1] if len(partes) > 1 else partes[0]
    return f"{protocolo}://{resto.replace('//', '/')}"


def descargar_pdfs(url_objetivo: str, carpeta_destino: str) -> None:
    """Descarga todos los PDFs enlazados en el contenido principal de la página.

    Accede a ``url_objetivo``, extrae los enlaces del contenido visible
    (ignorando menús y cabeceras ocultas), filtra los que apuntan a archivos
    ``.pdf`` y los descarga en ``carpeta_destino``. Si un archivo ya existe,
    lo omite. En caso de error 404, reintenta con la URL en minúsculas.
    Los errores de descarga se registran en ``errores.txt``.

    Args:
        url_objetivo: URL de la página donde buscar los enlaces a PDFs.
        carpeta_destino: Ruta a la carpeta donde guardar los PDFs descargados.
    """
    if not os.path.exists(carpeta_destino):
        os.makedirs(carpeta_destino)
        print(f"Carpeta '{carpeta_destino}' creada.")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }

    try:
        print(f"Conectando a {url_objetivo}...")
        response = requests.get(url_objetivo, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error crítico al conectar con la web: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # Buscar el contenedor principal para evitar menús y cabeceras ocultas
    zona_contenido = soup.find(id='main-content')

    if not zona_contenido:
        # Fallback por si cambia la plantilla
        zona_contenido = soup.find(class_='entry-content')

    if zona_contenido:
        print("Zona de contenido principal detectada. Ignorando menús ocultos y headers...")
        contexto = zona_contenido
    else:
        print("No se detectó zona principal específica. Buscando en toda la página...")
        contexto = soup

    links = contexto.find_all('a', href=True)
    urls_pdf = set()

    print("Analizando enlaces del contenido...")
    for link in links:
        href = link['href']
        url_completa = urljoin(url_objetivo, href)

        # Limpieza básica: eliminar fragmentos y parámetros
        url_limpia = url_completa.split('#')[0].split('?')[0]
        url_limpia = limpiar_doble_barra(url_limpia)

        if url_limpia.lower().endswith('.pdf'):
            urls_pdf.add(url_limpia)

    print(f"Se encontraron {len(urls_pdf)} archivos PDF en el contenido principal.")

    count = 0
    errores = []

    for url in urls_pdf:
        url_final = CORRECCIONES.get(url, url)
        filename_part = url_final.split('/')[-1]
        nombre_archivo = unquote(filename_part)
        ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)

        if os.path.exists(ruta_archivo):
            if url == url_final:
                print(f"[Saltado] Ya existe: {nombre_archivo}")
            continue

        try:
            print(f"Descargando: {nombre_archivo}...")

            response_pdf = None
            try:
                r = requests.get(url_final, headers=headers, stream=True)
                r.raise_for_status()
                response_pdf = r
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    # Reintentar con URL en minúsculas
                    url_lower = url_final.lower()
                    if url_lower != url_final:
                        print(f"  > Error 404. Reintentando versión en minúsculas...")
                        r_retry = requests.get(url_lower, headers=headers, stream=True)
                        r_retry.raise_for_status()
                        response_pdf = r_retry
                        nombre_archivo = unquote(url_lower.split('/')[-1])
                        ruta_archivo = os.path.join(carpeta_destino, nombre_archivo)
                    else:
                        raise e
                else:
                    raise e

            with open(ruta_archivo, 'wb') as f:
                for chunk in response_pdf.iter_content(chunk_size=8192):
                    f.write(chunk)

            count += 1

        except Exception as e:
            print(f"ERROR descargando {url}: {e}")
            errores.append(url)

    print(f"\n--- PROCESO FINALIZADO ---")
    print(f"Descargas exitosas: {count}")

    if errores:
        with open("errores.txt", "w") as f_err:
            f_err.write("Enlaces fallidos:\n")
            for err in errores:
                f_err.write(f"{err}\n")


if __name__ == "__main__":
    URL = "https://scrinia.org/publicaciones/memoria/"
    CARPETA = "pdfs"
    descargar_pdfs(URL, CARPETA)