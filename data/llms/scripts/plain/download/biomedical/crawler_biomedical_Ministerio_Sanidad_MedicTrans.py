"""Recolector de datos web para el Ministerio de Sanidad (Medicina Transfusional).

Este módulo implementa un conjunto de funciones asíncronas para recolectar
documentos PDF relacionados con Medicina Transfusional desde la web del
Ministerio de Sanidad de España utilizando Crawl4AI. Los datos extraídos
incluyen el texto de los PDFs y metadatos asociados, conformando un dataset
en formato Parquet.

El portal contiene:
    - Información sobre donación de sangre
    - Normativa y recomendaciones
    - Publicaciones e informes técnicos

Example:
    Ejecución básica::

        python crawler_biomedical_Ministerio_Sanidad_MedicTrans.py

    Esto rastreará el sitio web, extraerá los enlaces a los PDFs, extraerá el
    texto y guardará los resultados en un archivo Parquet.

Note:
    Los metadatos y documentos provienen del portal de profesionales del
    Ministerio de Sanidad:
    URL: https://www.sanidad.gob.es/profesionales/saludPublica/medicinaTransfusional
"""

import asyncio
import json
import pandas as pd
import re
import requests
import shutil
from download_pdfs import download
import os

import nest_asyncio
nest_asyncio.apply()

from crawl4ai import (
    AsyncWebCrawler, CrawlerRunConfig, CacheMode,
    FilterChain, DomainFilter, URLPatternFilter,
    BFSDeepCrawlStrategy, LXMLWebScrapingStrategy
)


def clean_filename(nombre: str, reemplazo: str = "_") -> str:
    """Limpia un nombre de archivo reemplazando caracteres no válidos.

    Args:
        nombre: El nombre de archivo original a limpiar.
        reemplazo: El carácter o cadena a usar como reemplazo de los
            caracteres inválidos. Por defecto es "_".

    Returns:
        Nombre de archivo limpio y sin caracteres especiales.
    """
    nombre_limpio = re.sub(r'[\/:*?"<>|]', reemplazo, nombre)
    return re.sub(f'{reemplazo}+', reemplazo, nombre_limpio).strip()


def proc_markdown(markdown_contents: list, exclude_id: list) -> pd.DataFrame:
    """Procesa contenido Markdown y extrae enlaces con contexto.

    Analiza el texto Markdown buscando secciones y subsecciones, así como
    enlaces. Devuelve un DataFrame con las URLs encontradas y su contexto.

    Args:
        markdown_contents: Lista de cadenas de texto con contenido en Markdown.
        exclude_id: Lista de textos de enlaces que, de encontrarse, forzarán
            el uso del nombre de la sección como ID en lugar del texto del enlace.

    Returns:
        pd.DataFrame con columnas 'id', 'url', 'section' y 'subsection'
        conteniendo la información extraída.
    """
    enlaces = []
    re_seccion = re.compile(r"^# (.+)")
    re_subseccion = re.compile(r"^## (.+)")
    re_enlace = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)")

    for contenido in markdown_contents:
        seccion, subseccion = "", ""
        for line in contenido.splitlines():
            line = line.strip()
            if not line:
                continue
            if match := re_seccion.match(line):
                seccion = match.group(1).strip()
            elif match := re_subseccion.match(line):
                subseccion = match.group(1).strip()
            elif match := re_enlace.search(line):
                texto, url = match.groups()
                texto = clean_filename(texto)
                enlaces.append({
                    "id": seccion if texto in exclude_id else texto,
                    "url": url,
                    "section": seccion,
                    "subsection": subseccion,
                })

    return pd.DataFrame(enlaces)


def es_pdf(url: str) -> bool:
    """Verifica si la URL apunta a un archivo PDF usando cabecera HTTP.

    Realiza una petición HEAD a la URL y comprueba el `Content-Type`.

    Args:
        url: La dirección URL a verificar.

    Returns:
        True si el Content-Type indica un PDF ('application/pdf'),
        False en caso contrario o si ocurre un error en la petición.
    """
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        return "application/pdf" in response.headers.get("Content-Type", "").lower()
    except Exception as e:
        print(f"[Error] Verificando tipo de contenido para {url}: {e}")
        return False


