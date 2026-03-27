# Pipeline de creación de corpus de instrucciones (sintéticas + generales de Internet)

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [1. Objetivo y alcance](#1-objetivo-y-alcance)
- [2. Componentes del pipeline](#2-componentes-del-pipeline)
- [3. Flujo de construcción del corpus](#3-flujo-de-construcción-del-corpus)
- [4. Paso `initial`: normalización y agregación](#4-paso-initial-normalización-y-agregación)
- [5. Paso `downsampling`: generación de variantes](#5-paso-downsampling-generación-de-variantes)
- [6. Entradas y salidas](#6-entradas-y-salidas)
- [7. Ejecución del pipeline](#7-ejecución-del-pipeline)
- [8. Configuración](#8-configuración)
- [9. Buenas prácticas](#9-buenas-prácticas)
---

## 1. Objetivo y alcance

Este pipeline construye corpora de instrucciones para entrenamiento de LLMs combinando dos tipos de fuentes:

1. **Instrucciones sintéticas de dominio** (por ejemplo, legal, biomédico, patrimonio).
2. **Instrucciones generales** obtenidas de fuentes abiertas de Internet (normalmente en formato conversacional SFT).

El resultado es un corpus homogéneo, tokenizado, trazable por categoría y exportado en formatos `.parquet` y `.jsonl`, con variantes opcionales de downsampling.

---

## 2. Componentes del pipeline

Scripts principales:

- [data/llms/scripts/instructions/pipeline/instructions_manager.py](data/llms/scripts/instructions/pipeline/instructions_manager.py): orquestador principal.
- [data/llms/scripts/instructions/pipeline/instructions_step_base.py](data/llms/scripts/instructions/pipeline/instructions_step_base.py): clase base `InstructionsStep`.
- [data/llms/scripts/instructions/pipeline/instructions_step_initial.py](data/llms/scripts/instructions/pipeline/instructions_step_initial.py): generación del corpus inicial.
- [data/llms/scripts/instructions/pipeline/instructions_step_downsampling.py](data/llms/scripts/instructions/pipeline/instructions_step_downsampling.py): creación de subconjuntos balanceados.
- [data/llms/scripts/instructions/pipeline/config.yaml.example](data/llms/scripts/instructions/pipeline/config.yaml.example): plantilla de configuración.

Scripts de ejecución en cluster:

- [data/llms/scripts/instructions/pipeline/launcher_parent.sh](data/llms/scripts/instructions/pipeline/launcher_parent.sh)
- [data/llms/scripts/instructions/pipeline/launcher_job.sh](data/llms/scripts/instructions/pipeline/launcher_job.sh)

---

## 3. Flujo de construcción del corpus

El pipeline actual define dos pasos:

1. `initial`
2. `downsampling`

La entrada de datos sigue una estructura por dominio e idioma:

- Datos de entrada crudos: `data/instructions/raw/{domain}/{lang}`
- Datos intermedios normalizados: `data/instructions/interim/{domain}/{lang}`
- Dataset agregado inicial: `data/instructions/processed/{domain}/{lang}`
- Corpora finales downsampleados: `instructions/{domain}/{lang}`

Adicionalmente, se generan estadísticas en `outputs/instructions/{domain}/{lang}`.

---

## 4. Paso `initial`: normalización y agregación

Este paso transforma archivos de instrucciones crudas en un único corpus inicial consolidado.

### 4.1 Entrada de archivos

Se leen todos los `.jsonl` del directorio `raw/{domain}/{lang}`.

### 4.2 Formateo para instrucciones sintéticas de dominio

Cuando `domain != general`, el procesamiento aplica:

- normalización de nombres de columnas (`System prompt`, `Question`, `Response`);
- construcción de `instruction` concatenando `system_prompt`, `question` y `response`;
- extracción de criterios desde el nombre de fichero (por patrón regex), por ejemplo:
	- `query_type`
	- `context_type`
	- `justification_type` o `task_type` según dominio;
- creación de una columna de categoría (`category`);
- cálculo de tokens por instrucción;
- normalización de identificadores (`source_id`, `id`).

### 4.3 Formateo para instrucciones generales (Internet)

Cuando `domain == general`, el procesamiento está orientado a datasets tipo SFT en formato conversacional:

- extracción de turnos desde `conversations`:
	- `system_prompt`
	- `question` (turno `human`)
	- `response` (turno `gpt`)
- creación de `instruction` unificando `question` y `response`;
- asignación de `source_id` usando el nombre de archivo (patrón `*_SFT.jsonl`);
- cálculo de tokens.

### 4.4 Salida intermedia y agregación final

Por cada archivo raw se guarda una versión intermedia en `interim/{domain}/{lang}`.

Después, todos los intermedios se agregan verticalmente en un único corpus inicial:

- `ALIA-{domain}-{lang}-instructions.parquet`
- `ALIA-{domain}-{lang}-instructions.jsonl`

Finalmente se generan estadísticas del corpus inicial (volumen, tokens y distribución por categorías/criterios).

---

## 5. Paso `downsampling`: generación de variantes

Este paso toma el corpus inicial y genera versiones reducidas para experimentación y entrenamiento controlado.

Tipos de tarea soportados:

1. `tokens_general`:
	 - reduce tokens globales conservando proporción por categoría.
2. `instructions_general`:
	 - reduce número total de instrucciones conservando proporción por categoría.
3. `tokens_specific`:
	 - fija objetivos de tokens para categorías concretas.
4. `instructions_specific`:
	 - fija objetivos de instrucciones para categorías concretas.

Para cada tarea:

- se ejecuta el muestreo correspondiente;
- se transforma a formato conversación con `conversations` (`system`, `human`, `gpt`);
- se baraja el resultado final (`shuffle` reproducible por semilla);
- se exporta en `.parquet` y `.jsonl` con sufijo descriptivo;
- se calculan estadísticas del subset generado.

---

## 6. Entradas y salidas

| Etapa | Entrada | Salida |
|---|---|---|
| `initial` | `data/instructions/raw/{domain}/{lang}/*.jsonl` | `data/instructions/interim/{domain}/{lang}/*.jsonl` + `data/instructions/processed/{domain}/{lang}/ALIA-{domain}-{lang}-instructions.parquet/jsonl` |
| `downsampling` | `data/instructions/processed/{domain}/{lang}/ALIA-{domain}-{lang}-instructions.jsonl` | `instructions/{domain}/{lang}/ALIA-{domain}-{lang}-instructions-downsample-{suffix}.parquet/jsonl` |

Estadísticas por paso:

- `outputs/instructions/{domain}/{lang}/ALIA-{domain}-{lang}-instructions-{step}-{suffix}-stats.csv`

---

## 7. Ejecución del pipeline

### 7.1 Ejecución local

```bash
python data/llms/scripts/instructions/pipeline/instructions_manager.py \
	--domain biomedical \
	--lang es
```

Ejecutar solo un paso:

```bash
python data/llms/scripts/instructions/pipeline/instructions_manager.py \
	--domain general \
	--lang en \
	--single_step initial
```

Ejecutar un rango:

```bash
python data/llms/scripts/instructions/pipeline/instructions_manager.py \
	--domain legal \
	--lang es \
	--start_step initial \
	--end_step downsampling
```

### 7.2 Ejecución en SLURM

```bash
bash data/llms/scripts/instructions/pipeline/launcher_parent.sh \
	--domain biomedical \
	--lang es \
	--end_step downsampling
```

---

## 8. Configuración

La configuración completa del pipeline se define en:

- [data/llms/scripts/instructions/pipeline/config.yaml.example](data/llms/scripts/instructions/pipeline/config.yaml.example)

Bloques principales a revisar:

- `pipeline.steps`
- `paths`
- `general-instruction`
- `domain-instruction`
- `downsampling-tasks`

---

## 9. Buenas prácticas

- Mantener nomenclatura consistente de archivos raw para que los patrones regex extraigan correctamente la categoría/criterios.
- Validar siempre la presencia de campos mínimos (`question`, `response`) antes de agregar nuevos datasets.
- Revisar estadísticas por paso para detectar sesgos de categoría o caídas abruptas de volumen.
- Configurar tareas de downsampling según el objetivo experimental (balance por tokens o por número de instrucciones).
- Ejecutar con `--force` solo cuando se requiera regenerar salidas existentes.

