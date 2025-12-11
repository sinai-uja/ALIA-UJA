# Documentación: Sistema de Chunking Semántico

Este sistema implementa un pipeline de chunking semántico optimizado para dividir documentos de texto en fragmentos coherentes usando embeddings y análisis de similitud coseno.

## Objetivo General

El sistema procesa grandes corpus de documentos para dividirlos en "chunks" (fragmentos) semánticamente coherentes con tamaños controlados basados en tokens, facilitando su uso en sistemas de recuperación de información, RAG (Retrieval-Augmented Generation) y modelos de lenguaje.

## Arquitectura del Sistema

### 1. `semantic_chunker.py`

Este script implementa la clase `SemanticChunker`, un transformador de documentos optimizado con las siguientes capacidades:

#### Funcionalidades Principales

- **Chunking semántico basado en embeddings**: Utiliza modelos de embeddings para calcular similitud entre oraciones y determinar puntos de ruptura naturales donde el contenido cambia de tema
- **Control estricto de tokens**: Implementa límites configurables (min/max tokens) usando tiktoken para garantizar chunks dentro de rangos específicos
- **Optimización de GPU**: Procesa embeddings en batches para reducir uso de memoria y evitar desbordamientos
- **Detección avanzada de oraciones**: Usa spaCy para segmentación precisa de oraciones (con fallback a regex)
- **Balanceo de chunks**: Ajusta tamaños de chunks para lograr homogeneidad mediante fusión de fragmentos pequeños
- **Paralelización**: Soporta procesamiento paralelo de múltiples documentos (configurable según disponibilidad de GPU)

#### Métodos Clave

**`combine_sentences()`**
Combina oraciones con un buffer para proporcionar contexto adicional antes de generar embeddings, mejorando la calidad de la segmentación semántica.

**`calculate_cosine_distances()`**
Calcula distancias de similitud coseno entre embeddings de oraciones consecutivas usando operaciones vectorizadas, identificando cambios temáticos.

**`split_text()`**
Método principal que ejecuta el pipeline completo: segmenta texto en oraciones, genera embeddings, calcula distancias, determina puntos de ruptura y crea chunks validados.

**`_split_by_token_limit()`**
Divide grupos de oraciones que exceden el límite máximo de tokens, respetando el umbral de tolerancia configurado (max_threshold).

**`_balance_chunks()`**
Fusiona chunks pequeños con vecinos para reducir varianza y mejorar homogeneidad, verificando límites de tokens.

**`_optimize_chunk_in_threshold_zone()`**
Optimiza chunks que caen en la zona de umbral (entre max_chunk_size_tokens y max_chunk_size_tokens + max_threshold) buscando mejores puntos de división.

#### Algoritmos de Umbral de Ruptura

Soporta cuatro métodos para determinar puntos de ruptura semántica:

- **Percentile**: Usa percentil de distancias (default: 95)
- **Standard deviation**: Usa desviación estándar multiplicada por factor
- **Interquartile**: Usa rango intercuartílico (IQR)
- **Gradient**: Analiza gradientes de distancias para detectar cambios abruptos

### 2. `extract_chunks.py`

Script principal que orquesta el pipeline de procesamiento de corpus completos.

#### Flujo de Procesamiento

1. **Carga de configuración**: Lee `config.yaml` con todos los parámetros del sistema
2. **Inicialización de modelos**: Carga modelo de embeddings (HuggingFace) y crea instancia de SemanticChunker con configuración específica
3. **Detección de hardware**: Detecta disponibilidad de GPU y ajusta paralelización automáticamente
4. **Procesamiento por dataset**: Itera sobre archivos Parquet del corpus, extrayendo documentos
5. **Generación de chunks**: Aplica SemanticChunker a cada documento con filtros de calidad
6. **Almacenamiento**: Guarda chunks en archivos Parquet con metadatos (tokens, validez, IDs)
7. **Estadísticas**: Genera reportes de tokens, validez y distribuciones

#### Funciones Principales

**`get_model()`**
Inicializa el modelo de embeddings con soporte GPU/CPU y crea el SemanticChunker con todos los parámetros de configuración.

**`get_chunks()`**
Procesa listas de documentos generando chunks, ajustando dinámicamente el buffer_size según volumen y aplicando procesamiento serial o paralelo.

**`_filter_chunks()`**
Filtra chunks basándose en densidad de puntuación para eliminar fragmentos de baja calidad.

**`aggregate_chunks()`**
Consolida múltiples archivos Parquet de chunks en un único archivo agregado con compresión eficiente.

**`_get_statictics()`**
Calcula y muestra estadísticas detalladas: conteo de chunks, métricas de tokens (media, min, max, mediana), distribución de validez.

**`main()`**
Función principal que coordina el procesamiento completo: carga corpus, itera datasets, genera chunks y gestiona persistencia.

### 3. `config.yaml`

Archivo de configuración centralizado que define todos los parámetros del sistema.

#### Configuraciones Principales

- **Rutas de datos**: Directorios de corpus de entrada y chunks de salida
- **Modelo de embeddings**: Ruta al modelo multilingual MiniLM-L12-v2
- **Límites de tokens**: min_chunk_size_tokens (512), max_chunk_size_tokens (1024)
- **Tokenizador**: cl100k_base (compatible con OpenAI)
- **Optimización GPU**: embedding_batch_size (32)
- **Segmentación de oraciones**: Configuración de spaCy con modelo español
- **Balanceo**: target_chunk_variance (0.2) para homogeneidad
- **Método de ruptura**: breakpoint_threshold_type (gradient)
- **Paralelización**: max_workers configurables
- **Filtros**: chunk_punctuation_percentage (0.1) para calidad

## Flujo de Datos

1. **Input**: Archivos Parquet con columnas `id` y `text` en el corpus_path
2. **Segmentación**: Texto dividido en oraciones usando spaCy
3. **Contexto**: Oraciones combinadas con buffer para contexto
4. **Embeddings**: Generación por batches usando modelo multilingual
5. **Análisis semántico**: Cálculo de distancias coseno entre embeddings
6. **Puntos de ruptura**: Identificación usando threshold gradient
7. **Validación de tokens**: Verificación de límites min/max con tiktoken
8. **Balanceo**: Fusión de chunks pequeños para homogeneidad
9. **Filtrado**: Eliminación de chunks con alta densidad de puntuación
10. **Output**: Archivos Parquet con columnas: source_id, id_document, id_chunk, chunk, tokens, valid

## Optimizaciones Implementadas

- **Gestión de memoria GPU**: Limpieza automática de caché CUDA después de cada batch
- **Procesamiento vectorizado**: Operaciones numpy para cálculos de similitud
- **Spawn multiprocessing**: Compatibilidad con CUDA evitando problemas de fork
- **Lazy loading**: Uso de Polars con escaneo lazy para archivos grandes
- **Compresión**: Almacenamiento Parquet con Zstd para eficiencia
- **Ajuste dinámico**: Buffer size adaptativo según volumen de documentos
- **Streaming**: Procesamiento incremental de DataFrames grandes

## Casos de Uso

Este sistema está diseñado para preparar datos textuales para aplicaciones de NLP que requieren fragmentos semánticamente coherentes y de tamaño controlado, como bases de datos vectoriales, sistemas RAG, fine-tuning de LLMs y búsqueda semántica.