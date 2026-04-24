# Configuraciones de Modelos Entrenados

Parámetros específicos usados en el entrenamiento de cada modelo por dominio y arquitectura.
Para entender la metodología general ver [metodology.md](./metodology.md).

*Proyecto ALIA*

---

## Índice
- [Búsqueda de Hiperparámetros](#busqueda-de-hiperparametros)
- [Dominio Legal](#dominio-legal)
  - [Bi-Encoder Legal](#bi-encoder-legal)
  - [Cross-Encoder Legal](#cross-encoder-legal)
- [Dominio Biomédico](#dominio-biomédico)
  - [Bi-Encoder Biomédico](#bi-encoder-biomédico)
  - [Cross-Encoder Biomédico](#cross-encoder-biomédico)
- [Dominio Patrimonio](#dominio-patrimonio)
  - [Bi-Encoder Patrimonio](#bi-encoder-patrimonio)
  - [Cross-Encoder Patrimonio](#cross-encoder-patrimonio)

---
## Búsqueda de Hiperparámetros
La búsqueda de hiperparámetros se realizó de forma común para los tres dominios (Legal, Biomédico y Patrimonio) utilizando Optuna con el estimador TPE. En todos los casos se ejecutaron 20 trials con un Median Pruner (3 startup trials), utilizando NDCG@10 como métrica de evaluación y selección.

El espacio de búsqueda fue prácticamente idéntico para ambas arquitecturas (explorando valores log-uniformes para el learning rate y uniformes para warmup ratio y weight decay). La única diferencia radicó en la gestión del tamaño del lote según la arquitectura:

- Para los modelos Bi-Encoder: Se optimizó el parámetro mini-batch size (valores categóricos: 1, 4, 8, 12).
- Para los modelos Cross-Encoder: Al operar como rerankers más pesados computacionalmente, se fijó el batch size y se optimizó el parámetro de gradient accumulation steps (valores categóricos: 4, 8, 16, 32).

Nota: Como configuración general, las pruebas del bi-encoder usaron 5.000 ejemplos de entrenamiento por trial, mientras que las del cross-encoder utilizaron 1.000, ambos con semilla 42 y un split de validación del 5%.

| Hiperparámetro | Espacio de búsqueda |
|---|---|
| Learning rate | [1e-6, 5e-5] log-uniforme |
| Warmup ratio | [0.05, 0.20] uniforme |
| Weight decay | [0.00, 0.10] uniforme |
| Mini-batch size | {1, 4, 8, 12} categórico |
| Gradient accum. steps | {4, 8, 16, 32} categórico |

## Dominio Legal

> 📄 Referencia: *TITLE* — JOURNAL 2026.

**Estadísticas del dataset de hard negatives**

| Dificultad | Estrategia | Hard Negatives |
|---|---|---|
| Fácil | Random / PAM | 36.665 |
| Medio | Random / PAM | 842.911 |
| Difícil | Random / PAM | 19.361 |

### Bi-Encoder Legal

| Parámetro | Valor |
|---|---|
| Modelo base | `MrBERT-es` |
| `BATCH_SIZE` | 256 |
| `CACHE_MINI_BATCH_SIZE` | 4 |
| `LEARNING_RATE` | 5e-5 |
| `WARMUP_RATIO` | 0.160 |
| `WEIGHT_DECAY` | 0.020 |
| `MAX_SEQ_LENGTH` | 2048 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |
| Tiempo de entrenamiento | ~77 horas (4× NVIDIA A100 40GB) |
| Modelo publicado | [ALIA-MrBERT-es-legal-embeddings](https://huggingface.co/SINAI/ALIA-MrBERT-es-legal-embeddings) |

**Fases de entrenamiento**

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 1 | Random | Fácil | 2 | Sin límite |
| 2 | Random | Medio | 2 | Sin límite |
| 3 | Random | Difícil | 2 | Sin límite |
| 4 | PAM (hard negatives) | Fácil | 1 | Sin límite |
| 5 | PAM (hard negatives) | Medio | 1 | Sin límite |
| 6 | PAM (hard negatives) | Difícil | 1 | Sin límite |

**Curva de entrenamiento**

La pérdida de entrenamiento descendió de 0.0852 a 0.0242 a lo largo del proceso, una reducción del 71.6%, con convergencia estable sin signos de inestabilidad.

**Notas**

> 

---

### Cross-Encoder Legal

| Parámetro | Valor |
|---|---|
| Modelo base | `MrBERT-es` |
| Parámetros | ~150M |
| `BATCH_SIZE` | 32 |
| `GRADIENT_ACCUMULATION_STEPS` | 8 |
| Batch efectivo | 256 |
| `LEARNING_RATE` | 5e-5 |
| `WARMUP_RATIO` | 0.110 |
| `WEIGHT_DECAY` | 0.036 |
| `MAX_SEQ_LENGTH` | 2048 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |
| Tiempo de entrenamiento | ~14 horas (4× NVIDIA A100 40GB) |
| Modelo publicado | [ALIA-MrBERT-es-legal-reranker](https://huggingface.co/SINAI/ALIA-MrBERT-es-legal-reranker) |

**Fases de entrenamiento**

El cross-encoder solo entrena en las fases de hard negatives (PAM), ya que como reranker solo necesita distinguir entre candidatos ya considerados relevantes por el bi-encoder.

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 4 | PAM (hard negatives) | Fácil | 1 | Sin límite |
| 5 | PAM (hard negatives) | Medio | 1 | Sin límite |
| 6 | PAM (hard negatives) | Difícil | 1 | Sin límite |

**Curva de entrenamiento**

La pérdida descendió de 0.0749 a 0.0318, una reducción del 57.5%, con convergencia estable a lo largo del proceso.

**Notas**

> 

---

## Dominio Biomédico

> 📄 Referencia: *TITLE* — JOURNAL 2026.

**Estadísticas del dataset de hard negatives**

| Dificultad | Estrategia | Hard Negatives |
|---|---|---|
| General | Random / PAM | 15.527 |
| Fácil | Random / PAM | 87.246 |
| Medio | Random / PAM | 401.622 |
| Difícil | Random / PAM | 248.258 |

### Bi-Encoder Biomédico

| Parámetro | Valor |
|---|---|
| Modelo base | `MODEL_PATH` |
| `BATCH_SIZE` | 128 |
| `CACHE_MINI_BATCH_SIZE` | 4 |
| `LEARNING_RATE` | 5e-05 |
| `WARMUP_RATIO` | 0.159500633 |
| `WEIGHT_DECAY` | 0.021437163 |
| `MAX_SEQ_LENGTH` | 8,192 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |
| Modelo publicado | [ALIA-MrBERT-es-biomedical-embeddings](https://huggingface.co/SINAI/ALIA-MrBERT-es-biomedical-embeddings) |

**Fases de entrenamiento**

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 1 | Random | General | 2 | Sin límite |
| 2 | Random | Fácil | 2 | Sin límite |
| 3 | Random | Medio | 2 | 248.258 |
| 4 | Random | Difícil | 2 | Sin límite |
| 5 | PAM (hard negatives) | General | 1 | Sin límite |
| 6 | PAM (hard negatives) | Fácil | 1 | Sin límite |
| 7 | PAM (hard negatives) | Medio | 1 | 248.258 |
| 8 | PAM (hard negatives) | Difícil | 1 | Sin límite |

**Curva de entrenamiento**

La pérdida bajó de 1.7914 a 0.0032 (↓ 99.8%). Caída drástica en la Fase 1. El modelo asimiló los negativos aleatorios casi de inmediato y mantuvo una estabilidad total incluso al introducir los negativos más difíciles (fases 6-8), mostrando una convergencia casi perfecta.

**Notas**

> Se añadieron datos genéricos al entrenamiento de este modelo, lo que supone una mejora directa sobre el pipeline inicial empleado en el modelo del dominio legal. Además, con el objetivo de equilibrar las distribuciones de los datos, se ajustó el límite máximo del conjunto de dificultad media para que tuviese exactamente el mismo tamaño que el conjunto de dificultad difícil.

---

### Cross-Encoder Biomédico

| Parámetro | Valor |
|---|---|
| Modelo base | `MODEL_PATH` |
| `BATCH_SIZE` | 32 |
| `GRADIENT_ACCUMULATION_STEPS` | 4 |
| `LEARNING_RATE` | 5×10⁻⁵ |
| `WARMUP_RATIO` | 0.13456696 |
| `WEIGHT_DECAY` | 0.04160315 |
| `MAX_SEQ_LENGTH` | 8,192 |
| Precisión | bf16 |
| Gradient checkpointing | Sí |
| Modelo publicado | [ALIA-MrBERT-es-biomedical-reranker](https://huggingface.co/SINAI/ALIA-MrBERT-es-biomedical-reranker) |

**Fases de entrenamiento**

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 1 | Random | General | 2 | Sin límite |
| 2 | PAM (hard negatives) | Fácil | 1 | Sin límite |
| 3 | PAM (hard negatives) | Medio | 1 | 248.258 |
| 4 | PAM (hard negatives) | Difícil | 1 | Sin límite |
| 5 | PAM (hard negatives) | General | 1 | Sin límite |

**Curva de entrenamiento**

La pérdida bajó de 0.7287 a 0.0507 (↓ 93.0%). Descenso progresivo y fluido a través de las fases de dificultad. Al igual que en otros dominios, la Fase 5 (General Top) presentó un reto inicial con un pequeño pico de pérdida, pero el modelo lo corrigió rápidamente para cerrar con alta precisión.

**Notas**

> Al igual que en el bi-encoder biomédico, el pipeline incorpora datos genéricos mejorando la versión inicial (dominio legal) y se ha limitado el tamaño máximo del conjunto de dificultad media para que coincida en tamaño con el conjunto de dificultad difícil, garantizando un mejor balance durante el entrenamiento del reranker.

---

## Dominio Patrimonio

> 📄 Referencia: *TITLE* — JOURNAL 2026.

**Estadísticas del dataset de hard negatives**
| Dificultad | Estrategia | Hard Negatives |
|---|---|---|
| General | Random / PAM | 15.527 |
| Fácil | Random / PAM | 207.376 |
| Medio | Random / PAM | 383.208 |
| Difícil | Random / PAM | 101.352 |

### Bi-Encoder Patrimonio

| Parámetro | Valor |
|---|---|
| Modelo base | `MrBERT-es` |
| `BATCH_SIZE` | 32 |
| `CACHE_MINI_BATCH_SIZE` | 4 |
| `LEARNING_RATE` | 4.7e-5 |
| `WARMUP_RATIO` | 0.197829 |
| `WEIGHT_DECAY` | 0.007845 |
| `MAX_SEQ_LENGTH` | 8192 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |
| Modelo publicado | [ALIA-MrBERT-es-patrimonio-embeddings](https://huggingface.co/SINAI/ALIA-MrBERT-es-patrimonio-embeddings) |

**Fases de entrenamiento**

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 1 | Random | General | 2 | Sin límite |
| 2 | Random | Fácil | 2 | 100.000 |
| 3 | Random | Medio | 2 | 100.000 |
| 4 | Random | Difícil | 2 | 100.000 |
| 5 | PAM (hard negatives) | General | 1 | Sin límite |
| 6 | PAM (hard negatives) | Fácil | 1 | 100.000 |
| 7 | PAM (hard negatives) | Medio | 1 | 100.000 |
| 8 | PAM (hard negatives) | Difícil | 1 | 100.000 |

**Curva de entrenamiento**

La curva muestra una caída drástica inicial durante la Fase 1 (General Random), partiendo de una pérdida de 4.7638. Se observa una estabilización casi total a partir de la Fase 2, con un ligero repunte controlado al inicio de la Fase 5 (General Top) al introducir negativos más difíciles, para finalmente converger en un valor residual de 0.0067.

**Notas**

> Se limitó el número máximo de mensajes por fase a 100.000.

---

### Cross-Encoder Patrimonio

| Parámetro | Valor |
|---|---|
| Modelo base | `MrBERT-es` |
| `BATCH_SIZE` | 32 |
| `GRADIENT_ACCUMULATION_STEPS` | 8 |
| `LEARNING_RATE` | 4.7e-5 |
| `WARMUP_RATIO` | 0.197829 |
| `WEIGHT_DECAY` | 0.007845 |
| `MAX_SEQ_LENGTH` | 8192 |
| Precisión | bfloat16 |
| Gradient checkpointing | Sí |
| Modelo publicado | [ALIA-MrBERT-es-patrimonio-reranker](https://huggingface.co/SINAI/ALIA-MrBERT-es-patrimonio-reranker) |

**Fases de entrenamiento**

| Fase | Tipo de negativos | Dificultad | Épocas | Muestras máx. |
|---|---|---|---|---|
| 1 | Random | General | 2 | Sin límite |
| 2 | PAM (hard negatives) | Fácil | 1 | 100.000 |
| 3 | PAM (hard negatives) | Medio | 1 | 100.000 |
| 4 | PAM (hard negatives) | Difícil | 1 | 100.000 |
| 5 | PAM (hard negatives) | General | 1 | Sin límite |

**Curva de entrenamiento**

A diferencia del Bi-Encoder, el Cross-Encoder presenta una curva con mayores fluctuaciones entre fases:

- Fases 1-4: Descenso progresivo de la pérdida desde 0.4711 hasta niveles cercanos a 0.02.
- Fase 5 (General Top): Se aprecia un "salto" o pico de pérdida al inicio de esta fase (aprox. 0.15), indicando que el cambio a negativos de tipo "Top" supuso un desafío mayor para el re-ranker, logrando reconducir el aprendizaje hasta un valor final de 0.0579.

**Notas**

> Se limitó el número máximo de mensajes por fase a 100.000.
