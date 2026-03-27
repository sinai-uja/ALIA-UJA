# Proceso de curación con DataTrove (paso `datatrove` del pipeline de corpus)

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [1. Objetivo y alcance](#1-objetivo-y-alcance)
- [2. Script implementado y contexto](#2-script-implementado-y-contexto)
- [3. Flujo real del paso `datatrove`](#3-flujo-real-del-paso-datatrove)
- [4. Etapas de procesamiento](#4-etapas-de-procesamiento)
- [5. Entradas, salidas y trazabilidad](#5-entradas-salidas-y-trazabilidad)
- [6. Ejecución y parámetros](#6-ejecución-y-parámetros)
- [7. Configuración](#7-configuración)
- [8. Consideraciones operativas](#8-consideraciones-operativas)
---

## 1. Objetivo y alcance

Este documento describe el comportamiento real del paso `datatrove` tal y como está implementado en el script [data/llms/scripts/corpora/corpora_step_datatrove.py](data/llms/scripts/corpora/corpora_step_datatrove.py).

El objetivo del paso es convertir un corpus dividido en partes JSONL en un corpus curado en español, deduplicado, filtrado por calidad y exportado en formatos parquet y jsonl para su uso en etapas posteriores.

---

## 2. Script implementado y contexto

El paso se ejecuta como una clase `CorporaDatatrove`, que hereda de `CorporaStep` y forma parte del pipeline general de construcción de corpus.

Su posición en la cadena de procesamiento es:

1. `initial`
2. `clean`
3. `split`
4. `datatrove` ← **este documento**
5. `complete`
6. `downsampling`

La entrada esperada del paso `datatrove` es el directorio de partes JSONL generado por `split`.

---

## 3. Flujo real del paso `datatrove`

La ejecución sigue esta secuencia:

1. Inicialización del modo offline para recursos de detección de idioma.
2. Construcción de rutas de entrada/salida.
3. Comprobación de salida final existente (salto de ejecución si ya existe parquet final).
4. Filtro de idioma (`LanguageFilter`).
5. Deduplicación MinHash (firmas, buckets, clustering y filtrado final).
6. Filtros de calidad y formateo.
7. Unión de JSONL comprimidos resultantes (`.jsonl.gz`) en un único corpus.
8. Cálculo de estadísticas de tokens y actualización del fichero de información del corpus.

---

## 4. Etapas de procesamiento

### 4.1 Preparación offline de modelos

Antes de lanzar los pipelines de DataTrove, el script:

- define `HF_HOME` en un directorio local de modelos;
- verifica la existencia del modelo FastText `lid.176.bin` en la ruta local esperada;
- copia el binario al `asset_dir` usado por DataTrove/HuggingFace cache;
- crea el fichero marcador `.completed`.

Si no existe el modelo fuente local, el proceso finaliza con error.

### 4.2 Filtro de idioma

Se lanza un `LocalPipelineExecutor` con:

- `JsonlReader` sobre las partes de entrada;
- `LanguageFilter` restringido a español (`es`) y umbral configurable;
- `JsonlWriter` para documentos válidos;
- `JsonlWriter` adicional para excluidos.

Resultado: directorio intermedio `01.es` y traza de excluidos en `01.filtered-out`.

### 4.3 Deduplicación MinHash

La deduplicación se ejecuta en cuatro sub-etapas:

1. **Signatures** (`MinhashDedupSignature`)
2. **Buckets** (`MinhashDedupBuckets`)
3. **Cluster** (`MinhashDedupCluster`, con `tasks=1`)
4. **Filter** (`MinhashDedupFilter`)

Resultado: directorio deduplicado `02.deduplicated` y documentos descartados por duplicado en `02.removed_duplicates`.

### 4.4 Filtros de calidad y formateo

Sobre la salida deduplicada se aplican, en orden:

- `GopherRepetitionFilter`
- `FineWebQualityFilter`
- `GopherQualityFilter`
- `FTFYFormatter`
- `PIIFormatter`
- `SymbolLinesFormatter` (elimina líneas con símbolo `|`)

Los descartes se guardan por tipo de filtro en rutas separadas (`03.removed_*`) y la salida curada va a `03.cleaned`.

### 4.5 Unificación final

El script recorre los `*.jsonl.gz` de `03.cleaned`, los descomprime, concatena en memoria con Polars y exporta:

- corpus final `datatrove` en parquet;
- corpus final `datatrove` en jsonl.

Después, computa tokens y actualiza el fichero de información del corpus para el paso `datatrove`.

---

## 5. Entradas, salidas y trazabilidad

### Entradas principales

- Directorio de entrada: partes JSONL producidas por `split`.

### Salidas principales

- Directorio de trabajo DataTrove (intermedios y logs).
- Directorio de corpus limpio final (`03.cleaned`).
- Fichero final parquet del paso `datatrove`.
- Fichero final jsonl del paso `datatrove`.
- CSV de conteo de tokens del paso.

### Trazabilidad de descartes

Cada bloque de filtrado tiene `exclusion_writer`, por lo que los documentos excluidos se conservan en rutas específicas y auditables.

---

## 6. Ejecución y parámetros

El script expone argumentos CLI:

- `--name`: nombre del corpus.
- `--domain`: dominio del corpus.
- `--version`: versión del corpus (por defecto `-1`).
- `--tasks`: paralelismo para ejecutores locales (por defecto `25`, salvo clustering MinHash que fija `1`).

Comportamiento relevante:

- si el parquet final del paso ya existe, el script no reprocesa y solo asegura jsonl + métricas;
- el paso está diseñado para integrarse en el orquestador global del pipeline.

---

## 7. Configuración

La configuración del paso no se define en este documento. Se debe consultar directamente el archivo de referencia:

- [data/llms/scripts/corpora/config.yaml.example](data/llms/scripts/corpora/config.yaml.example)

En concreto, los bloques aplicables a `datatrove` son:

- `datatrove.language-filter`
- `datatrove.deduplication`
- `datatrove.quality-filter`
- `paths` asociados a entradas/salidas de este paso

---

## 8. Consideraciones operativas

- Verificar previamente la disponibilidad de modelos offline para detección de idioma.
- Ajustar `--tasks` según CPU/RAM y tamaño de corpus.
- Mantener revisión de los directorios `03.removed_*` para auditoría de calidad.
- En ejecuciones repetidas, revisar si se desea reutilizar salida existente o forzar reprocesado desde pasos anteriores.