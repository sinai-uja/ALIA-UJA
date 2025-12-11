Definir la estructura estandarizada de los datasets del grupo SINAI.

*Sara Dueñas Romero | sduenas@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Estándar de Estructura de Dataset](#estándar-de-estructura-de-dataset)
  - [Estructura General](#estructura-general)
  - [Columnas Obligatorias](#columnas-obligatorias)
  - [Columnas Adicionales](#columnas-adicionales)
  - [Ejemplo de Estructura de Dataset](#ejemplo-de-estructura-de-dataset)
  - [Consideraciones Adicionales](#consideraciones-adicionales)

---

# Estándar de Estructura de Dataset

Este documento establece las directrices para la estructuración de datasets dentro del proyecto de unificación de creación de datasets para el grupo de trabajo.

## Estructura General

* **Unidad de Datos**: Cada fila del dataset representa una unidad de texto, que puede ser un documento, párrafo o fragmento textual.

* **Formato de Almacenamiento**: Los datasets deben almacenarse en formato `.parquet` para una gestión eficiente en disco y cargarse en memoria utilizando el formato Apache Arrow, aprovechando las capacidades de procesamiento en memoria de Polars.

## Columnas Obligatorias

Todas las tablas deben incluir obligatoriamente las siguientes columnas, con los nombres exactos especificados:

* **`id`**: Identificador único del documento. Debe ser una cadena de texto única que permita distinguir cada unidad de texto.

* **`text`**: Contenido textual del documento. Esta columna es esencial, especialmente para datasets destinados a tareas de generación de texto.

* **`url`**: Enlace directo al texto original, facilitando la trazabilidad y verificación de la fuente. *Este atributo se debe incluir solamente para aquellos recursos que se generen mediante un scrapeo de una fuente de datos.*

Todos los **nombres de columnas deben estar en inglés**, para tener una coherencia entre datasets.

## Columnas Adicionales

Se pueden incluir columnas adicionales para enriquecer la información de cada documento. Las directrices para estas columnas son:

* **Nomenclatura**: Los nombres de las columnas adicionales deben estar en formato `snake_case` (leer [Documentación de Nomenclatura](/data/documentation/estandares/buenas_practicas_nomenclatura.md)), sin espacios ni caracteres especiales, utilizando guiones bajos (`_`) para separar palabras en minúscula si es necesario.

* **Contenido**: Deben representar características distintivas o metadatos relevantes del documento. Ejemplos comunes incluyen:
  * **`name`**: Nombre asociado al documento.
  * **`section`**: Sección o categoría a la que pertenece el documento.
  * **`date`**: Fecha de publicación o creación del documento, preferiblemente en formato (`DD-MM-AAAA`).
  * **`author`**: Nombre del autor o entidad responsable del contenido.
  * **`parent_url`**: URL de la página anterior a la dirección del recurso.

Todos los **nombres de columnas deben estar en inglés**, para tener una coherencia entre datasets.

## Ejemplo de Estructura de Dataset

A continuación, se presenta un ejemplo ilustrativo de cómo debería estructurarse un dataset conforme a este estándar:

```python
import polars as pl

df = pl.DataFrame({
    "id": ["doc001", "doc002", "doc003"],
    "text": [
        "Este es el contenido del primer documento.",
        "Contenido del segundo documento para análisis.",
        "Tercer documento con información relevante."
    ],
    "url": [
        "https://ejemplo.com/doc001",
        "https://ejemplo.com/doc002",
        "https://ejemplo.com/doc003"
    ],
    "name": ["Documento 1", "Documento 2", "Documento 3"],
    "section": ["Noticias", "Opinión", "Cultura"],
    "date": ["20-05-2025", "21-05-2025", "22-05-2025"]
})

df.write_parquet(path)
```

```
shape: (3, 6)
┌────────┬─────────────────────────────────┬────────────────────────────┬─────────────┬──────────┬────────────┐
│ id     ┆ text                            ┆ url                        ┆ name        ┆ section  ┆ date       │
│ ---    ┆ ---                             ┆ ---                        ┆ ---         ┆ ---      ┆ ---        │
│ str    ┆ str                             ┆ str                        ┆ str         ┆ str      ┆ str        │
╞════════╪═════════════════════════════════╪════════════════════════════╪═════════════╪══════════╪════════════╡
│ doc001 ┆ Este es el contenido del prime… ┆ https://ejemplo.com/doc001 ┆ Documento 1 ┆ Noticias ┆ 20-05-2025 │
│ doc002 ┆ Contenido del segundo document… ┆ https://ejemplo.com/doc002 ┆ Documento 2 ┆ Opinión  ┆ 21-05-2025 │
│ doc003 ┆ Tercer documento con informaci… ┆ https://ejemplo.com/doc003 ┆ Documento 3 ┆ Cultura  ┆ 22-05-2025 │
└────────┴─────────────────────────────────┴────────────────────────────┴─────────────┴──────────┴────────────┘
```

Este ejemplo utiliza la biblioteca Polars para crear un DataFrame que cumple con las especificaciones del estándar.

## Consideraciones Adicionales
* **Consistencia de Datos**: Es fundamental mantener la coherencia en los formatos de datos, especialmente en campos como fechas e idiomas.
* **Documentación**: Cada dataset debe ir acompañado de una documentación que describa las columnas incluidas, su significado y cualquier procesamiento previo realizado.
* **Validación**: Se recomienda implementar procesos de validación para asegurar que los datasets cumplen con este estándar antes de su integración en el repositorio principal.

Siguiendo estas directrices, se garantiza una estructura uniforme y coherente en todos los datasets del proyecto, facilitando su manejo, análisis y reutilización por parte de los distintos miembros del grupo de trabajo.

