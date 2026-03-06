"""Recolector de publicaciones del Departamento de Seguridad Nacional (DSN).

Este script automatiza la extracción y descarga de publicaciones del portal `dsn.gob.es`.
Navega por categorías y sus páginas paginadas, accede a cada publicación y extrae los
enlaces de descarga (PDFs o HTML). Los PDFs se descargan directamente; el HTML se convierte
a texto y luego a PDF vía reportlab. El texto se extrae con pdfplumber y los datos se
guardan en un Parquet.

Attributes:
    url (str): URL de la página de publicaciones del DSN.
    path_datos (str): Directorio local donde se guardan los archivos descargados.
    path (str): Directorio raíz para el Parquet de salida.
"""

import requests
from bs4 import BeautifulSoup
import unicodedata
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from urllib.parse import urljoin
import fitz
import polars as pl
import pdfplumber

def devolver_etiquetas(soup):
    """Extrae los nombres de las categorías de publicaciones de la página principal del DSN.

    Args:
        soup (BeautifulSoup): Objeto soup de la página principal.

    Returns:
        list[str]: Lista de nombres de categorías encontradas.
    """
    # Buscar el primer enlace de publicación
    etiquetas = soup.select("p.heading-square-title")
    categoria = []
    
    for i in etiquetas:
        #print(i.text)
        categoria.append(i.text)
    return categoria

def devolver_publicacion(soup):
    """Extrae los enlaces a publicaciones individuales de una página de categoría.

    Args:
        soup (BeautifulSoup): Objeto soup de la página de categoría.

    Returns:
        list[str]: Lista de URLs absolutas a cada publicación por tarjeta.
    """
    archivos = []
    archivos = soup.select("a.card")

    enlaces = []
    for archivo in archivos:
        if archivo and archivo.has_attr("href"):
            enlace = "https://www.dsn.gob.es" + archivo["href"]
            enlaces.append(enlace)
            #print(f"Enlace del archivo: {enlace}")
        else:
            print("No se encontró el enlace PDF.")
            
    return enlaces

def obtener_todas_las_paginas_categoria(url_categoria, headers):
    """Devuelve todas las URLs paginadas dentro de una categoría.

    Itera incrementando el parámetro `page` hasta que no se encuentran más tarjetas.

    Args:
        url_categoria (str): URL base de la categoría.
        headers (dict): Cabeceras HTTP para simular navegador.

    Returns:
        list[str]: Lista de URLs de páginas paginadas.
    """
    paginas = []
    pagina = 0

    while True:
        url_pagina = f"{url_categoria}?page={pagina}"
        response = requests.get(url_pagina, headers=headers)

        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.text, "html.parser")
        archivos = soup.select("a.card")
        if not archivos:
            break  # No hay más publicaciones

        paginas.append(url_pagina)
        pagina += 1

    return paginas


def extraer_enlaces_descargas(soup):
    """Extrae los enlaces de descarga de una publicación individual.

    Busca dentro de elementos `div.richtext` todos los enlaces encontrados,
    completando any URL relativa con la base del DSN.

    Args:
        soup (BeautifulSoup): Objeto soup de la página de la publicación.

    Returns:
        list[str]: Lista de URLs de descarga absolutas.
    """
    secciones = soup.select("div.richtext")
    enlaces = []

    for seccion in secciones:
        a_tags = seccion.find_all("a", href=True)
        for a in a_tags:
            href = a["href"].strip()

            # Si empieza por "www.", añadirle el esquema
            if href.startswith("www."):
                href = "https://" + href

            # Unir correctamente con la base
            enlace = urljoin("https://www.dsn.gob.es", href)
            enlaces.append(enlace)
            #print(f"Enlace de descarga encontrado: {enlace}")

    if not enlaces:
        print("No se encontraron enlaces de descarga.")

    return enlaces

def unir_url_categoria(texto):
    """Convierte el nombre de una categoría a formato de slug para URL.

    Normaliza a minúsculas, elimina acentos y reemplaza espacios por guiones.

    Args:
        texto (str): Nombre de la categoría tal como aparece en la página.

    Returns:
        str: Slug válido para construir la URL de la categoría.
    """
    texto = texto.lower()
    texto = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('utf-8')  # quita acentos
    texto = texto.replace(' ', '-')
    #print(texto)
    return texto


