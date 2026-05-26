# Evaluación de modelos encoders (Bi-encoders) basada en LLM-as-judge con el framework RAGAS

Scripts para preparar, recuperar, formatear y evaluar modelos de recuperación semántica con RAGAS en el proyecto ALIA. El flujo se apoya en un LLM-as-judge para las métricas de RAGAS, en embeddings OpenAI-compatible para la recuperación y en una secuencia de pasos intermedios que permiten reutilizar artefactos, reanudar ejecuciones y evaluar por dominios y muestras.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

## Tabla de contenido

- [Descripción general](#descripción-general)
	- [Flujo general](#flujo-general)
- [Scripts principales](#scripts-principales)
	- [step_1_data.py](#step_1_datapy)
	- [step_2_database.py](#step_2_databasepy)
	- [step_3_compute_retrieval.py](#step_3_compute_retrievalpy)
	- [step_4_format_for_ragas.py](#step_4_format_for_ragappy)
	- [step_5_run_ragas.py](#step_5_run_ragapy)
	- [Utilidades y soporte](#utilidades-y-soporte)
- [Configuración](#configuración)
	- [config.yaml.example](#configyamlexample)
	- [schemas.yaml](#schemasyaml)
- [Ejecución](#ejecución)
	- [Flujo completo](#flujo-completo)
	- [Pasos individuales](#pasos-individuales)
	- [launcher.sh](#launchersh)
	- [launcher_parent.sh](#launcher_parentsh)
	- [Argumentos comunes](#argumentos-comunes)
- [Arquitectura de evaluación](#arquitectura-de-evaluación)
	- [APIs y modelos](#apis-y-modelos)
	- [Evaluación incremental](#evaluación-incremental)
	- [Caché, checkpoints y reintentos](#caché-checkpoints-y-reintentos)
	- [Normalización y recuperación](#normalización-y-recuperación)
- [Formatos de entrada y salida](#formatos-de-entrada-y-salida)
	- [Entrada](#entrada)
	- [Salida](#salida)
- [Estructura de datos esperada](#estructura-de-datos-esperada)
	- [Triplets de origen](#triplets-de-origen)
	- [Ficheros intermedios](#ficheros-intermedios)
	- [Entrada RAGAS](#entrada-ragas)
- [Notas operativas](#notas-operativas)
- [Referencias](#referencias)

## Descripción general

El módulo implementa una tubería de evaluación por etapas para modelos encoder, centrada en RAGAS y en datos locales del proyecto ALIA.

| Script | Fase | Función principal |
|--------|------|------------------|
| `step_1_data.py` | Preparación | Genera `queries.jsonl`, `references.jsonl` y `reference_contexts.jsonl` desde el JSONL de triplets |
| `step_2_database.py` | Indexación | Construye una base FAISS con embeddings de los contextos de referencia |
| `step_3_compute_retrieval.py` | Recuperación | Calcula los contextos recuperados para cada consulta |
| `step_4_format_for_ragas.py` | Formateo | Une retrieval + referencias y deja el JSONL listo para RAGAS |
| `step_5_run_ragas.py` | Evaluación | Ejecuta RAGAS, exporta resumen por métrica y detalle por muestra |

### Flujo general

1. **Preparación de datos** desde un fichero de triplets anotados.
2. **Construcción de la base vectorial** con embeddings OpenAI-compatible y FAISS.
3. **Recuperación semántica** de pasajes para cada consulta.
4. **Formateo de las muestras** al esquema que espera RAGAS.
5. **Evaluación incremental** con métricas de retrieval y generación.
6. **Exportación de resultados** en CSV de resumen, CSV de detalle y, opcionalmente, ficheros por métrica.

## Scripts principales

### `step_1_data.py`

Genera los ficheros base de evaluación a partir de `ALIA-<domain>-triplets-*.jsonl`:

- `queries_<sample>.jsonl`
	- `user_input` toma el valor de `query`
	- conserva `id_query`, `id_passage`, `id_document` y `source_id` cuando están disponibles
- `references_<sample>.jsonl`
	- `reference` toma el valor de `answer`
- `reference_contexts_<sample>.jsonl`
	- `reference_contexts` se construye como lista con el `passage`

Comportamiento relevante:

- Deduplica registros exactos si el fichero de salida ya existe.
- Permite procesar una muestra concreta o todo el conjunto disponible.
- Si `sample=0`, usa la mayor muestra detectada cuando existe una versión muestreada.

Argumentos principales:

- `--domain`: dominio de datos.
- `--input_file`: JSONL de entrada opcional.
- `--output_dir`: directorio de salida opcional.
- `--sample`: tamaño de muestra a procesar.

### `step_2_database.py`

Construye una base vectorial FAISS a partir de `ALIA-<domain>-contexts-*.jsonl`.

- Lee embeddings mediante una API OpenAI-compatible, configurada en `encoder-api` dentro de `config.yaml`.
- Usa `faiss.IndexIDMap2` para guardar el índice y un fichero de metadatos en paralelo.
- Normaliza L2 por defecto, de forma que la similitud interna se aproxima a coseno cuando procede.
- Trunca textos largos antes de llamar a embeddings si superan el límite estimado de tokens.

Salida principal:

- `faiss.index`
- `metadata.jsonl`

Argumentos principales:

- `--domain`: dominio de datos.
- `--input_file`: fichero JSONL de contexts.
- `--config`: ruta al YAML de configuración.
- `--output_dir`: ruta de salida de la base vectorial.
- `--sample`: muestra de contexts a indexar.
- `--index_name`: nombre del fichero del índice.
- `--metadata_name`: nombre del fichero de metadatos.
- `--batch_size`: tamaño de lote para embeddings.
- `--no_normalize`: desactiva la normalización L2.
- `--force`: recalcula aunque ya exista la salida.

### `step_3_compute_retrieval.py`

Calcula la recuperación semántica para cada consulta usando el índice FAISS creado en el paso anterior.

- Embebe las consultas con el mismo modelo configurado en `encoder-api`.
- Usa `top_k` para decidir cuántos pasajes devuelve por consulta.
- Produce un JSONL con los pasajes recuperados, sus identificadores y un vector de confidencias.

Salida principal:

- `retrieval/{model_id}/ALIA-{domain}-embeddings-results-query_{sample-query}-contexts_{sample-context}.jsonl`

Campos principales generados:

- `id_query`
- `user_input`
- `id_retrieved_contexts`
- `retrieved_contexts`
- `confidences`

Argumentos principales:

- `--domain`: dominio de datos.
- `--queries_file`: JSONL de consultas.
- `--index_file`: índice FAISS.
- `--metadata_file`: metadatos asociados al índice.
- `--output_file`: ruta de salida opcional.
- `--top_k`: número de contextos a recuperar.
- `--batch_size`: tamaño de lote para embeddings.
- `--sample-query`: muestra de queries.
- `--sample-context`: muestra de contexts.
- `--force`: recalcula la salida.

### `step_4_format_for_ragas.py`

Fusiona los resultados de retrieval con `references.jsonl` y `reference_contexts.jsonl` para dejar una muestra compatible con RAGAS.

- Verifica la presencia de las columnas mínimas de cada entrada.
- Mantiene un único registro por `id_query` en los ficheros auxiliares.
- Construye los campos esperados por RAGAS y conserva identificadores adicionales para calcular `hit@1`.
- Si faltan campos opcionales, avisa y deja la información necesaria en blanco o nula.

Salida principal:

- `retrieval/{model_id}/ALIA-{domain}-embeddings-results-format-query_{sample-query}-contexts_{sample-context}.jsonl`

Campos esperados en la salida:

- `id`
- `user_input`
- `response`
- `reference`
- `retrieved_contexts`
- `reference_contexts`
- `id_passage`
- `id_retrieved_contexts`
- `id_reference_context`
- `id_retrieved_context`

Argumentos principales:

- `--domain`: dominio de datos.
- `--input_file`: JSONL de retrieval.
- `--references_file`: fichero de referencias.
- `--reference_contexts_file`: fichero de contextos de referencia.
- `--output_file`: ruta de salida opcional.
- `--sample-query`: muestra de queries.
- `--sample-context`: muestra de contexts.
- `--force`: recalcula la salida.

### `step_5_run_ragas.py`

Ejecuta RAGAS sobre el JSONL formateado y exporta los resultados finales.

- Usa `llm-api` como LLM evaluador y `encoder-api` como backend de embeddings.
- Evalúa métricas de retrieval, generación o ambas, según `--task`.
- Permite un modo `hit` con métricas auxiliares `hit@1` y `hit@k`.
- Trabaja de forma incremental, con caché, reintentos y checkpoints para tolerar interrupciones.
- Si el CSV de salida ya existe, detecta qué métricas están presentes y puede completar solo las que faltan.

Métricas incluidas:

- Retrieval:
	- `context_precision`
	- `context_utilization`
	- `context_relevance`
- Generación:
	- `faithfulness`
	- `answer_relevancy`
	- `factual_correctness`
- Auxiliares:
	- `hit@1`
	- `hit@k`

Exportaciones generadas:

- CSV de resumen por métrica: `results/{model_id}/ALIA-{domain}-ragas-{task}-query_{sample-query}-contexts_{sample-context}.csv`
- CSV de detalle por muestra: `results/{model_id}/ALIA-{domain}-ragas-{task}-query_{sample-query}-contexts_{sample-context}-samples.csv`
- Ficheros por métrica, cuando aplica: `results/{model_id}/by_metric/`

Argumentos principales:

- `--domain`: dominio de datos.
- `--task`: `retrieval`, `generation`, `all` o `hit`.
- `--force`: fuerza el recálculo completo.
- `--config`: ruta al YAML de configuración.
- `--input_file`: JSONL ya formateado para RAGAS.
- `--output_file`: fichero CSV de resumen.
- `--sample-query`: muestra de queries.
- `--sample-context`: muestra de contexts.

### Utilidades y soporte

- `launcher.sh`: orquesta los cinco pasos y resuelve rutas por defecto, muestras y parámetros comunes.
- `launcher_parent.sh`: ejecuta lotes de evaluaciones a partir de una lista `RUNS`.
- `schemas.yaml`: documenta el contrato de columnas de entrada y salida entre pasos.
- `config.yaml.example`: plantilla de configuración para APIs, métricas, reintentos y checkpoints.

## Configuración

### `config.yaml.example`

Archivo de plantilla para las rutas, credenciales y parámetros de evaluación. Los scripts leen principalmente estas secciones:

- `llm-api`
	- `api_key`, `base_url`, `model_name`
	- `max_tokens`, `temperature`, `inference_delay_s`
- `encoder-api`
	- `api_key`, `base_url`, `model_name`
- `ragas`
	- `metrics`: lista de métricas a evaluar
	- `send_incrementally`: activa el envío por bloques
	- `sample_fraction`: fracción de muestras a evaluar
	- `chunk_size`: tamaño del bloque incremental
	- `max_calls`: límite de llamadas; `0` desactiva el límite
	- `max_concurrency`: concurrencia máxima
	- `max_retries`: reintentos por fallo
	- `backoff_base_s`: base del backoff exponencial
	- `global_retry_wait_s`: espera entre reintentos globales
	- `inference_delay_s`: retardo antes de cada llamada
	- `cache_path`: caché opcional en JSON
	- `backup_batch_size`: frecuencia de checkpoints
	- `backup_dir`: directorio de checkpoints

El ejemplo también incluye claves de apoyo para envoltorios de ejecución:

- `evaluation`
- `output_file`
- `input_jsonl`

### `schemas.yaml`

El fichero `schemas.yaml` actúa como contrato de datos entre las etapas. Resume qué columnas deben existir en cada artefacto y cómo se transforman entre pasos.

- `ALIA-<domain>-triplets-contexts.jsonl`
	- `source_id`, `id_document`, `id_passage`, `passage`, `tokens`, `valid`
- `ALIA-<domain>-triplets-sampled.jsonl`
	- `source_id`, `id_document`, `id_passage`, `id_passage_query`, `passage`, `character`, `type`, `difficulty`, `query`, `answer`
- `queries.jsonl`
	- `user_input`, `id_query`, `id_passage`, `id_document`, `source_id`
- `references.jsonl`
	- `reference`, `id_query`, `id_passage`, `id_document`, `source_id`
- `reference_contexts.jsonl`
	- `reference_contexts`, `id_query`, `id_passage`, `id_document`, `source_id`
- `ALIA-{domain}-embeddings-results.jsonl`
	- `confidences`, `retrieved_contexts`, `id_retrieved_contexts`, `user_input`, `id_query`, `id_passage`, `id_document`, `source_id`
- `ALIA-{domain}-embeddings-results-format.jsonl`
	- `id_reference_context`, `id_retrieved_context`, `reference_contexts`, `retrieved_contexts`, `reference`, `response`, `user_input`, `id`

## Ejecución

### Flujo completo

```bash
bash launcher.sh \
	--domain biomedical \
	--task all \
	--sample-query 800 \
	--sample-context 12596
```

`launcher.sh` ejecuta el flujo completo con parámetros coherentes entre pasos. Por defecto hereda muestras, rutas y el fichero `config.yaml` desde variables de entorno o argumentos de línea de comandos.

### Pasos individuales

```bash
# 1. Generar queries, references y reference_contexts
python step_1_data.py --domain biomedical --sample 800

# 2. Crear la base vectorial FAISS
python step_2_database.py --domain biomedical --sample 12596

# 3. Calcular retrieval
python step_3_compute_retrieval.py \
	--domain biomedical \
	--sample-query 800 \
	--sample-context 12596 \
	--top_k 5

# 4. Formatear la salida para RAGAS
python step_4_format_for_ragas.py \
	--domain biomedical \
	--sample-query 800 \
	--sample-context 12596

# 5. Ejecutar RAGAS
python step_5_run_ragas.py \
	--domain biomedical \
	--task all \
	--sample-query 800 \
	--sample-context 12596
```

### `launcher.sh`

Script principal de orquestación. Resuelve rutas por defecto, valida `--task`, propaga `--force` y permite ajustar:

- `--domain`
- `--task`
- `--force`
- `--config`
- `--python-bin`
- `--query-sample`
- `--context-sample`
- `--retrieval-query-sample`
- `--retrieval-context-sample`
- `--format-query-sample`
- `--format-context-sample`
- `--ragas-query-sample`
- `--ragas-context-sample`
- `--top-k`
- `--batch-size`
- `--index-name`
- `--metadata-name`
- `--no-normalize`

### `launcher_parent.sh`

Lanza una batería de ejecuciones usando una lista `RUNS` interna o la variable de entorno `EXTRA_RUNS`. Es útil para evaluar varios dominios o configuraciones sin repetir comandos manualmente.

- `CONTINUE_ON_ERROR=true` permite seguir con el lote aunque una ejecución falle.
- `DRY_RUN=true` imprime los comandos sin ejecutarlos.
- Cada ejecución se registra en un fichero de log independiente.

### Argumentos comunes

- `--domain`: dominio a evaluar.
- `--sample-query`: muestra de consultas.
- `--sample-context`: muestra de contexts.
- `--force`: ignora salidas previas y recalcula.
- `--config`: ruta al YAML de configuración.

## Arquitectura de evaluación

### APIs y modelos

El flujo distingue entre dos backends OpenAI-compatible:

- `llm-api`: modelo juez de RAGAS.
- `encoder-api`: modelo de embeddings para recuperación y para métricas que requieren vectorización.

Los dos se resuelven a través de `api_key`, `base_url` y `model_name`, lo que permite ejecutar el pipeline contra servicios locales o remotos compatibles con la API de OpenAI.

### Evaluación incremental

`step_5_run_ragas.py` puede enviar muestras en bloques (`chunk_size`) y limitar el número de llamadas con `max_calls`. Esto reduce el riesgo de saturar la API y facilita la evaluación de lotes grandes.

El flujo también puede tomar una fracción de muestras (`sample_fraction`) si la configuración lo requiere.

### Caché, checkpoints y reintentos

La evaluación incorpora varios mecanismos de resiliencia:

- Caché local opcional para evitar recomputar resultados ya resueltos.
- Checkpoints periódicos en `backup_dir` cada `backup_batch_size` muestras.
- Reintentos por métrica con `max_retries` y `backoff_base_s`.
- Reintento global por muestra con `global_retry_wait_s`.
- Retardo previo a cada llamada con `inference_delay_s`.

### Normalización y recuperación

- En `step_2_database.py` la normalización L2 está activada por defecto.
- En `step_3_compute_retrieval.py`, si el índice se ha creado con producto interno, las consultas se normalizan antes de hacer `search`.
- `top_k` controla cuántos contextos se recuperan por consulta; el valor por defecto es `5`.

## Formatos de entrada y salida

### Entrada

**Datos de evaluación**:

- JSONL de triplets de origen con consultas, respuestas y pasajes.
- JSONL de contexts para indexación vectorial.
- Ficheros intermedios generados por los pasos 1 a 4.

**Servicios de inferencia**:

- Un LLM juez compatible con OpenAI para RAGAS.
- Un backend de embeddings compatible con OpenAI para retrieval.

### Salida

Por cada ejecución se generan artefactos con esta estructura general:

```text
data/
└── {domain}/
		├── ALIA-{domain}-triplets-{sample}/
		│   ├── queries_{sample}.jsonl
		│   ├── references_{sample}.jsonl
		│   └── reference_contexts_{sample}.jsonl
		└── ALIA-{domain}-contexts-{sample}/
				└── vector_db/
						└── {model_id}/
								├── faiss.index
								└── metadata.jsonl
retrieval/
└── {model_id}/
		├── ALIA-{domain}-embeddings-results-query_{q}-contexts_{c}.jsonl
		└── ALIA-{domain}-embeddings-results-format-query_{q}-contexts_{c}.jsonl
results/
└── {model_id}/
		├── ALIA-{domain}-ragas-{task}-query_{q}-contexts_{c}.csv
		├── ALIA-{domain}-ragas-{task}-query_{q}-contexts_{c}-samples.csv
		└── by_metric/
				├── ALIA-{domain}-ragas-{task}-query_{q}-contexts_{c}-<metric>.csv
				└── ALIA-{domain}-ragas-{task}-query_{q}-contexts_{c}-<metric>_scores.csv
```

El CSV de detalle por muestra conserva las columnas base y añade las métricas con prefijo `ragas_`. El CSV principal actúa como resumen por métrica con estadísticas agregadas.

## Estructura de datos esperada

### Triplets de origen

El paso 1 parte de un JSONL de triplets con campos como:

```json
{
	"source_id": "dataset_name",
	"id_document": "doc_id",
	"id_passage": "passage_id",
	"id_passage_query": "query_id",
	"query": "pregunta o consulta",
	"answer": "respuesta esperada",
	"passage": "texto del pasaje"
}
```

### Ficheros intermedios

Los pasos 1 a 4 trabajan con un contrato estable de columnas:

- `queries.jsonl`: `user_input`, `id_query`, `id_passage`, `id_document`, `source_id`
- `references.jsonl`: `reference`, `id_query`, `id_passage`, `id_document`, `source_id`
- `reference_contexts.jsonl`: `reference_contexts`, `id_query`, `id_passage`, `id_document`, `source_id`
- `retrieval results`: `id_query`, `user_input`, `retrieved_contexts`, `id_retrieved_contexts`, `confidences`

### Entrada RAGAS

`step_4_format_for_ragas.py` genera un JSONL con un esquema compatible con el evaluador:

```json
{
	"id": "query_id",
	"user_input": "consulta",
	"response": "respuesta del modelo",
	"reference": "respuesta de referencia",
	"retrieved_contexts": ["pasaje 1", "pasaje 2"],
	"reference_contexts": ["pasaje de referencia"],
	"id_passage": "passage_id",
	"id_retrieved_contexts": ["passage_1", "passage_2"],
	"id_reference_context": "passage_id",
	"id_retrieved_context": "passage_1"
}
```

## Notas operativas

- `sample=0` significa “usar todo lo disponible” o, si hay variantes muestreadas, la mayor muestra detectada.
- `--force` elimina o sobrescribe la salida previa según el paso.
- `step_4_format_for_ragas.py` avisa si faltan identificadores opcionales; en ese caso, `hit@1` puede quedar como `NaN`.
- `step_5_run_ragas.py` detecta si ya existe un CSV de salida y, si hay métricas faltantes, puede completar solo esas métricas.
- `launcher_parent.sh` es la opción más cómoda para lanzar campañas de evaluación repetidas.

## Referencias

- [RAGAS](https://docs.ragas.io/)
- [FAISS](https://github.com/facebookresearch/faiss)
- [OpenAI API](https://platform.openai.com/docs/)