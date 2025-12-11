# Documentación: Sistema de Generación Automática de Cabeceras y Clasificación de Documentos Jurídico-Administrativos

Este sistema utiliza un LLM (Large Language Model) con salidas estructuradas para generar automáticamente cabeceras descriptivas y clasificar documentos del ámbito jurídico-administrativo español.

## Objetivo General

El sistema procesa corpus de documentos legales y administrativos para extraer dos elementos clave: una cabecera descriptiva que sintetiza el contenido principal con metadatos técnicos relevantes, y una clasificación categórica que facilita la organización sistemática y búsqueda optimizada de documentos oficiales.

## Arquitectura del Sistema

### 1. Script con el pipeline principal: `generate_headers.py`

Script principal que implementa el pipeline completo de procesamiento de documentos usando VLLM (Very Large Language Model) con generación guiada por esquemas JSON.

#### Componentes Principales

**Clase `DocumentOutput` (Pydantic)**

Define el esquema de salida estructurada con dos campos obligatorios:
- `cabecera`: Resumen conciso de 2-3 frases con datos técnicos relevantes (dataset, fecha, sección, contenido)
- `clasificacion`: Categoría única entre ocho opciones predefinidas (Anuncio, Resolución, Convocatoria, Licitación, Real decreto, Documento legislativo, Registro del parlamento, Otro)

**Clase `DocumentProcessor`**

Clase principal que encapsula toda la lógica de procesamiento con las siguientes responsabilidades:

#### Métodos Fundamentales

**`_initialize_llm()`**
Inicializa el modelo LLM con paralelización tensorial configurada (tensor_parallel_size: 4) y establece parámetros de generación con guided decoding basado en el esquema JSON de DocumentOutput, garantizando respuestas válidas y estructuradas.

**`_load_system_prompt()`**
Carga el prompt del sistema desde `system_prompt.txt`, que define el rol del modelo como especialista en análisis documental jurídico-administrativo y especifica instrucciones detalladas sobre formato de entrada/salida, manejo de metadatos y corrección de errores de codificación.

**`safe_decode()`**
Método estático que maneja la decodificación segura de unicode escapes en textos, corrigiendo problemas de codificación comunes (ej: "Ã©" → "é", "Ã±" → "ñ") mediante detección de patrones unicode y decodificación con fallback a texto original.

**`batch_iterator()`**
Generador que divide listas de documentos en batches del tamaño configurado (batch_size: 2048), optimizando el uso de memoria GPU y permitiendo procesamiento incremental de grandes volúmenes.

**`_validate_text_lengths()`**
Valida que los textos no excedan la longitud máxima del modelo restando los tokens reservados para el prompt (max_model_len - prompt_tokens = 131072 - 11350 = 119722 tokens válidos), recortando documentos excesivamente largos y registrando advertencias.

**`_enrich_documents()`**
Enriquece documentos con contexto estructurado combinando tres elementos: nombre del dataset de origen (limpiado de guiones bajos), metadatos en formato JSON (si están disponibles y no vacíos) y texto completo del documento, proporcionando máximo contexto al LLM para análisis preciso.

**`_prepare_messages_batch()`**
Construye arrays de mensajes en formato chat con dos roles: system (prompt cargado desde archivo) y user (texto del documento enriquecido y decodificado), preparando inputs compatibles con la interfaz de chat del LLM.

**`_process_batch()`**
Procesa batches completos de documentos invocando el LLM con parámetros de sampling configurados (temperature: 0.2, max_tokens: 131072) y guided decoding habilitado, extrayendo respuestas JSON y validándolas con el modelo Pydantic, aplicando reparación de JSON en caso de fallos y retornando listas paralelas de cabeceras y clasificaciones.

**`_process_source()`**
Gestiona el procesamiento completo de un source específico del corpus: verifica existencia previa (skip si ya existe, salvo que force=True), filtra documentos por source_id, enriquece textos con metadatos, valida longitudes, procesa en batches con barra de progreso, agrega columnas de resultados al DataFrame y guarda en formato Parquet con nombre del source.

**`process()`**
Método principal que ejecuta el flujo completo: carga el prompt del sistema, lee el archivo Parquet del corpus, extrae sources únicos ordenados, inicializa el LLM con configuración tensor paralela, e itera sobre cada source aplicando procesamiento completo con gestión de errores y logging detallado.

#### Sistema de Guided Decoding

El sistema utiliza `GuidedDecodingParams` con el esquema JSON de Pydantic para forzar al modelo a generar salidas estructuradas válidas, eliminando necesidad de parseo complejo post-generación y garantizando consistencia en formato de respuestas.

#### Manejo de Errores JSON

Implementa doble capa de validación: intento de parsing directo con `json.loads()` y, en caso de fallo, aplicación de `json_repair.repair_json()` para corregir JSON malformado, finalizando con fallback a valores vacíos si ambos métodos fallan.

### 2. Fichero de configuración: `config.yaml`

Archivo de configuración centralizado que define todos los parámetros del sistema de generación de headers.

#### Configuraciones por Categoría

**Rutas del Sistema**
- `root-headers`: Directorio base para archivos del sistema (.../COMUNES/headers)
- `system_file`: Archivo con el prompt del sistema (system_prompt.txt)
- `root-corpus`: Directorio donde reside el corpus a procesar
- `parquet_file`: Archivo Parquet de entrada con documentos (ALIA-legal-administrative-enriched.parquet)
- `output_dir`: Directorio de salida para archivos procesados
- `output_file`: Nombre del archivo Parquet de salida con headers generados