def txt_a_pdf(ruta_txt, ruta_pdf):
    """Convierte un archivo de texto plano a PDF usando ReportLab.

    Args:
        ruta_txt (str): Ruta al archivo `.txt` de entrada.
        ruta_pdf (str): Ruta de salida del PDF generado.
    """
    with open(ruta_txt, "r", encoding="utf-8") as f:
        contenido = f.readlines()

    c = canvas.Canvas(ruta_pdf, pagesize=A4)
    width, height = A4
    y = height - 50

    for linea in contenido:
        if y < 50:
            c.showPage()
            y = height - 50
        c.drawString(50, y, linea.strip())
        y -= 15

    c.save()

def extraer_texto_pdf_mas_robusto(ruta_pdf):
    """Extrae el texto de un PDF con PyMuPDF. Es una alternativa robusta frente a fallos de pdfplumber.

    Args:
        ruta_pdf (str): Ruta al PDF local.

    Returns:
        str: Texto extraído o cadena vacía en caso de error.
    """
    texto = ""
    try:
        doc = fitz.open(ruta_pdf)
        for pagina in doc:
            texto += pagina.get_text()
        doc.close()
    except Exception as e:
        print(f"Error al leer el PDF: {e}")
    return texto

def read_pdf(pdf_file):
    """Extrae el texto de todas las páginas de un PDF usando pdfplumber.

    Args:
        pdf_file (str): Ruta al PDF local.

    Returns:
        str: Texto concatenado de todas las páginas.
    """
    texto = ''
    with pdfplumber.open(pdf_file) as pdf:
        for num_pagina in range(len(pdf.pages)):
            pagina = pdf.pages[num_pagina]
            texto_pag = pagina.extract_text()
            texto += texto_pag
    return texto


def procesar_enlace_descarga(enlace, headers, path_destino, nombre_base="descarga"):
    """Descarga un enlace de publicación del DSN y lo guarda como PDF.

    Distingue tres casos:
    - A) El enlace apunta directamente a un PDF.
    - B) El enlace apunta a un HTML válido del que extrae texto y genera PDF con ReportLab.
    - C) El enlace devuelve un 404 o página de error.

    Args:
        enlace (str): URL a procesar.
        headers (dict): Cabeceras HTTP.
        path_destino (str): Directorio donde guardar el archivo generado.
        nombre_base (str, optional): Nombre base (sin extensión) del archivo. Default `'descarga'`.

    Returns:
        bool: True si se guardó algún contenido válido, False en caso contrario.
    """
    try:
        print(f"Procesando enlace: {enlace}")
        response = requests.get(enlace, headers=headers, timeout=10)

        # Validación HTTP
        if response.status_code != 200:
            print(f"Error HTTP ({response.status_code}) al acceder a {enlace}")
            return False

        content_type = response.headers.get("Content-Type", "").lower()
        is_pdf = ".pdf" in enlace.lower() or "application/pdf" in content_type

        if is_pdf:
            # CASO A: PDF
            ruta_pdf = os.path.join(path_destino, nombre_base + ".pdf")
            with open(ruta_pdf, "wb") as f:
                f.write(response.content)
            print(f"-------PDF guardado en: {ruta_pdf}")
            return True

        # CASO B/C: Asumimos HTML
        soup = BeautifulSoup(response.text, "html.parser")
        texto = soup.get_text().lower()

        # CASO C: Página no encontrada
        errores_404 = ["página no encontrada", "error 404", "no se encuentra", "server-unavailable!"]
        if any(err in texto for err in errores_404):
            print(f"Página no encontrada en: {enlace}")
            return False

        # CASO B: HTML válido, extraer texto
        parrafos = soup.find_all("p")
        texto_parrafos = "\n".join([p.get_text(strip=True) for p in parrafos if p.get_text(strip=True)])

        if not texto_parrafos:
            print(f"No se encontraron <p> útiles en: {enlace}")
            return False

        # Guardar texto como .txt
        ruta_txt = os.path.join(path_destino, nombre_base + ".txt")
        with open(ruta_txt, "w", encoding="utf-8") as f:
            f.write(texto_parrafos)
        print(f"Texto HTML guardado en: {ruta_txt}")

        # Convertir a PDF
        ruta_pdf = os.path.join(path_destino, nombre_base + ".pdf")
        txt_a_pdf(ruta_txt, ruta_pdf)
        #print(f"PDF generado desde HTML en: {ruta_pdf}")

        os.remove(ruta_txt)  # Limpieza
        return True

    except requests.exceptions.RequestException as e:
        print(f"Error de red al procesar {enlace}: {e}")
    except Exception as e:
        print(f"Error inesperado procesando {enlace}: {e}")
    
    return False



