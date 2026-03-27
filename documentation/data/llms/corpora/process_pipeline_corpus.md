# Pipeline de construcción de corpus para LLMs (ingesta, limpieza, curación, enriquecimiento y downsampling)

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [1. Objetivo y alcance](#1-objetivo-y-alcance)
- [2. Estructura de scripts](#2-estructura-de-scripts)
- [3. Requisitos](#3-requisitos)
- [4. Configuración](#4-configuración)
- [5. Ejecución del pipeline](#5-ejecución-del-pipeline)
- [6. Descripción de pasos del pipeline](#6-descripción-de-pasos-del-pipeline)
- [7. Entradas y salidas por paso](#7-entradas-y-salidas-por-paso)
- [8. Downsampling: tipos de tareas](#8-downsampling-tipos-de-tareas)
- [9. Ejemplos de uso](#9-ejemplos-de-uso)
- [10. Scripts auxiliares y ejecución en cluster](#10-scripts-auxiliares-y-ejecución-en-cluster)
- [11. Buenas prácticas y resolución de problemas](#11-buenas-prácticas-y-resolución-de-problemas)
---

## 1. Objetivo y alcance

Este directorio contiene el pipeline completo para construir un corpus curado a partir de datasets procesados por dominio (`legal`, `biomedical`, `heritage`, etc.), listo para tareas de entrenamiento y experimentación de LLMs.

El flujo general implementa:

1. Construcción inicial del corpus a partir de múltiples datasets.
2. Limpieza de texto.
3. División en partes para procesamiento paralelo.
4. Curación avanzada con DataTrove (idioma, deduplicación, calidad).
5. Enriquecimiento con metadatos.
6. Generación de variantes de corpus mediante downsampling.

---

## 2. Estructura de scripts

- `corpora_manager.py`: orquestador principal del pipeline.
- `corpora_base.py`: clase abstracta base (`CorporaStep`) para normalizar configuración y rutas.
- `corpora_step_initial.py`: crea `initial` (unión de datasets de entrada).
- `corpora_step_clean.py`: aplica limpieza textual y calcula tokens.
- `corpora_step_split.py`: divide el corpus limpio en subdatasets parquet/jsonl.
- `corpora_step_datatrove.py`: ejecuta curación con DataTrove y recompone salida final.
- `corpora_step_complete.py`: enriquece con metadatos y unifica mappings.
- `corpora_step_downsampling.py`: genera subconjuntos por objetivos de tokens/documentos.
- `corpora_step_datatrove_download_models.py`: descarga modelos para modo offline de DataTrove.
- `launcher_parent.sh` y `launcher_job.sh`: envoltorios para ejecución en SLURM.
- `config.yaml.example`: plantilla de configuración.
- `_dataset_mapping.csv` y `_feature_mapping.csv`: mappings para normalización de datasets y columnas.

---

## 3. Requisitos

- Python 3.12+ (recomendado).
- Dependencias principales del pipeline:
  - `polars`
  - `beautifulsoup4`
  - `tqdm`
  - `datatrove`
  - `huggingface_hub`
  - `requests`
- Utilidades internas del proyecto en `utils/utils_alia.py`.
- Para ejecución en cluster: entorno SLURM + entorno virtual/conda configurado.

> Nota: `corpora_step_datatrove.py` está preparado para trabajo en modo offline usando modelos locales de identificación de idioma.

---

## 4. Configuración

### 4.1 Archivo de configuración

1. Copiar `config.yaml.example` a `config.yaml` en este mismo directorio.
2. Ajustar rutas de `paths` según la infraestructura.

Campos importantes:

- `paths.path-root-data`: raíz de datasets procesados por dominio.
- `paths.path-root-corpora`: raíz donde se guardarán los corpora generados.
- `pipeline.steps`: orden de ejecución (`initial`, `clean`, `split`, `datatrove`, `complete`, `downsampling`).
- Secciones específicas por paso: `clean`, `split`, `datatrove`, `completion`, `downsampling`.

### 4.2 Mappings

- `_dataset_mapping.csv`: mapea IDs de dataset originales a IDs unificados.
- `_feature_mapping.csv`: mapea nombres de columnas originales a nombres normalizados.

Estos archivos se usan en `complete` para homogeneizar fuentes y metadatos.

---

## 5. Ejecución del pipeline

El punto de entrada recomendado es `corpora_manager.py`.

Parámetros CLI:

- `--name` (obligatorio): nombre del corpus.
- `--domain` (obligatorio): dominio del corpus.
- `--version` (opcional, `-1` por defecto).
- `--single_step` (opcional): ejecuta un único paso.
- `--start_step` y `--end_step` (opcionales): ejecuta rango de pasos.
- `--force` (opcional): reprocesa salidas existentes en pasos que lo soportan.

Lógica de ejecución:

- Sin filtros de pasos: ejecuta todo el pipeline.
- `single_step`: solo ese paso.
- `start_step/end_step`: ejecuta subrango validando orden.

---

## 6. Descripción de pasos del pipeline

### 6.1 `initial`

- Lee el fichero de información del corpus (`ALIA-{name}.json` o versionado).
- Recupera la lista `datasets`.
- Carga `dataset.parquet` por dataset desde la ruta del dominio.
- Selecciona columnas base (`id`, `text`) y añade `source_id`.
- Concatena y guarda:
  - corpus inicial en parquet
  - corpus inicial en jsonl
- Genera métricas de tokens y actualiza info del corpus.

### 6.2 `clean`

Aplica transformaciones configurables sobre la columna de texto:

- eliminación de `#`
- eliminación de patrones de imágenes markdown `![...](...)`
- normalización de saltos de línea múltiples
- normalización de cabeceras tipo Wikipedia (`== título ==`)
- inserción de `.` antes de salto de línea en ciertos casos

Después, recalcula columna `tokens`, guarda parquet/jsonl y actualiza métricas.

### 6.3 `split`

- Divide el corpus limpio en `N` partes (`split.parts`).
- Exporta cada parte a:
  - `subdatasets_parquet/archivo_parte_i.parquet`
  - `subdatasets_jsonl/archivo_parte_i.jsonl`

Este paso facilita paralelismo y procesamiento posterior con DataTrove.

### 6.4 `datatrove`

Pipeline secuencial de curación:

1. **Language filter** (`es`) con umbral configurable.
2. **Deduplicación MinHash**:
   - firmas
   - buckets
   - clustering
   - filtrado final de duplicados
3. **Quality filtering**:
   - `GopherRepetitionFilter`
   - `FineWebQualityFilter`
   - `GopherQualityFilter`
4. **Formatters**:
   - `FTFYFormatter`
   - `PIIFormatter`
   - `SymbolLinesFormatter`

Salida intermedia: JSONL GZ curados.
Salida final del paso: unificación a parquet/jsonl `datatrove` y actualización de métricas.

### 6.5 `complete`

- Carga corpus `datatrove`.
- Aplica mapping de `source_id` si existe `_dataset_mapping.csv`.
- Para cada dataset fuente:
  - carga parquet original del dataset
  - mapea columnas con `_feature_mapping.csv`
  - selecciona features de metadatos por dominio (`completion.features.<domain>`)
  - construye columna `metadata` (JSON serializado)
  - recalcula/añade tokens
  - guarda parquet enriquecido por dataset
- Agrega todos los parquets enriquecidos en un único corpus enriquecido parquet/jsonl.

### 6.6 `downsampling`

- Lee corpus enriquecido (o archivo especial si se configura `special-input-file`).
- Ejecuta lista de tareas declaradas en `downsampling.plain-text.tasks`.
- Cada tarea genera:
  - corpus downsampleado (`.parquet` y `.jsonl`)
  - CSV de estadísticos/tokens asociado

---

## 7. Entradas y salidas por paso

| Paso | Entrada principal | Salida principal |
|---|---|---|
| `initial` | `dataset.parquet` de cada dataset fuente | `ALIA-{name}-initial.parquet/jsonl` |
| `clean` | `ALIA-{name}-initial.parquet` | `ALIA-{name}-clean.parquet/jsonl` |
| `split` | `ALIA-{name}-clean.parquet` | `subdatasets_parquet/*`, `subdatasets_jsonl/*` |
| `datatrove` | `subdatasets_jsonl/*` | `ALIA-{name}-datatrove.parquet/jsonl` |
| `complete` | `ALIA-{name}-datatrove.parquet` + mappings | `ALIA-{name}-enriched.parquet/jsonl` |
| `downsampling` | `ALIA-{name}-enriched.parquet` | `ALIA-{name}-<task>-<sources>-<target>.parquet/jsonl` |

Además, en cada paso se generan ficheros de conteo/estadística en `stats/`.

---

## 8. Downsampling: tipos de tareas

Las tareas disponibles (según implementación actual) son:

1. `tokens_general_stratified`
   - objetivo global de tokens, manteniendo proporción por fuente.
2. `tokens_general_equitative`
   - objetivo de tokens por fuente (implementación pendiente en código actual).
3. `tokens_per_source`
   - mapping explícito de tokens por fuente.
4. `documents_general_stratified`
   - objetivo global de documentos, manteniendo proporción por fuente.
5. `documents_general_equitative`
   - objetivo de documentos por fuente.
6. `documents_per_source`
   - mapping explícito de documentos por fuente.

El nombre del fichero de salida incorpora automáticamente tipo de tarea, número de fuentes y objetivo.

---

## 9. Ejemplos de uso

### 9.1 Ejecutar todo el pipeline

```bash
python data/llms/scripts/corpora/corpora_manager.py \
  --name biomedical \
  --domain biomedical
```

### 9.2 Ejecutar un solo paso

```bash
python data/llms/scripts/corpora/corpora_manager.py \
  --name biomedical \
  --domain biomedical \
  --single_step clean
```

### 9.3 Ejecutar un rango de pasos

```bash
python data/llms/scripts/corpora/corpora_manager.py \
  --name biomedical \
  --domain biomedical \
  --start_step split \
  --end_step complete
```

### 9.4 Forzar reprocesado

```bash
python data/llms/scripts/corpora/corpora_manager.py \
  --name biomedical \
  --domain biomedical \
  --single_step downsampling \
  --force
```

---

## 10. Scripts auxiliares y ejecución en cluster

### 10.1 Descarga de modelos DataTrove (offline)

```bash
python data/llms/scripts/corpora/corpora_step_datatrove_download_models.py \
  --model_dir /ruta/a/utils/datatrove
```

Descarga modelos `lid.176.bin` y `lid.176.ftz` y genera `setup_env.sh`.

### 10.2 Ejecución en SLURM

- `launcher_parent.sh`: parsea argumentos, define logs y envía job con `sbatch`.
- `launcher_job.sh`: activa entorno y ejecuta `corpora_manager.py` con `srun`.

Ejemplo:

```bash
bash data/llms/scripts/corpora/launcher_parent.sh \
  --name biomedical \
  --domain biomedical \
  --end_step downsampling
```

> Importante: revisar `BASE_SCRIPT_PATH` en `launcher_job.sh`.

---

## 11. Buenas prácticas y resolución de problemas

- Mantener `config.yaml` versionado por entorno (sin credenciales ni rutas sensibles).
- Verificar que existe el JSON de información del corpus y que contiene `datasets`.
- Si falta JSONL pero existe parquet en un paso, el pipeline intentará regenerarlo.
- Para DataTrove en entornos sin Internet, preparar previamente modelos offline.
- Usar `--start_step`/`--end_step` para reanudar pipelines largos.
- Usar `--force` solo cuando se necesite recomputación de salidas existentes.
