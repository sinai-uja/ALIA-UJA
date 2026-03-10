"""Recolector y procesador de datos para Parallel Global Voices.

Este módulo descarga, descomprime y convierte un archivo TMX de Parallel Global Voices en
dos datasets Parquet: uno con pares de traducción y otro solo con los textos en el idioma objetivo.

Example:
    python download_parglovoi.py
"""


import os
import xml.etree.ElementTree as ET
import zipfile

from omegaconf import OmegaConf
import polars as pl
import requests
from tqdm import tqdm
import win32net


def download_file(dataset_folder: str, url: str) -> str:
    """Descarga un archivo desde una URL y lo guarda en la carpeta especificada.

    Args:
        dataset_folder: Carpeta donde se guardará el archivo descargado y descomprimido.
        url: URL del archivo .zip a descargar.

    Returns:
        Ruta absoluta del archivo .tmx encontrado dentro del .zip extraído.

    Raises:
        requests.exceptions.HTTPError: Si la descarga falla (ej. error 404).
        FileNotFoundError: Si no se encuentra ningún archivo .tmx en el contenido extraído.
    """

    filename = url.split("/")[-1]
    filepath = os.path.join(dataset_folder, filename)

    # 1) Descargar con tqdm
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total_size = int(r.headers.get("content-length", 0))
        chunk_size = 8192

        with open(filepath, "wb") as f, tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=filename,
            ascii=True,
        ) as load_bar:
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)
                load_bar.update(len(chunk))

    # 2) Descomprimir .zip con tqdm
    with zipfile.ZipFile(filepath, 'r') as zip_ref:
        members = zip_ref.namelist()
        total_size = sum(zip_ref.getinfo(member).file_size for member in members)
        
        with tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=f"Descomprimiendo {filename}",
            ascii=True,
        ) as extract_bar:
            for member in members:
                zip_ref.extract(member, dataset_folder)
                extract_bar.update(zip_ref.getinfo(member).file_size)

    # 3) Buscar el archivo .tmx dentro de la carpeta extraída
    for root, dirs, files in os.walk(dataset_folder):
        for file in files:
            if file.endswith('.tmx'):
                return os.path.join(root, file)
    
    raise FileNotFoundError("No se encontró ningún archivo .tmx en el archivo descargado")


def load_tmx(filepath: str):
    """Carga un archivo TMX y extrae los segmentos de traducción iterativamente.
    
    Args:
        filepath: Ruta absoluta al archivo TMX.

    Yields:
        Diccionario con los segmentos de traducción detectados para cada par de idiomas (ej. {'eng': 'text', 'spa': 'texto'}).
    """
    xml_lang = "{http://www.w3.org/XML/1998/namespace}lang"

    context = ET.iterparse(filepath, events=("end",))
    for event, item in context:
        if item.tag == "tu":
            segments = {}
            for tuv in item.findall("tuv"):
                lang = tuv.attrib.get(xml_lang)
                seg = tuv.find("seg").text if tuv.find("seg") is not None else None
                segments[lang] = seg

            yield segments
            item.clear()  # Liberar memoria


def setup(config_path: str, folders: list[str]) -> str:
    """Carga la configuración desde un archivo YAML, monta un disco en red y crea la estructura de carpetas.

    Args:
        config_path: Ruta al archivo de configuración YAML con credenciales y rutas.
        folders: Lista ordenada de nombres de carpetas para crear la jerarquía del dataset.

    Returns:
        Ruta absoluta de la carpeta principal donde se guardará el dataset.

    Raises:
        RuntimeError: Si ocurre un error al procesar el archivo YAML.
        win32net.error: Si falla la conexión a la unidad de red.
    """

    config = OmegaConf.load(config_path)
    netresource = {
                'remote': config.disk_path,
                'password': config.password,
                'user': config.user
            }
    win32net.NetUseAdd(None, 2, netresource)
    dataset_folder = os.path.join(config.disk_path, *folders)
    os.makedirs(dataset_folder, exist_ok=True)
    return dataset_folder


def tmx_to_parquet(filepath: str, output_path: str, src="eng", tgt="spa") -> None:
    """Convierte un archivo TMX a formato Parquet y genera dos variantes.

    Genera un archivo Parquet completo con los campos (id, text_src, text_tgt) y
    un archivo Parquet reducido solo con los campos (id, text_tgt).

    Args:
        filepath: Ruta absoluta al archivo TMX de entrada.
        output_path: Ruta base para guardar el archivo Parquet completo.
        src: Código del idioma fuente (por defecto 'eng').
        tgt: Código del idioma objetivo (por defecto 'spa').

    Raises:
        ValueError: Si no se encuentran pares válidos para los idiomas indicados en el TMX.
    """
    pairs = []

    # Iteramos el TMX y acumulamos todos los pares
    for i, segs in tqdm(enumerate(load_tmx(filepath), start=1),
                        desc=f"Procesando {filepath}", unit="pares"):
        if src in segs and tgt in segs:
            pairs.append({
                "id": f"{i}", 
                f"text_{src}": segs[src], 
                f"text_{tgt}": segs[tgt]
            })

    # Verificar que hay datos
    if not pairs:
        raise ValueError(f"No se encontraron pares válidos de idiomas {src}-{tgt} en el archivo TMX")

    # Crear DataFrame completo
    df_full = pl.DataFrame(pairs)
    
    # Crear DataFrame reducido (solo id y texto objetivo)
    df_reduced = df_full.select(["id", f"text_{tgt}"])

    # Guardar archivos Parquet
    df_full.write_parquet(output_path, compression="zstd")
    
    reduced_output = output_path.replace(".parquet", f"_{tgt}.parquet")
    df_reduced.write_parquet(reduced_output, compression="zstd")

    print(f"Conversión finalizada.")
    print(f"Total de pares procesados: {len(pairs):,}")
    print(f"Archivo completo: {output_path}")
    print(f"Archivo {tgt}: {reduced_output}")


if __name__ == "__main__":
    # Preparamos la configuración inicial del entorno
    # dataset_folder = "ruta/a/la/carpeta"
    dataset_folder = setup(
        config_path="personal_config.yaml",
        folders=["ALIA", "Parallel_Global_Voices"]
    )

    # Descargamos el archivo TMX español-inglés, descomprimimos y guardamos en la carpeta correspondiente
    filepath = download_file(
        url="https://nlp.ilsp.gr/pgv/archives/eng-spa.zip",
        dataset_folder=dataset_folder
    )

    # Cargamos el archivo TMX, extraemos segmentos de traducción y convertimos en Parquet
    tmx_to_parquet(
        filepath=filepath,
        output_path=os.path.join(dataset_folder, "output.parquet")
    )
