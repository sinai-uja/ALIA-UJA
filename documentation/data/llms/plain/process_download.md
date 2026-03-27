Este documento establece las directrices y estándares para la descarga y preparación inicial de datasets dentro del proyecto de unificación del grupo de trabajo.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Procedimiento estandarizado de descarga de datos](#procedimiento-estandarizado-de-descarga-de-datos)
  - [Objetivo](#-objetivo)
  - [Herramientas y formatos recomendados](#️-herramientas-y-formatos-recomendados)
    - [Formato de almacenamiento: Parquet](#formato-de-almacenamiento-parquet)
    - [Formato en memoria: Arrow](#formato-en-memoria-arrow)
      - [Comparativa técnica: Parquet vs Arrow](#-comparativa-técnica-parquet-vs-arrow)
    - [Formato de las Tablas de Datos](#-formato-de-las-tablas-de-datos)
      - [Uso de Polars](#uso-de-polars)
  - [Uso de las Clases de Descarga](#-uso-de-las-clases-de-descarga)
  - [Creación de un Nuevo Proceso de Descarga](#-creación-de-un-nuevo-proceso-de-descarga)
    - [Estándar de Clases de Descarga](#estándar-de-clases-de-descarga)
    - [Estándar de Documentación de la Nueva Clase de Descarga](#estándar-de-documentación-de-la-nueva-clase-de-descarga)
  - [Recomendaciones adicionales](#-recomendaciones-adicionales)
  - [Lecturas recomendadas](#-lecturas-recomendadas)


---

# Procedimiento estandarizado de descarga de datos

Este documento proporciona una **guía técnica y operativa** para los desarrolladores encargados del proceso de descarga de datos dentro del flujo de trabajo del grupo. El objetivo es garantizar la **eficiencia, interoperabilidad y coherencia** en la adquisición y estructuración de datasets.

## Objetivo

Establecer un procedimiento unificado para:

* Descargar datasets de manera reproducible.
* Almacenar los datos de forma eficiente y estandarizada.
* Preparar los datos para su procesamiento posterior.


## Herramientas y formatos recomendados

### Formato de almacenamiento: Parquet

El formato `.parquet` se utilizará para **guardar los datos en disco**, garantizando:

* Almacenamiento eficiente mediante compresión.
* Representación estructurada y columnar.
* Compatibilidad con herramientas como **Spark**, **Dask**, **Polars**, entre otras.
* Posibilidad de fragmentación y particionamiento (ideal para datasets grandes).

> Recomendado para: almacenamiento persistente y distribución entre miembros del grupo.


### Formato en memoria: Arrow

Cuando los datos se carguen en memoria para procesamiento, se utilizará el formato **Apache Arrow**:

* Alta eficiencia en operaciones analíticas sobre columnas.
* Diseño optimizado para acceso en memoria (SIMD, caché).
* Interoperabilidad entre lenguajes (Python, Java, R...).
* Minimiza la serialización y copia de datos innecesarias.
* Integrado con bibliotecas como **PyArrow**, **Polars**, **Hugging Face datasets**, etc.

> Recomendado para: procesamiento intensivo en memoria, tareas de análisis, entrenamiento de modelos o transformación de datos.


#### 🧬 Comparativa técnica: Parquet vs Arrow

| Característica               | Parquet (disco)                          | Arrow (memoria)                                 |
| ---------------------------- | ---------------------------------------- | ----------------------------------------------- |
| **Ubicación**                | Disco                                    | Memoria RAM                                     |
| **Propósito principal**      | Almacenamiento persistente               | Procesamiento eficiente en tiempo real          |
| **Formato**                  | Columnar, con compresión y fragmentación | Columnar, en memoria optimizada                 |
| **Compresión**               | Snappy, Gzip, Zstd (intensiva)           | Mínima o nula (velocidad prioritaria)           |
| **Interoperabilidad**        | Alta (Python, Java, Spark, Hadoop...)    | Muy alta (representación en memoria compartida) |
| **Tipos de datos complejos** | Soportados (listas, estructuras, mapas)  | Soportados (listas, estructuras, mapas)         |
| **Rendimiento**              | Muy alto para consultas analíticas       | Muy alto para operaciones en memoria            |
| **Casos de uso típicos**     | Persistencia, intercambio entre sistemas | Carga, análisis y transformación rápida         |

### Formato de las Tablas de Datos

Los datasets deben estructurarse en formato tabular, siguiendo los estándares definidos en el documento [Estándar de Estructura de un Dataset](/documentation/data/llms/plain/standard_dataset_structure.md).

- **Directrices**:
    - Cada columna representa una variable específica.
    - Cada fila representa una observación o registro.
    - Los nombres de las columnas deben ser descriptivos y consistentes.
    - Se deben manejar adecuadamente los valores nulos o faltantes.

#### Uso de Polars

Se ha adoptado la librería **Polars** para la manipulación de datos debido a su rendimiento y eficiencia en el manejo de grandes volúmenes de datos.

- **Ventajas**:
    - Procesamiento paralelo y eficiente.
    - Soporte nativo para formatos Parquet y Arrow.
    - Interfaz intuitiva y expresiva para operaciones de datos.([Polars](https://docs.pola.rs/user-guide/misc/arrow/?utm_source=chatgpt.com "Arrow producer/consumer - Polars user guide"), [arXiv](https://arxiv.org/abs/2204.06074?utm_source=chatgpt.com "Skyhook: Towards an Arrow-Native Storage System"))


## Uso de las Clases de Descarga

```pgsql
📂 download
├─ ScraperBase.py
├─ CrawlerBase.py
├─ 📂 scrapers
└─ 📂 crawlers
```

1. **Importación**: Se debe importar la clase correspondiente al recurso de datos deseado.
    
2. **Inicialización**: Al instanciar la clase, se debe proporcionar:
    - Un identificador único para el nuevo dataset.
    - Los parámetros necesarios para la descarga, según la fuente de datos.
        
3. **Ejecución**: Invocar el método principal de la clase para iniciar la descarga y procesamiento de los datos.
    
Para detalles específicos sobre cada clase y sus parámetros, consultar la documentación asociada a cada proceso de descarga.

## Creación de un Nuevo Proceso de Descarga

### Estándar de Clases de Descarga

Al desarrollar un nuevo script para la descarga de datos, se deben seguir las siguientes pautas:

1. **Estructura de la Clase**:
    - Nombrar la clase de forma descriptiva, reflejando la metodología utilizada y la fuente de datos (si es exclusiva para ella).
    - Incluir métodos para:
        - Inicialización con parámetros necesarios.
        - Validación de parámetros.
        - Descarga de datos.
        - Procesamiento y transformación de datos.
        - Almacenamiento en formato Parquet.
            
2. **Manejo de Errores**:
    - Implementar mecanismos para capturar y registrar errores durante la descarga y procesamiento.
    - Proporcionar mensajes de error claros y descriptivos.([Polars](https://docs.pola.rs/py-polars/html/reference/api/polars.from_arrow.html?utm_source=chatgpt.com "polars.from_arrow — Polars documentation"))
        
3. **Configurabilidad**:
    - Permitir la configuración de parámetros como rutas de almacenamiento, filtros de datos, y opciones de conexión.
        

### Estándar de Documentación de la Nueva Clase de Descarga

Cada nueva clase debe ir acompañada de una documentación clara y completa que incluya:

- **Descripción General**: Objetivo y funcionalidad de la clase.
- **Parámetros de Entrada**: Listado y descripción de todos los parámetros requeridos y opcionales.
- **Ejemplo de Uso**: Código de ejemplo que demuestre cómo utilizar la clase.
- **Notas Adicionales**: Consideraciones especiales, limitaciones o dependencias.
    

La documentación debe integrarse en el repositorio del proyecto y enlazarse desde el documento principal de procesos de descarga.

## Recomendaciones adicionales

* **Fragmentación por tamaño**: Para datasets grandes, dividir en fragmentos manejables utilizando `row groups` en Parquet o `split datasets` en Arrow.
* **Scripts reutilizables**: Se recomienda almacenar los scripts de descarga en la carpeta `/scripts/download/` con nombres claros y documentación mínima.


## Lecturas recomendadas

* [Apache Arrow Documentation](https://arrow.apache.org/)
* [Apache Parquet Documentation](https://parquet.apache.org/)
* [PyArrow (Apache Arrow in Python)](https://arrow.apache.org/docs/python/)