**Configuración del Modelo LLM**
- `model_path`: Ruta al modelo GPT-OSS 20B (.../gpt-oss-20b/)
- `prompt_tokens`: Tokens reservados para el prompt del sistema (11350), utilizados en cálculo de límites
- `tensor_parallel_size`: Número de GPUs para paralelización tensorial (4)
- `max_model_len`: Longitud máxima del contexto en tokens (131072)
- `seed`: Semilla para reproducibilidad (42)
- `temperature`: Control de aleatoriedad en generación (0.2 = más determinista)
- `max_tokens`: Límite de tokens generados por respuesta (131072)

**Parámetros de Procesamiento**
- `batch_size`: Número de documentos procesados por batch (2048)
- `skip_sources`: Lista de sources a omitir durante procesamiento (EuroPat)

### 3. `system_prompt.txt`

Prompt estructurado que define el comportamiento del modelo como especialista en análisis documental jurídico-administrativo.

#### Estructura del Prompt

**Sección ROL**
Define al modelo como especialista en análisis documental que procesa documentos oficiales para catalogación y archivo sistemático.

**Sección TAREA**
Especifica los dos elementos a generar:
- **Cabecera**: Resumen de 2-3 frases con datos técnicos (dataset, fecha, sección, contenido)
- **Clasificación**: Asignación a una de ocho categorías exactas con definiciones precisas

**Taxonomía de Clasificación**
Ocho categorías mutuamente excluyentes con criterios específicos:
- **Anuncio**: Comunicaciones públicas identificadas explícitamente
- **Resolución**: Decisiones administrativas oficiales
- **Convocatoria**: Llamadas a procesos selectivos públicos
- **Licitación**: Subtipo específico de convocatoria identificado explícitamente
- **Real decreto**: Disposiciones gubernamentales reglamentarias
- **Documento legislativo**: Normas con rango de ley del poder legislativo
- **Registro del parlamento**: Documentos de actividades parlamentarias
- **Otro**: Documentos no clasificables en categorías anteriores

**INSTRUCCIONES ESPECÍFICAS**

Define tres aspectos críticos del procesamiento:

*Sobre parámetros de entrada*: Estructura esperada con tres componentes (nombre dataset, metadatos opcionales JSON, texto completo)

*Sobre metadatos*: Directrices para ignorar campos null y utilizar solo información válida del JSON

*Sobre problemas de codificación*: Instrucciones para interpretar y corregir errores de codificación (Ã©→é, Ã±→ñ) sin copiar literalmente los errores

**FORMATO DE RESPUESTA OBLIGATORIO**
Esquema JSON estricto con dos campos: cabecera (string) y clasificacion (string categórico).

**OBJETIVO**
Facilita organización, catalogación eficiente, identificación precisa de contenido, clasificación exacta de naturaleza jurídico-administrativa y búsqueda optimizada.

**EJEMPLOS DE REFERENCIA**
Seis ejemplos completos de entrada/salida que ilustran:
- Ejemplo 1: Documento legislativo (Constitución Española)
- Ejemplo 2: Resolución de concurso administrativo
- Ejemplo 3: Resolución de comisiones universitarias
- Ejemplo 4: Anuncio de notificación administrativa
- Ejemplo 5: Licitación de proyecto de construcción ferroviaria
- Ejemplo 6: Registro del parlamento (sesión plenaria)

## Flujo de Datos Completo

1. **Carga de configuración**: Lectura de `config.yaml` con todos los parámetros del sistema
2. **Inicialización de recursos**: Carga del prompt desde `system_prompt.txt` y lectura del corpus Parquet
3. **Extracción de sources**: Identificación de sources únicos en columna `source_id` con ordenamiento
4. **Inicialización del LLM**: Carga del modelo GPT-OSS 20B con paralelización en 4 GPUs y configuración de guided decoding
5. **Iteración por source**: Procesamiento independiente de cada dataset del corpus
6. **Filtrado de documentos**: Extracción de documentos correspondientes al source actual
7. **Enriquecimiento contextual**: Combinación de nombre dataset, metadatos JSON y texto completo
8. **Validación de longitud**: Verificación y recorte de textos que excedan límites del modelo
9. **Batchificación**: División en lotes de 2048 documentos para procesamiento eficiente
10. **Generación con LLM**: Invocación del modelo con guided decoding para garantizar JSON válido
11. **Extracción de resultados**: Parsing de respuestas JSON y validación con Pydantic
12. **Agregación de columnas**: Adición de `header` y `classification` al DataFrame original
13. **Persistencia por source**: Guardado en archivos Parquet individuales con nombre del source
14. **Reporting**: Visualización de muestras y estadísticas de procesamiento

## Optimizaciones Implementadas

- **Guided Decoding con Pydantic**: Garantiza salidas estructuradas sin necesidad de parseo complejo post-generación
- **Paralelización tensorial**: Distribución del modelo en 4 GPUs para procesamiento acelerado
- **Batching masivo**: Procesamiento de 2048 documentos por lote maximizando throughput
- **Validación preventiva**: Recorte de textos largos antes de enviar al modelo evitando errores en runtime
- **Procesamiento incremental por source**: Guardado independiente permite reanudar procesamiento y evitar reprocesamiento
- **Reparación automática de JSON**: Doble capa de validación con json_repair como fallback
- **Decodificación segura de unicode**: Corrección automática de errores de codificación comunes
- **Skip de sources procesados**: Verificación de existencia previa con opción de forzar reprocesamiento
- **Temperatura baja**: Configuración a 0.2 para generaciones más deterministas y consistentes
- **Logging detallado**: Trazabilidad completa del procesamiento con niveles de logging configurables

## Casos de Uso

Este sistema está diseñado para automatizar la catalogación y clasificación de grandes corpus de documentos jurídico-administrativos españoles (BOE, BOJA, documentación parlamentaria, licitaciones públicas, biblioteca jurídica), generando metadatos estructurados que facilitan búsqueda, recuperación, organización archivística y análisis de contenido legal.
