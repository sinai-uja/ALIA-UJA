Para cada dataset descargado y tratado en el marco del Proyecto ALIA, se debe generar la documentación descriptiva correspondiente que incluya sus metadatos estructurados.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

## Tabla de contenido
- [Documentación de Metadatos para Conjuntos de Datos](#documentación-de-metadatos-para-conjuntos-de-datos)
  - [Plan de Metadatos](#plan-de-metadatos)
  - [Ontología de Metadatos](#ontología-de-metadatos)

---

# Documentación de Metadatos para Conjuntos de Datos

## Plan de Metadatos

El modelo de metadatos utilizado se basa en [Dublin Core](https://www.dublincore.org/), un estándar ampliamente reconocido para la descripción de recursos de información. Este modelo propone un conjunto de 15 elementos básicos, ampliables mediante los términos de [DCMI Metadata Terms](https://www.dublincore.org/specifications/dublin-core/dcmi-terms/), lo que permite representar de manera sencilla, flexible y estandarizada los recursos documentales.

**Ventajas de utilizar Dublin Core en datasets para entrenamiento de LLMs:**
* **Interoperabilidad:** Permite que los metadatos puedan ser interpretados y reutilizados por diferentes herramientas y plataformas.
* **Simplicidad:** Facilita la descripción de recursos de forma eficiente.
* **Estándar internacional:** Reconocido por la norma ISO 15836.
* **Flexibilidad:** Las etiquetas son opcionales, repetibles y no requieren un orden fijo.
* **Amplio uso:** Adoptado en entornos académicos, bibliotecas, instituciones gubernamentales y sector empresarial.

---

## Ontología de Metadatos

La estructura de metadatos definida se organiza a partir de tres espacios de nombres:

* `dc`: Dublin Core básico.
* `dcterms`: Dublin Core Metadata Terms.
* `alia`: Vocabulario extendido específico del proyecto ALIA.

**Definiciones clave**

* Se utiliza **`dataset`** como término para designar un conjunto de datos procesados con valor lingüístico.
* Se emplea **`corpus`** para referirse a datos en bruto o con mínimo tratamiento.

**Elementos de la ontología**

* `alia:dataset`: Nodo raíz del archivo de metadatos.
* `dc:identifier`: ID del dataset.
* `dc:title`: Título del recurso.
* `dc:description`: Descripción general del contenido.
* `dcterms:subject`: Dominio temático (`biomedical`, `legal/administrative`, `heritage`).
* `dc:relation`: Recursos relacionados o fuentes agregadas.
* `dc:source`: Fuente primaria original.
* `dc:date`: Fecha de publicación del recurso original.
* `dcterms:coverage`: Periodo de tiempo que abarcan los datos.
* `dcterms:provenance`: Estado de curación (`raw`, `processed`, `curated`).
* `dc:publisher`: Entidad responsable de la publicación.
* `dcterms:hasVersion`: Versión del recurso.
* `alia:tasks`: Aplicaciones posibles (según tareas de HuggingFace).
* `dcterms:license`: Licencia legal del recurso.
* `dc:rights`: Información sobre los derechos de uso.
* `dcterms:bibliographicCitation`: Referencia bibliográfica asociada (si aplica).
* `alia:processing`: Detalles del procesamiento del dataset.
  * `alia:downloading`: Método de descarga (API, scraping, etc.).
  * `alia:filtering`: Filtros aplicados.
  * `alia:curation`: Procesos de limpieza y corrección de errores.
* `dc:language`: Idioma(s) del recurso.
* `dc:format`: Formato del archivo (e.g., `"Data: parquet"`, `"Metadata: YAML"`).
* `alia:textEncoding`: Codificación del contenido textual.
* `alia:level`: Nivel de granularidad (`document`, `paragraph`, `sentence`).
* `dcterms:extent`: Tamaño en MB del recurso.
* `alia:instances`: Número de instancias.
* `alia:tokens`: Número total de tokens.
* `alia:features`: Atributos presentes en el dataset.
  * `alia:feature`: Atributo individual.
    * `dc:identifier`: Identificador del atributo.
    * `dc:description`: Descripción del atributo.
    * `dc:type`: Tipo de dato o categoría.
* `alia:splits`: Particiones del dataset (`train`, `test`, `validation`).
  * `alia:split`: Partición específica.
    * `dc:identifier`: Identificador.
    * `dcterms:extent`: Tamaño (MB).
    * `alia:instances`: Número de instancias.
    * `alia:tokens`: Número de tokens.

```pgsql
alia:dataset
├── dc:identifier
├── dc:title
├── dc:description
├── dcterms:subject
├── dc:relation
├── dc:source
├── dc:date
├── dcterms:coverage
├── dcterms:provenance
├── dc:publisher
├── dcterms:hasVersion
├── alia:tasks
├── dcterms:license
├── dc:rights
├── dcterms:bibliographicCitation
├── alia:processing
│   ├── alia:downloading
│   ├── alia:filtering
│   └── alia:curation
├── dc:language
├── dc:format
├── alia:textEncoding
├── alia:level
├── dcterms:extent
├── alia:instances
├── alia:tokens
├── alia:features
│   ├── alia:feature
│   │   ├── dc:identifier
│   │   ├── dc:description
│   │   └── dc:type
├── alia:splits
│   ├── alia:split
│   │   ├── dc:identifier
│   │   ├── dcterms:extent
│   │   ├── alia:instances
│   │   └── alia:tokens
```