def main():
    """Orquestador del scraping del DSN.

    Accede a la página de publicaciones del DSN, obtiene las categorías y sus páginas.
    Por cada publicación: navega a su detalle, extrae los enlaces de descarga y los procesa
    intentando guardarlos como PDF (directamente o via conversión HTML).
    En caso de fallo genera un PDF de error. Lee el PDF con pdfplumber y acumula los datos.
    Al final guarda todo en un Parquet.
    """
    # URL objetivo
    url = "https://www.dsn.gob.es/es/publicaciones"
    path_datos = "/home/mmg/scraper/scraper_dsn/docs"
    path = "/home/mmg/scraper/scraper_dsn"

    dict_id_txt = []

    # Encabezados para simular navegador (Chrome)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    }

    # Solicitud a la página de publicaciones
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        print("Entrado en la pagina principal")
        soup = BeautifulSoup(response.text, "html.parser")

        categorias = devolver_etiquetas(soup)
        #print(categorias)

        # Generar URLs
        urls = [url + "/" + unir_url_categoria(cat) for cat in categorias]

        for categoria, url_categoria in zip(categorias, urls):
            paginas_categoria = obtener_todas_las_paginas_categoria(url_categoria, headers)

            for url_pagina in paginas_categoria:
                responsePublicaciones = requests.get(url_pagina, headers=headers)
                soupPublicaciones = BeautifulSoup(responsePublicaciones.text, "html.parser")
                enlaces = devolver_publicacion(soupPublicaciones)

                for enlace in enlaces:
                    #print(f"Archivo: {enlace}, enlaces encontrado dentro de la categoría: {len(enlaces)}")
                    responseDescargas = requests.get(enlace, headers=headers)
                    soupDescargas = BeautifulSoup(responseDescargas.text, "html.parser") 
                    nombre_archivo = (soupDescargas.select_one("p.heading-title")).text
                    #print(f"Titulo del archivo: {nombre_archivo}")
                    enlaces_descarga = extraer_enlaces_descargas(soupDescargas)
                    
                    
                    for i, enlace_descarga in enumerate(enlaces_descarga):
                        nombre_base = f"{nombre_archivo}_{i}"
                        exito = procesar_enlace_descarga(enlace_descarga, headers, path_datos, nombre_base)

                        if not exito:
                            # Generar PDF con mensaje de error
                            ruta_pdf_error = os.path.join(path_datos, nombre_base + "_ERROR.pdf")
                            c = canvas.Canvas(ruta_pdf_error, pagesize=A4)
                            c.drawString(50, 800, f"Enlace de descarga fallido: {enlace_descarga}")
                            c.drawString(50, 780, "No se pudo guardar ningún contenido válido.")
                            c.save()
                            print(f"PDF de error guardado en: {ruta_pdf_error}")
                        
                        else:

                            nombre_pdf = nombre_base + ".pdf"
                            ruta = os.path.join(path_datos, nombre_pdf)
                            texto = read_pdf(ruta)
                            print("PDF leído correctamente")
                            """
                            id = nombre_base
                            url = enlace
                            seccion = categoria_slug"""

                        dict_id_txt.append({"id": nombre_base, "txt": texto, "url": enlace, "seccion": categoria})

                            
    else:
        print("Error al acceder a la página principal:", response.status_code)


    try:
        df = pl.DataFrame(dict_id_txt)
        df.write_parquet(f"{path}/output.parquet")
        print(".parquet guardado correctamente")
        
    except Exception as e:
        print(f"Error al guardar el parquet: {e}")

if __name__ == "__main__":
    main()

main()