async def run_crawler_and_process() -> list:
    """Ejecuta el crawler principal para recolectar páginas.

    Configura y ejecuta un crawler asíncrono en profundidad (BFS) sobre el
    portal de Medicina Transfusional. Excluye elementos no deseados de la
    página y espera a que el contenido dinámico termine de cargar. Guarda el
    árbol de URLs en un archivo JSON.

    Returns:
        Lista de diccionarios con las URLs encontradas y sus metadatos.
    """
    # Definir filtros y condiciones de espera
    filter_chain = FilterChain([
        DomainFilter(blocked_domains=[]),
        URLPatternFilter(patterns=["*/es/*"])
    ])

    wait_condition = """
    () => new Promise(resolve => {
        setTimeout(() => {
            resolve(true);
        }, 2000);
    })
    """

    # Configuración del crawler principal (deep crawl)
    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=5,
            include_external=False
        ),
        exclude_domains=[],
        excluded_tags=['header', 'script', 'footer', 'aside'],
        excluded_selector=".row.rs-migas, .table-responsive, .scrolltop",
        exclude_all_images=True,
        wait_for=f"js:{wait_condition}",
        scraping_strategy=LXMLWebScrapingStrategy(),
        cache_mode=CacheMode.BYPASS,
        verbose=True
    )

    root_url = "https://www.sanidad.gob.es/profesionales/saludPublica/medicinaTransfusional"

    async with AsyncWebCrawler() as crawler:
        print("[INFO] Iniciando crawling profundo...")
        results = await crawler.arun(root_url, config=config)

        data = [
            {"url": result.url, "metadata": result.metadata}
            for result in results if result.url != root_url
        ]

        print(f"[INFO] Crawled {len(data)} páginas")
        with open("urls_tree_Ministerio_Sanidad-MedicTrans.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    return data


async def extract_pdf_links_and_generate_csv(results: list) -> None:
    """Filtra enlaces PDF, recupera markdown de las páginas contenedoras y exporta CSV.

    A partir de los resultados previos, identifica las URLs que apuntan a PDFs,
    rastrea las páginas donde se encontraron para obtener su Markdown y asocia
    las URLs de los PDFs con su contexto semántico. Finalmente guarda todo en
    un archivo CSV.

    Args:
        results: Lista de diccionarios devueltos por `run_crawler_and_process`,
            donde cada uno contiene la 'url' y sus correspondientes 'metadata'.
    """
    crawler_config = CrawlerRunConfig(
        exclude_domains=[],
        excluded_tags=['header', 'script', 'footer', 'aside'],
        excluded_selector=".row.rs-migas, .table-responsive, .scrolltop",
        exclude_all_images=True,
        wait_for="js:() => new Promise(resolve => setTimeout(resolve, 2000))",
        cache_mode=CacheMode.BYPASS,
        verbose=True,
        scraping_strategy=LXMLWebScrapingStrategy()
    )

    markdown_list = []
    pdf_links = []
    parent_urls_df = pd.DataFrame(columns=["parent_url"])

    async with AsyncWebCrawler() as crawler:
        for result in results:
            url = result['url']
            if es_pdf(url):
                pdf_links.append(url)
                parent_url = result['metadata'].get('parent_url')
                if parent_url:
                    parent_urls_df.loc[len(parent_urls_df)] = [parent_url]
                    try:
                        page = await crawler.arun(parent_url, config=crawler_config)
                        markdown_list.append(page.markdown)
                    except Exception as e:
                        print(f"[ERROR] No se pudo procesar {parent_url}: {e}")

    data = proc_markdown(markdown_list, exclude_id=[])
    data_filtrado = data[data["url"].isin(pdf_links)].drop_duplicates(subset="url")

    # Combina metadatos de origen con enlaces PDF
    data_final = pd.concat([data_filtrado.reset_index(drop=True), parent_urls_df.reset_index(drop=True)], axis=1)

    output_file = "Ministerio_Sanidad-MedicTrans.csv"
    data_final.to_csv(output_file, index=False)
    print(f"[INFO] CSV exportado a {output_file}")


def postprocess_csv_and_generate_parquet(dirname: str) -> None:
    """Carga el CSV generado, extrae PDFs a texto y guarda en Parquet.

    Lee el archivo CSV de metadatos, procede a descargar los documentos PDF,
    extrae el contenido de texto de cada uno, y consolida todos los datos en
    un archivo Parquet en la carpeta especificada. Mueve el CSV original a la
    carpeta de salida.

    Args:
        dirname: Nombre del directorio de salida y prefijo del archivo CSV.
    """
    csv_path = f"{dirname}.csv"
    output_dir = dirname

    # Asegurar que el directorio existe
    os.makedirs(output_dir, exist_ok=True)

    # Leer CSV
    data = pd.read_csv(csv_path)

    # Descargar PDFs y agregar texto
    data["text"] = data.apply(lambda row: download(row["url"], output_dir, row["id"]), axis=1)

    # Guardar como archivo Parquet
    parquet_path = f"{output_dir}/output.parquet"
    data.to_parquet(parquet_path, index=False)
    print(f"[INFO] Archivo Parquet creado en {parquet_path}")

    # Mover JSON a la carpeta
    shutil.move(csv_path, f"{output_dir}/{os.path.basename(csv_path)}")
    print(f"[INFO] CSV movido a {output_dir}/")

    # Mover CSV original a la carpeta
    shutil.move(csv_path, f"{output_dir}/{os.path.basename(csv_path)}")
    print(f"[INFO] CSV movido a {output_dir}/")


async def main() -> None:
    """Función principal asíncrona que coordina el flujo completo.

    Ejecuta el rastreo inicial, la extracción y almacenamiento en CSV, y
    el postprocesamiento para descargar PDFs y crear el dataset Parquet.
    """
    results = await run_crawler_and_process()
    await extract_pdf_links_and_generate_csv(results)
    postprocess_csv_and_generate_parquet("Ministerio_Sanidad-MedicTrans")


if __name__ == "__main__":
    asyncio.run(main())
