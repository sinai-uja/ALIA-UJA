Para cada versión del corpus generada en el marco del Proyecto ALIA, se debe documentar el flujo de construcción, limpieza y consolidación de datos.

*Sara Dueñas Romero, Adrián Moreno Muñoz | sduenas@ujaen.es, ammunoz@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Funcionamiento de los scripts de construcción](#funcionamiento-de-los-scripts-de-construcción)
  - [Fase 1: Preparación (build_corpus.py)](#fase-1-preparación-build_corpuspy)
    - [Generación de Raw y Limpieza](#generación-de-raw-y-limpieza)
    - [División para procesamiento](#división-para-procesamiento)
  - [Fase 2: Curación (fineweb_curation.py)](#fase-2-curación-fineweb_curationpy)
  - [Fase 3: Finalización (finalize_build_corpus.py)](#fase-3-finalización-finalize_build_corpuspy)
    - [Unificación y conteo de tokens](#unificación-y-conteo-de-tokens)
    - [Actualización de metadatos](#actualización-de-metadatos)
- [Ejecución del pipeline](#ejecución-del-pipeline)

---

# Funcionamiento de los scripts de construcción

El proceso de "Construcción de corpus" orquesta la transformación de datasets individuales dispersos en un único corpus unificado, limpio y validado. Este proceso se divide en tres fases secuenciales gestionadas por scripts específicos.

## Fase 1: Preparación (build_corpus.py)

El script [``build_corpus.py``](/data/llms/scripts/corpora/build_corpus.py) tiene como objetivo principal la creación de la primera versión del corpus ("raw") y su preparación para las etapas de curación masiva. Este script centraliza la lógica de rutas mediante la función ``get_paths``, que gestiona automáticamente el versionado de directorios y ficheros basándose en los argumentos de entrada (*name*, *domain*, *version*).

### Generación de Raw y Limpieza

El flujo comienza con la función ``build_raw_corpus``, que unifica múltiples datasets en un único archivo Parquet.
- Esta función lee el archivo de configuración ``info.json`` del corpus para identificar qué datasets lo componen.
- Utiliza **Polars** en modo *lazy* (``pl.scan_parquet``) para iterar sobre cada dataset fuente, estandarizando las columnas a ``id`` y ``text``, y añadiendo una columna de trazabilidad ``source_id``.
- Finalmente, concatena todos los *LazyFrames* y vuelca el resultado a disco ("raw corpus"), optimizando el uso de memoria mediante *streaming*.

Posteriormente, la función ``process_cleaning`` aplica reglas de normalización sobre el texto unificado.
- Se carga el corpus "raw" y se aplica la lógica de limpieza definida en ``clean_text_logic`` mediante ``map_elements``.
- Las reglas de limpieza incluyen:
  1. **Eliminación de saltos de línea internos**: Se detectan y eliminan saltos de línea que rompen oraciones (aquellos no precedidos por puntuación terminal).
  2. **Normalización de espaciado**: Se reducen múltiples saltos de línea consecutivos a uno solo y se limpian espacios redundantes alrededor de los saltos.
  3. **Limpieza de ruido numérico**: Se eliminan líneas que contienen únicamente números aislados al inicio del texto.

### División para procesamiento

Para facilitar el procesamiento paralelo en la siguiente fase (DataTrove), la función ``split_corpus`` divide el corpus limpio en fragmentos manejables.
- Calcula el número de filas por parte basándose en la configuración global (``config['build']['parts']``).
- Utiliza la funcionalidad *slice* de Polars (operación *zero-copy*) para generar sub-datasets rápidos.
- Exporta cada fragmento en dos formatos simultáneamente:
  1. **Parquet**: Para almacenamiento eficiente y validaciones rápidas.
  2. **JSONL (NDJSON)**: Formato requerido por las herramientas de curación de texto como DataTrove.

## Fase 2: Curación (fineweb_curation.py)

Esta fase intermedia procesa los archivos JSONL generados anteriormente aplicando filtros de calidad y deduplicación.

> **Nota:** La documentación detallada de este proceso se encuentra disponible en: [process_curation.md](/documentation/data/llms/corpora/process_curation.md).

## Fase 3: Finalización (finalize_build_corpus.py)

El script [``finalize_build_corpus.py``](/data/llms/scripts/corpora/finalize_build_corpus.py) consolida los resultados de la curación y genera las estadísticas finales del corpus. Su objetivo es transformar la salida dispersa de la fase de curación en un entregable final (Parquet único) y enriquecer sus metadatos.

### Unificación y conteo de tokens

La función ``merge_jsonl_to_parquet`` reconstruye el corpus final a partir de los fragmentos procesados.
- Escanea el directorio de salida de DataTrove (archivos ``.jsonl.gz``) utilizando ``read_jsonl_gz_folder``.
- Descomprime y lee cada archivo, unificándolos en un único DataFrame de Polars.
- Escribe el resultado como el archivo Parquet definitivo del corpus versionado.

Una vez unificado, la función ``count_tokens`` audita el volumen del corpus.
- Utiliza la clase utilitaria ``TokenManager`` para añadir una columna de conteo de tokens a cada instancia del texto.
- Realiza una agregación (*group_by*) por ``source_id`` para calcular:
  1. El total de tokens aportados por cada dataset fuente.
  2. El número de instancias (documentos) por fuente.
- Genera un archivo CSV auxiliar (``token_count_csv``) que incluye tanto el desglose por fuente como una fila sumarizada con los totales absolutos del corpus.

### Actualización de metadatos

Finalmente, la función ``update_corpus_info`` inyecta las estadísticas calculadas en el archivo de definición del corpus (``info.json``).
- Lee el CSV de conteo generado en el paso anterior y calcula los porcentajes de contribución (tanto en tokens como en instancias) de cada dataset.
- Actualiza la estructura del JSON añadiendo campos clave como:
  - ``total-tokens``: Conteo exacto.
  - ``total-tokens-bill``: Conteo en miles de millones (para reporte rápido).
  - ``info``: Diccionario detallado con las estadísticas por dataset, ordenado por volumen de contribución.

# Ejecución del pipeline

El proceso completo de construcción se ejecuta secuencialmente mediante los scripts de Python, pasando siempre los argumentos de identificación del corpus.

Ejemplo de flujo de ejecución para un corpus llamado "legal-administrativo" del dominio "legal":

**Construcción y Preparación**:
   ```
   python build_corpus.py --name legal-administrativo --domain legal --version 1
   ```
   *Genera los archivos raw, limpia el texto y crea los splits JSONL.*

**Curación (DataTrove)**:
   ```
   python fineweb_curation.py ...
   ```
   *Procesa los splits y genera archivos .jsonl.gz limpios.*

**Finalización y Estadísticas**:
   ```
   python finalize_build_corpus.py --name legal-administrativo --domain legal --version 1
   ```
   *Unifica los resultados, cuenta tokens y actualiza el info.json.*

