"""Conversor de URLs a texto para el dataset del Ministerio de Vivienda y Agenda Urbana.

Este script lee un CSV con URLs de documentos del Ministerio de Vivienda y Agenda Urbana,
descarga cada URL con `download_pdfs.download` y extrae el texto del documento.
El resultado se guarda en un archivo Parquet y el CSV original se mueve a la misma carpeta.

Attributes:
    dirname (str): Nombre del directorio y base del dataset.
"""

import pandas as pd
import shutil
import os
from download_pdfs import download


def get_data(dirname):
    """Lee el CSV del dataset y descarga el texto de cada URL referenciada.

    Args:
        dirname (str): Nombre del directorio que contiene el CSV (`{dirname}.csv`) y donde
                       se guardarán los datos descargados.

    Returns:
        pd.DataFrame: DataFrame con columna `text` añadida con el contenido descargado.
    """
    # Leer el CSV desde el archivo
    data = pd.read_csv(f"{dirname}.csv")

    # Agregar la columna 'text' descargando el contenido de cada URL
    data["text"] = data.apply(lambda row: download(row["url"], dirname, row["id"]), axis=1)

    return data


# ID del dataset y nombre del archivo base
dirname = "Ministerio_Vivienda&AgendaUrbana"

# Asegurar que el directorio existe
os.makedirs(dirname, exist_ok=True)

# Crear el DataFrame con los textos
df = get_data(dirname)

# Guardar como archivo Parquet
df.to_parquet(f"{dirname}/output.parquet", index=False)
print("Archivo Parquet creado")

# Mover el archivo CSV original a la carpeta
shutil.move(f"{dirname}.csv", f"{dirname}/{dirname}.csv")
