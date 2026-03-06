"""Descargador de PDFs de la Revista de Arquitectura Religiosa Contemporánea.

Este módulo descarga los artículos en formato PDF de todos los números
publicados en la Revista de Arquitectura Religiosa Contemporánea (AARC)
de la Universidade da Coruña, navegando por su archivo de ediciones con
Playwright (API síncrona) y extrayendo el texto de cada PDF con PyPDF2.
Los resultados se guardan en un CSV y un archivo Parquet.

La Revista AARC contiene:
    - Artículos científicos sobre arquitectura religiosa contemporánea
    - Publicaciones del área de Historia del Arte y Arquitectura

Example:
    Ejecución básica::

        python scrapper_heritage_ActasDeArquitecturaReligiosaContemporánea.py

    Esto navegará por el archivo de ediciones, descargará los PDFs en
    ``pdfs_revista_aarc/`` y generará ``output.csv`` y ``output.parquet``.

Attributes:
    MAIN_URL (str): URL del archivo de ediciones de la revista.
    OUTPUT_DIR (str): Carpeta raíz donde se guardan los PDFs por edición.
    registros (list[dict]): Lista global de registros con ``id``, ``url``
        y ``text`` para construir el CSV.

Note:
    Los artículos son de acceso abierto a través del portal de revistas
    de la Universidade da Coruña.
    URL: https://revistas.udc.es/index.php/aarc/issue/archive
"""

import os
import re
import unicodedata
import csv
import polars as pl
from PyPDF2 import PdfReader
from playwright.sync_api import sync_playwright

registros = []  # Para guardar filas con id, url y texto

# URL principal de la revista (lista de todas las ediciones)
MAIN_URL = "https://revistas.udc.es/index.php/aarc/issue/archive"

# Carpeta raíz donde se guardarán los PDFs
OUTPUT_DIR = "pdfs_revista_aarc"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def extraer_texto_pdf(ruta_pdf: str) -> str:
    """Extrae el texto de un PDF usando PyPDF2.

    Maneja errores y PDFs vacíos devolviendo una cadena vacía en caso
    de fallo.

    Args:
        ruta_pdf: Ruta al archivo PDF del que extraer el texto.

    Returns:
        Texto extraído del PDF, o cadena vacía si el PDF está vacío
        o si ocurrió un error.
    """
    try:
        reader = PdfReader(ruta_pdf)
        texto = []
        for page in reader.pages:
            texto.append(page.extract_text() or "")
        return "\n".join(texto).strip()
    except Exception as e:
        print(f"Error al extraer texto de {ruta_pdf}: {e}")
        return ""


def normalizar_nombre_archivo(nombre: str) -> str:
    """Limpia y normaliza un nombre de archivo para hacerlo seguro en Windows.

    Elimina tildes y acentos, reemplaza espacios por guiones bajos, elimina
    caracteres no válidos en Windows y limita la longitud si es necesario.

    Args:
        nombre: Nombre original sin normalizar.

    Returns:
        Nombre normalizado y seguro para usar en rutas de archivos.
    """
    # Quitar tildes y acentos
    nombre = unicodedata.normalize("NFKD", nombre)
    nombre = nombre.encode("ascii", "ignore").decode("ascii")

    # Reemplazar espacios por guiones bajos
    nombre = nombre.replace(" ", "_")

    # Eliminar caracteres no válidos para Windows
    nombre = re.sub(r'[<>:"/\\|?*]', '', nombre)

    # Quitar posibles caracteres no imprimibles o sobrantes
    nombre = nombre.strip().replace('\n', '')

    return nombre


def descargar_edicion(context, issue_url: str, issue_name: str) -> None:
    """Descarga todos los PDFs de una edición específica de la revista.

    Navega a la página de la edición, localiza los enlaces a los artículos
    en PDF, accede a la página de galería de cada artículo, descarga el PDF
    mediante el botón de descarga y extrae su texto con PyPDF2. Añade cada
    registro a la lista global ``registros``.

    Args:
        context: Contexto de Playwright activo para crear nuevas páginas.
        issue_url: URL de la página de la edición de la revista.
        issue_name: Nombre normalizado de la edición, usado para nombrar
            la subcarpeta de PDFs.
    """
    issue_folder = os.path.join(OUTPUT_DIR, issue_name)
    os.makedirs(issue_folder, exist_ok=True)

    page = context.new_page()
    print(f"\n Procesando edición: {issue_name}")
    page.goto(issue_url)

    # Esperar a que aparezcan los enlaces a artículos
    try:
        page.wait_for_selector("a.obj_galley_link.pdf", timeout=10000)
    except:
        print(f" No se encontraron artículos en {issue_url}")
        page.close()
        return

    links = page.query_selector_all("a.obj_galley_link.pdf")
    print(f"{len(links)} artículos encontrados.")

    for i, link in enumerate(links, start=1):
        href = link.get_attribute("href")
        if not href:
            continue

        article_url = page.evaluate("(url) => new URL(url, window.location.href).href", href)
        print(f"  [{i}/{len(links)}] Artículo: {article_url}")

        article_page = context.new_page()
        article_page.goto(article_url)

        try:
            article_page.wait_for_selector("a.download", timeout=10000)
        except:
            print("No se encontró enlace de descarga.")
            article_page.close()
            continue

        download_button = article_page.query_selector("a.download")
        pdf_url = article_page.evaluate("(el) => el.href", download_button)
        if not download_button:
            print("No hay botón de descarga.")
            article_page.close()
            continue

        # Descargar PDF mediante el botón de descarga
        with article_page.expect_download() as download_info:
            download_button.click()

        download = download_info.value
        filename = normalizar_nombre_archivo(f"articulo_{i}_{issue_name}.pdf")
        save_path = "\\\\?\\" + os.path.abspath(os.path.join(issue_folder, filename))
        download.save_as(save_path)

        print(f"PDF guardado: {save_path}")

        # Extraer texto del PDF y registrar en la lista global
        texto = extraer_texto_pdf(save_path)
        registros.append({
            "id": filename,
            "url": pdf_url,
            "text": texto
        })

        article_page.close()

    page.close()


def main():
    """Ejecuta el proceso completo de descarga de todas las ediciones.

    Navega al archivo de ediciones de la revista, extrae los enlaces a
    cada número, llama a ``descargar_edicion`` para cada uno, y al finalizar
    genera el CSV ``output.csv`` y su equivalente en formato Parquet.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print(f"Navegando a {MAIN_URL} ...")
        page.goto(MAIN_URL)

        # Esperar a que carguen las ediciones
        page.wait_for_selector("div.obj_issue_summary a.title")

        issue_links = page.query_selector_all("div.obj_issue_summary a.title")
        print(f"Encontradas {len(issue_links)} ediciones.")

        for issue_link in issue_links:
            issue_url = issue_link.get_attribute("href")
            issue_name = issue_link.inner_text().strip().replace("/", "-")
            issue_url = page.evaluate("(url) => new URL(url, window.location.href).href", issue_url)

            descargar_edicion(context, issue_url, issue_name)

        browser.close()
        print("\n Descarga completa de todas las ediciones.")

        # Guardar resultados en CSV
        csv_path = "output.csv"
        with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "url", "text"])
            writer.writeheader()
            writer.writerows(registros)

        print(f"\n CSV generado: {csv_path}")

        # Convertir CSV a Parquet con Polars
        df = pl.read_csv(csv_path)
        parquet_path = "output.parquet"
        df.write_parquet(parquet_path)

        print(f"Archivo Parquet generado: {parquet_path}")


if __name__ == "__main__":
    main()