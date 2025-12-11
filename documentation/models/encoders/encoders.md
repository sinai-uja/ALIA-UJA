**Comparativa entre modelos de Embedding (Bi-Encoder) y modelos Reranker (Cross-Encoder)**

Descripción del framework y parámetros de entrenamiento para modelos de embeddings y reranker

*Alba María Mármol Romero | amarmol@ujaen.es | Proyecto Vandelvira*

---

# Introducción

En tareas de recuperación de información y búsqueda semántica, se emplean habitualmente dos tipos de arquitecturas: bi-encoders (embedding models) y cross-encoders (rerankers). Ambos tienen como objetivo medir la relevancia entre pares de textos (por ejemplo, una pregunta y un documento), pero lo hacen de maneras muy diferentes y con distintas implicaciones en cuanto a eficiencia y rendimiento.

# Estructura y funcionamiento

| Característica           | Bi-Encoder (Embedding Model)       | Cross-Encoder (Reranker)           |
|--------------------------|------------------------------------|------------------------------------|
| Arquitectura             | Dos codificadores independientes   | Un solo codificador conjunto       |
| Procesamiento            | Consulta y documento por separado  | Consulta y documento juntos        |
| Interacción entre textos | Limitada o inexistente             | Completa y contextualizada         |
| Velocidad de inferencia  | Muy rápida                         | Más lenta                          |
| Escalabilidad            | Alta (permite precomputar)         | Baja (procesamiento en línea)      |
| Precisión                | Moderada                           | Alta                               |
| Casos de uso             | Recuperación inicial, ANN          | Reranking, tareas contextuales     |


## Embedding Models (Bi-Encoder)

* Arquitectura: En un modelo bi-codificador, existen dos codificadores independientes: uno para codificar la consulta y otro para codificar los documentos candidatos. Estos codificadores no comparten parámetros (aunque a veces pueden estar inicializados de la misma forma). 
* Funcionamiento: Cada texto (consulta o documento) se transforma en un vector de embedding de manera independiente. 
* Entrenamiento: Se entrena con una función de pérdida contrastiva, con el objetivo de: Maximizar la similitud entre la consulta y su documento relevante y ,inimizar la similitud con documentos irrelevantes.
* Ventaja: Muy eficientes, permiten precomputar los vectores de los documentos y hacer búsquedas rápidas con Approximate Nearest Neighbors (ANN).
* Inconveniente: Al no tener acceso cruzado entre tokens de los dos textos, pueden perder matices contextuales.
* Ejemplos: sentence-transformers como all-MiniLM-L6-v2, BGE, GTR, Contriever.

### [SWIFT - Embedding Training](https://swift.readthedocs.io/en/latest/BestPractices/Embedding.html)

SWIFT permite el entrenamiento de modelos de embeddings. SWIFT actualmente soporta entrenamiento con una serie de modelos indicados, sin embargo, se pueden integrar modelos propios asegurando que el forward del modelo devuelva: `{"last_hidden_state": embedding_tensor}`. Además, se debe añadir una capa de normalización al final del forward.

Para convertir cualquier otro modelo en un modelo de embeddings, simplemente se puede añadir el parámetro: `--task_type embedding`

Formatos de dataset soportados por SWIFT para el entrenamiento de modelos de embeddings (cada uno corresponde a una forma distinta de calcular la pérdida durante el entrenamiento):

* Cosine Similarity Loss: Minimiza la diferencia entre la similitud coseno del par de embeddings y una etiqueta real (un valor entre -1 y 1). Es decir, se espera que si dos frases son muy similares, el modelo aprenda a generar embeddings con alta similitud coseno (valor cercano a 1); si no lo son, la similitud debe ser más baja.Formato del dataset (texto puro - LLM): `{"query": "sentence1", "response": "sentence2", "label": 0.8}`
* Contrastive Loss: Busca que los embeddings de pares positivos (label=1) estén cerca y los de pares negativos (label=0) estén lejos, hasta cierto margen. Formato del dataset (LLM): `{"query": "sentence1", "response": "sentence2", "label": 1}`
* Online Contrastive Loss: Es una variante dinámica del anterior. En lugar de usar pares fijos, genera automáticamente pares positivos y negativos dentro del batch, buscando los más difíciles (hard positives/negatives).
* InfoNCE Loss: Aprende a distinguir el par positivo (query y response) de todos los demás pares dentro del batch, considerándolos como negativos. El objetivo es que
el embedding de la query esté más cerca de su response que de cualquier otro response del batch. Formatos: `{"query": "sentence1", "response": "sentence2"}` ; `{"query": "parís es la capital de francia", "response": "la capital de francia es parís", "rejected_response": ["roma es la capital de italia", "berlín es la capital de alemania"]}`.

