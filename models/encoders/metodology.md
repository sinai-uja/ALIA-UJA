# Metodología de Entrenamiento de Modelos Discriminativos

Descripción de la metodología completa seguida para obtener los modelos bi-encoders y cross-encoders.

*Proyecto ALIA*

---

## Índice
1. [Introducción](#1-introducción)
2. [Generación del Conjunto de Entrenamiento](#2-generación-del-conjunto-de-entrenamiento)
3. [Estrategia de Entrenamiento](#3-estrategia-de-entrenamiento)
   - [3.1. Entrenamiento Bi-Encoder](#31-entrenamiento-bi-encoder)
   - [3.2. Entrenamiento Cross-Encoder](#32-entrenamiento-cross-encoder)
4. [Estrategia de Evaluación](#4-estrategia-de-evaluación)

---

## 1. Introducción

En este proyecto se utilizan modelos encoder de tipo **Sentence Transformer** para dos tareas complementarias dentro de un pipeline de recuperación de información:

- **Bi-encoder**: codifica query y documento de forma independiente y mide su similitud mediante producto escalar. Es eficiente en tiempo de búsqueda y se usa para la recuperación inicial (first-stage retrieval).
- **Cross-encoder (reranker)**: recibe la query y el documento concatenados y produce un único score de relevancia. Es más preciso pero más lento, por lo que se aplica como segunda etapa sobre los candidatos recuperados por el bi-encoder.

Ambos modelos parten del mismo backbone transformer preentrenado (`MODEL_PATH`) y se ajustan mediante aprendizaje curricular sobre datos sintéticos de hard negatives generados específicamente para el dominio.

---

## 2. Generación del Conjunto de Entrenamiento

Para entrenar los modelos se necesitan **tripletas sintéticas** de la forma:

```
query  +  documento_relevante  +  lista_de_documentos_irrelevantes
```

Estas tripletas se organizan en varios niveles de dificultad:

| Nivel | Descripción |
|---|---|
| `facil` | Negativos fáciles de distinguir del positivo |
| `medio` | Negativos de dificultad intermedia |
| `dificil` | Negativos muy similares al positivo (hard negatives) |
| `generales` | Ejemplos de dominio general, no específicos |

Cada nivel dispone además de dos variantes según cómo se seleccionaron los negativos:

- **`random`**: negativos seleccionados aleatoriamente del corpus.
- **`top`**: negativos seleccionados mediante **Positive-Aware Mining** (enfoque NVIDIA): un candidato solo se considera negativo si su similitud con la query es inferior a la del positivo menos un margen `margin`:

```python
scores = compute_similarity(query, candidates)  # cosine / dot product
hard_negatives = candidates[scores < (positive_score - margin)]
```

Para el proceso completo de creación de datos ver [Flujo de Creación de Datos Sintéticos para Encoders](../../../data/encoders/documentation/flujoDatosSinteticos.md).

---

## 3. Estrategia de Entrenamiento

La estrategia combina tres técnicas:

- **Contrastive learning**: en cada lote de entrenamiento se incluyen pares positivos y negativos. El objetivo es que la representación de una query sea cercana a su documento relevante y lejana al resto (en el bi-encoder, la matriz de similitud del lote tiene valor 1 en la diagonal y 0 en el resto).
- **Curriculum learning**: las fases de entrenamiento siguen un orden de dificultad creciente, de negativos aleatorios a hard negatives, permitiendo que el modelo aprenda primero las señales más claras antes de enfrentarse a los casos más ambiguos ([Bengio et al., 2009](https://dl.acm.org/doi/10.1145/1553374.1553380)).
- **Positive-Aware Mining**: se evitan falsos negativos usando el score del positivo como umbral de referencia, siguiendo el enfoque de [Moreira et al., 2024](https://arxiv.org/abs/2405.15343).

En ambos modelos (bi-encoder y cross-encoder) el entrenamiento se divide en **múltiples fases secuenciales**. Cada fase guarda su checkpoint final, que es cargado por la siguiente fase. Las fases ya completadas se saltan automáticamente si el checkpoint existe, lo que permite reanudar entrenamientos interrumpidos.

---

### 3.1. Entrenamiento Bi-Encoder

**Arquitectura**

El modelo se construye añadiendo una cabeza de **mean pooling** sobre el encoder transformer:

```
Transformer (backbone) → MeanPooling → vector de dimensión fija
```

En la fase 1, la cabeza de pooling se añade explícitamente. En fases posteriores, se carga directamente el checkpoint `SentenceTransformer` guardado por la fase anterior.

**Loss**: `CachedMultipleNegativesRankingLoss` con gradient caching, que permite usar lotes grandes sin aumentar el consumo de VRAM.

**Fases de entrenamiento**

| Fase | Dataset | Épocas | Muestras máx. | Tipo de negativos |
|---|---|---|---|---|
| 1 | `generales_random` | 2 | Sin límite | Aleatorios, dominio general |
| 2 | `facil_random` | 2 | 100 000 | Aleatorios, fácil |
| 3 | `medio_random` | 2 | 100 000 | Aleatorios, medio |
| 4 | `dificil_random` | 2 | 100 000 | Aleatorios, difícil |
| 5 | `generales_top` | 1 | Sin límite | Hard negatives, dominio general |
| 6 | `facil_top` | 1 | 100 000 | Hard negatives, fácil |
| 7 | `medio_top` | 1 | 100 000 | Hard negatives, medio |
| 8 | `dificil_top` | 1 | 100 000 | Hard negatives, difícil |

**Hiperparámetros** (configurables en `config_train.yaml`)

La tabla siguiente muestra los valores de referencia usados como punto de partida. Los hiperparámetros finales de cada modelo entrenado (legal, biomédico y patrimonio) pueden diferir, ya que se optimizan mediante Optuna para cada dominio. Consulta la configuración específica de cada modelo en:

> 📄 [`training_parameters.md`](./training parameters.md) — Configuraciones concretas y parámetros específicos por dominio (legal, biomédico, patrimonio).

| Parámetro | Valor de referencia |
|---|---|
| `BATCH_SIZE` | 32 |
| `CACHE_MINI_BATCH_SIZE` | 4 |
| `LEARNING_RATE` | 4.7e-5 |
| `WARMUP_RATIO` | 0.197829 |
| `WEIGHT_DECAY` | 0.007845 |
| `MAX_SEQ_LENGTH` | 8192 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |

**Script de entrenamiento**: [`train_cl_biencoder.py`](../../../models/encoders/train_cl_biencoder.py)

---

### 3.2. Entrenamiento Cross-Encoder

**Arquitectura**

El cross-encoder recibe query y documento **concatenados** y produce un único score de relevancia mediante una cabeza de regresión (`num_labels=1`):

```
[CLS] query [SEP] documento [SEP] → Transformer → score de relevancia
```

El modelo se carga directamente como `CrossEncoder` desde el checkpoint del backbone (fase 1) o desde el checkpoint guardado por la fase anterior.

**Loss**: `BinaryCrossEntropyLoss`. Cada ejemplo del dataset incluye pares `(query, documento_positivo, label=1.0)` y `(query, documento_negativo, label=0.0)`. La carga del dataset usa **reservoir sampling** para garantizar un muestreo uniforme sin cargar todo el fichero en memoria.

**Fases de entrenamiento**

| Fase | Dataset | Épocas | Muestras máx. | Tipo de negativos |
|---|---|---|---|---|
| 1 | `generales_random` | 1 | Sin límite | Aleatorios, dominio general |
| 2 | `facil_top` | 1 | 100 000 | Hard negatives, fácil |
| 3 | `medio_top` | 1 | 100 000 | Hard negatives, medio |
| 4 | `dificil_top` | 1 | 100 000 | Hard negatives, difícil |
| 5 | `generales_top` | 1 | Sin límite | Hard negatives, dominio general |

> El cross-encoder omite las fases de negativos aleatorios de nivel medio y difícil (presentes en el bi-encoder) y va directamente a hard negatives de dominio específico tras el calentamiento general. Esto se debe a que el cross-encoder ya recibe la query y el documento concatenados, lo que lo hace más robusto a negativos fáciles desde el principio.

**Hiperparámetros** (configurables en `config_train.yaml`)

Al igual que en el bi-encoder, los valores siguientes son de referencia. Los hiperparámetros finales por dominio están documentados en:

> 📄 [`training_parameters.md`](./training parameters.md) — Configuraciones concretas y parámetros específicos por dominio (legal, biomédico, patrimonio).

| Parámetro | Valor de referencia |
|---|---|
| `BATCH_SIZE` | 32 |
| `GRADIENT_ACCUMULATION_STEPS` | 8 |
| `LEARNING_RATE` | 4.7e-5 |
| `WARMUP_RATIO` | 0.197829 |
| `WEIGHT_DECAY` | 0.007845 |
| `MAX_SEQ_LENGTH` | 8192 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |

> El batch efectivo del cross-encoder es `BATCH_SIZE × GRADIENT_ACCUMULATION_STEPS = 256`, compensando el mayor coste computacional de la arquitectura.

**Script de entrenamiento**: [`train_cl_crossencoder.py`](../../../models/encoders/train_cl_crossencoder.py)

---

## 4. Estrategia de Evaluación 

La evaluación se realiza al final de cada época mediante un **Information Retrieval Evaluator** que mide la capacidad del modelo de recuperar los documentos relevantes dado un conjunto de queries de validación.

**Métricas principales**

| Métrica | Descripción |
|---|---|
| `MRR@K` | Mean Reciprocal Rank: posición media del primer resultado relevante |
| `NDCG@K` | Normalized Discounted Cumulative Gain: calidad del ranking completo |
| `MAP@K` | Mean Average Precision: precisión media sobre los K primeros resultados |
| `Recall@K` | Proporción de documentos relevantes recuperados entre los K primeros |

El valor de K por defecto es **10** para el bi-encoder y **10** para el cross-encoder (configurable en `config_train.yaml`).

**División de datos**

Del conjunto total de tripletas por fase, se reserva un **5%** como split de validación (`EVAL_SPLIT_RATIO = 0.05`). El 95% restante se usa para entrenamiento.

**Seguimiento de experimentos**

Todos los experimentos se registran en **Weights & Biases** en modo offline. Cada fase genera un run independiente con:
- Nombre de run: `phase{N}_{label}` (e.g. `phase01_facil_random`)
- Grupo: `curriculum` (para visualizar todas las fases juntas)
- Tags: número de fase y etiqueta de dificultad

Para búsqueda de hiperparámetros, se usa **Optuna** con los scripts `train_optuna_biencoder.py` y `train_optuna_crossencoder.py`. Ver [`config_optuna.yaml.example`](../../../models/encoders/config_optuna.yaml.example) para la configuración del estudio.

---

## Referencias

- Bengio, Y., Louradour, J., Collobert, R., & Weston, J. (2009). [Curriculum learning](https://dl.acm.org/doi/10.1145/1553374.1553380). *ICML 2009*.
- Moreira, G. et al. (2024). [NV-Retriever: Improving text embedding models with effective hard-negative mining](https://arxiv.org/abs/2405.15343). *arXiv:2405.15343*.
- Weng, L. (2021). [Contrastive representation learning](https://lilianweng.github.io/posts/2021-05-31-contrastive/). *Lil'Log*.
