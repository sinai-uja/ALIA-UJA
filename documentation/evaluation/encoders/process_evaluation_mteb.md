# Evaluación de modelos encoders (Bi-encoders y Cross-encoders) basada en el framework MTEB

Scripts para evaluación homogénea de modelos de recuperación semántica (bi-encoders) y reordenación (cross-encoders) sobre conjuntos de evaluación locales del proyecto ALIA, utilizando el framework [MTEB](https://huggingface.co/spaces/mteb/leaderboard) como capa principal de evaluación.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

## Tabla de contenido

- [Descripción general](#descripción-general)
  - [Flujo general](#flujo-general)
- [Scripts principales](#scripts-principales)
  - [evaluation_static_metrics_biencoder.py](#evaluation_static_metrics_biencoderpy)
  - [evaluation_static_metrics_crossencoder.py](#evaluation_static_metrics_crossencoderpy)
  - [Utilidades y soporte](#utilidades-y-soporte)
- [Configuración](#configuración)
  - [config.yaml](#configyaml)
  - [Listas de modelos](#listas-de-modelos)
- [Ejecución](#ejecución)
  - [Bi-encoders](#bi-encoders)
  - [Cross-encoders](#cross-encoders)
  - [Argumentos comunes](#argumentos-comunes)
- [Arquitectura de evaluación](#arquitectura-de-evaluación)
  - [Personalización de MTEB](#personalización-de-mteb)
  - [Carga de modelos](#carga-de-modelos)
  - [Optimización para GPU](#optimización-para-gpu)
  - [Modo offline](#modo-offline)
- [Formatos de entrada y salida](#formatos-de-entrada-y-salida)
  - [Entrada](#entrada)
  - [Salida](#salida)
- [Estructura de datos esperada](#estructura-de-datos-esperada)
  - [Para Retrieval](#para-retrieval)
  - [Para STS](#para-sts)
  - [Para Reranking](#para-reranking)
- [Notas operativas](#notas-operativas)
- [Referencias](#referencias)

## Descripción general

El módulo implementa dos pipelines de evaluación especializados:

| Script | Tarea | Métrica principal |
|--------|-------|------------------|
| `evaluation_static_metrics_biencoder.py` | Retrieval, STS | NDCG@10, Spearman |
| `evaluation_static_metrics_crossencoder.py` | Reranking | NDCG@10 |

### Flujo general

1. **Carga de configuración** desde `config.yaml`
2. **Selección de modelos, dominios y datasets**
3. **Construcción dinámica de tareas** compatibles con MTEB
4. **Carga de modelos** (SentenceTransformer / CrossEncoder)
5. **Evaluación** mediante `mteb.evaluate(...)`
6. **Persistencia de resultados** (JSONL + CSV)

## Scripts principales

### `evaluation_static_metrics_biencoder.py`

Evalúa bi-encoders en dos tipos de tarea:

- **Retrieval**: Recuperación semántica de documentos
  - Carga datos JSONL locales con esquemas flexibles
  - Construye corpus, queries y relevant_docs
  - Reporta: NDCG, MAP, MRR, Recall, Precision
  
- **STS**: Similitud textual semántica
  - Requiere columnas: sentence1, sentence2, score
  - Reporta: cosine_spearman, cosine_pearson, euclidean_spearman, manhattan_spearman

### `evaluation_static_metrics_crossencoder.py`

Evalúa cross-encoders en:

- **Reranking**: Reordenación de candidatos
  - Carga datos de formatos preconstruidos (parquet/json) o JSONL
  - Genera automáticamente listas de candidatos si no existen
  - Reporta: NDCG, MAP, MRR, Recall, Precision (en k=1,3,5,10,20)

### Utilidades y soporte

- `_download_biencoder.py`: Preparación de datasets para bi-encoders
- `_download_reranking.py`: Preparación de datasets para cross-encoders
- `evaluation_format_data.py`: Formatos y normalización de datos
- `launcher_*.sh`: Scripts de orquestación para ejecución batch

## Configuración

### `config.yaml`

Archivo centralizado que define:

```yaml
paths:
  path-root-data: <PATH_TO_DATA_ROOT>/data/encoders/data
  path-root-evaluation: <PATH_TO_EVALUATION_ROOT>/evaluation/encoder
  path-dir-models-biencoders: <PATH_TO_MODELS>/biencoders/
  path-dir-models-crossencoder: <PATH_TO_MODELS>/crossencoders/
  # ... rutas de datos, modelos, predicciones y resultados

available-domains:
  - general
  - legal
  - biomedical
  - heritage

available-eval-sets:
  Retrieval:
    {domain}: [lista de datasets disponibles]
  Reranking:
    {domain}: [lista de datasets disponibles]

model-configurations:
  DEFAULT:
    encode_kwargs: { batch_size: 16 }
  "BAAI/bge-m3":
    encode_kwargs: { batch_size: 16 }
    prompts:
      query: "Represent this sentence for searching relevant passages: "
      document: ""
  # ... configuración específica de modelos
```

Para usar el archivo como plantilla:

```bash
cp config.yaml config.yaml.example
# Editar config.yaml.example con rutas ficticias
```

### Listas de modelos

- `biencoder_model_list.txt.example`: Nombres de bi-encoders a evaluar
- `crossencoder_model_list.txt.example`: Nombres de cross-encoders a evaluar

## Ejecución

### Bi-encoders

```bash
# Evaluar un único modelo
python evaluation_static_metrics_biencoder.py \
  --model_name "BAAI/bge-small-en-v1.5" \
  --domain legal \
  --dataset "ALIA-1500-legal-Retrieval"

# Evaluar todos los modelos
python evaluation_static_metrics_biencoder.py \
  --model_name all \
  --domain legal

# Forzar reevaluación
python evaluation_static_metrics_biencoder.py \
  --model_name "BAAI/bge-small-en-v1.5" \
  --domain legal \
  --force_run
```

### Cross-encoders

```bash
# Evaluar un único modelo
python evaluation_static_metrics_crossencoder.py \
  --model_name "ms-marco-MiniLM-L-12-v2" \
  --domain legal \
  --dataset "ALIA-650-legal-Reranking"

# Evaluar todos los modelos
python evaluation_static_metrics_crossencoder.py \
  --model_name all \
  --domain legal
```

### Argumentos comunes

- `--model_name`: Nombre del modelo o `all` para iterar lista
- `--domain`: Dominio de evaluación (general, legal, biomedical, heritage)
- `--dataset`: Dataset específico (opcional, usa config.yaml por defecto)
- `--force_run`: Ignora caché y reevalúa

## Arquitectura de evaluación

### Personalización de MTEB

El proyecto adapta MTEB mediante clases personalizadas:

- **`ALIAAbsTaskRetrieval`**: Retrieval con soporte para datasets locales
- **`ALIAAbsTaskSTS`**: Similitud semántica textual
- **`ALIAAbsTaskReranking`**: Reranking con generación automática de candidatos

Estas clases:
- Generan dinámicamente metadatos (TaskMetadata)
- Transforman datos locales (JSONL/Parquet) al formato MTEB v2
- Soportan múltiples esquemas de columnas heredados

### Carga de modelos

**Bi-encoders**:
- Búsqueda en directorio principal, luego alternativo
- Reutilización de versiones pre-convertidas a SentenceTransformer
- Aplicación de prompts específicos por modelo

**Cross-encoders**:
- Resolución local desde directorios configurados
- Manejo defensivo de tokenizers (asignación de pad_token si falta)
- Inicialización con dtype y device adaptados

### Optimización para GPU

- Inferencia en `float16` (compatible con RTX)
- Autocast automático en CUDA
- Limpieza explícita de memoria CUDA al finalizar
- Batch size configurable por modelo

### Modo offline

Los scripts fuerzan ejecución offline mediante:

```bash
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
```

Esto garantiza que no hay descargas en tiempo de ejecución.

## Formatos de entrada y salida

### Entrada

**Datos de evaluación**:
- Archivos JSONL locales en rutas configuradas
- Formato parquet/json preconstruido para reranking
- Soporte para múltiples esquemas de columnas

**Modelos**:
- Bi-encoders en formato SentenceTransformer
- Cross-encoders en formato SentenceTransformers
- Configuración de prompts e hiperparámetros en config.yaml

### Salida

Por cada ejecución se generan:

```
results/
├── {task_type}/
│   └── {domain}/
│       └── {model_name}/
│           ├── ALIA_{domain}_{model_name}_{eval_set}_results.jsonl
│           └── ALIA_{domain}_{model_name}_{eval_set}_results.csv
predictions/
└── {task_type}/
    └── {domain}/
        └── {model_name}/
            └── ALIA_{domain}_{model_name}_{eval_set}_predictions.json
```

**Formato JSONL** (detalle completo):
```json
{
  "task_name": "ALIA_legal_model_name_dataset",
  "main_score": 0.5234,
  "scores": {...},
  "evaluation_time": 123.45
}
```

**Formato CSV** (resumen):
```
task_name, main_score, ndcg_at_1, ndcg_at_3, ndcg_at_5, ndcg_at_10, map, mrr, recall_at_k, precision_at_k
```

## Estructura de datos esperada

### Para Retrieval

```json
{
  "source": "dataset_name",
  "id": "doc_id",
  "query": "pregunta o consulta",
  "passage": "texto del documento"
}
```

Variantes de esquema soportadas:
- `source_id`, `id_document`, `id_chunk`, `query`, `passage`
- `source_id`, `id_document`, `id_passage`, `query`, `passage`

### Para STS

```json
{
  "sentence1": "texto 1",
  "sentence2": "texto 2",
  "score": 0.85
}
```

### Para Reranking

Formato preconstruido (parquet):
- `corpus.parquet`
- `queries.parquet`
- `relevant_docs.json`
- `top_ranked.json`

O formato JSONL que se transforma automáticamente.

## Notas operativas

- **Caché en memoria**: Los modelos se reutilizan entre evaluaciones consecutivas
- **Verificación de rutas**: Se validan existencia y permisos antes de cada ejecución
- **Recuperación ante interrupciones**: Detecta artefactos previos y permite reanudar
- **Logging completo**: Trazabilidad de cada fase (carga, evaluación, persistencia)
- **Seed reproducible**: Generación de candidatos con semilla fija en config.yaml

## Referencias

- [MTEB Benchmark](https://huggingface.co/spaces/mteb/leaderboard)
- [SentenceTransformers](https://www.sbert.net/)
- [CrossEncoder](https://www.sbert.net/docs/cross-encoders/ce-finetuning.html)