#### Script templates
* [EMB Model](https://github.com/tastelikefeet/swift/blob/main/examples/train/embedding/train_emb.sh)
* [GME Model](https://github.com/tastelikefeet/swift/blob/main/examples/train/embedding/train_gme.sh)

##  Reranker Models (Cross-Encoder)

* Arquitectura: En el codificador cruzado, la consulta y el documento se procesan conjuntamente en una única secuencia mediante un solo codificador. 
* Funcionamiento: Se concatenan el par de textos como una sola secuencia ([CLS] query [SEP] doc [SEP]). El modelo aprende directamente a predecir un score de relevancia entre ambos.
* Entrenamiento: Se entrena para maximizar la puntuación de pares relevantes y minimizarla para irrelevantes. Sin embargo, al tener acceso a ambas entradas simultáneamente, aprende interacciones más ricas y dependientes del contexto.
* Ventaja: Mayor precisión, ya que el modelo tiene acceso cruzado completo a todos los tokens.
* Inconveniente: Costoso computacionalmente. No se pueden precomputar los embeddings. No escalable para búsquedas a gran escala.
* Ejemplos: Modelos de la familia cross-encoder/ms-marco, MonoT5, cohere-rerank.

### [SWIFT - Reranker Training](https://swift.readthedocs.io/en/latest/BestPractices/Reranker.html)

SWIFT permite el entrenamiento de modelos de reranking. SWIFT soporta dos tipos de arquitectura de Reranker (por clasificación o generativo) y dos formas de calcular la pérdida *(loss)* (pointwise y listwise).

#### Arquitectura

**Reranker por Clasificación**

* Usa modelos como BERT o modernbert-reranker.
* Arquitectura: Añade una cabeza de clasificación sobre un modelo tipo BERT.
* Entrada: Un par query-document.
* Salida: Un único valor escalar (p. ej. 0.83) que representa la relevancia.
* Entrena usando: funciones de pérdida tipo clasificación (pointwise o listwise).

**Reranker Generativo**

* Usa modelos tipo Qwen3 (0.6B, 4B, 8B).
* Arquitectura: Basado en modelos generativos (CausalLM).
* Entrada: Un par query-document.
* Salida: La probabilidad de generar un token como "yes" o "no".
* Se clasifica comparando la probabilidad de tokens positivos y negativos (como logits de "yes" vs "no").
#### Script templates
* [Pointwise Classification Reranker](https://github.com/tastelikefeet/swift/blob/main/examples/train/reranker/train_reranker.sh)
* [Pointwise Generative Reranker](https://github.com/tastelikefeet/swift/blob/main/examples/train/reranker/train_generative_reranker.sh)

#### Cálculo de pérdida

**Entrenamiento Pointwise (por pares)**

Transforman el problema de clasificación en un problema de clasificación binaria, procesando cada par consulta-documento de forma independiente:
* Idea central: Clasificación binaria por cada par query-document.
* Función de pérdida: Binary Cross-Entropy.
* Casos de uso: Simplicidad y eficiencia, ideal para datasets a gran escala.

**Entrenamiento Listwise (por grupos)**

Transforman el problema de clasificación en un problema de clasificación múltiple, seleccionando ejemplos positivos de múltiples documentos candidatos:
* Idea central: Clasificación multiclase en grupos (1 positivo + N negativos).
* Función de pérdida: Multi-class Cross-Entropy.
* Casos de uso: Aprende relaciones relativas entre documentos, mejor alineado con tareas reales de ranking.
#### Script templates
* [Listwise Classification Reranker](https://github.com/tastelikefeet/swift/blob/main/examples/train/reranker/train_reranker_listwise.sh)
* [Listwise Generative Reranker](https://github.com/tastelikefeet/swift/blob/main/examples/train/reranker/train_generative_reranker_listwise.sh)

# ¿Qué parámetros y entrenamiento siguen los modelos Qwen?
Qwen3 hace uso de ms-swift y aplica tres etapas de entrenamiento:
1. Preentrenamiento con datos sintéticos (150M pares) --> Solamente para el modelo de embeddings
    * Sintetizados usando LLMs (Qwen3-32B)
    * Datos variados: retrieval, STS, clasificación, bitext
    * Generación controlada con "personas", dificultad, tipo, idioma
2. Fine-tuning supervisado (20M pares) --> Tanto para embeddings como reranker
    * Dataset supervisado = 7M humanos + 12M sintéticos filtrados
    * Filtro basado en cosine_sim > 0.7
    * Tareas múltiples: MS MARCO, NQ, HotpotQA, etc.
3. Model merging (SLERP interpolation) --> Tanto para embeddings como reranker
    * Mezcla de checkpoints tras el fine-tuning (mejora generalización y robustez).

**Parámetros adicionales**
* Función de pérdida para embeddings: Esta pérdida se basa en InfoNCE, una pérdida contrastiva que busca acercar las parejas positivas (query-documento relevante) y alejar las negativas.
* Función de pérdida para Reranking: es una pérdida de clasificación binaria supervisada (SFT) --> Pointwise Generative Reranker

# Más información
* [Cross encoders and bi-encoders - Medium](https://medium.com/@bhawana.prs/cross-encoders-and-bi-encoders-23373414f6fd)
* [Mastering Text Embedding and Reranker with Qwen3 - alibabacloud](https://www.alibabacloud.com/blog/mastering-text-embedding-and-reranker-with-qwen3_602308#:~:text=While%20embedding%20models%20retrieve%20broad,Web%20search%20and%20recommendation%20systems)
* [Training and Finetuning Reranker Models with Sentence Transformers v4 - Huggingface](https://huggingface.co/blog/train-reranker)






