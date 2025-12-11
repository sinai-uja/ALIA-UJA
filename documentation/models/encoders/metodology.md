*Metodología de entrenamiento de modelos discriminativos*

Descripción de la metodología completa seguida para obtener los modelos bi-encoders y cross-encoders.

*Alba María Mármol Romero, Arturo Montejo Ráez | amarmol@ujaen.es, amontejo@ujaen.es | Proyecto Vandelvira*

---
# 1. Introducción.
En este proyecto se utiliza el framework [ms-swift](ms-swiftParams.md) para entrenar modelos bi-encoder y cross-encoder. Se eligió por ser open-source, versátil y por ser la base del entrenamiento de la familia de modelos Qwen, líderes en el [leaderboard de MTEB](https://huggingface.co/spaces/mteb/leaderboard), incluso con modelos de tamaño reducido (0.6B). Partiendo de esta base, se presenta la siguiente metodología.

# 2. Generación de conjunto de entrenamiento.
Para el entrenamiento de los modelos bi-encoders y cross-encoders se necesitan datos sintéticos, en este caso, se crean tripletas: `{query, relevant_doc, [irrelevant_doc1, irrelevant_doc2,...]`. Para conocer el proceso completo de creación del conjunto de entrenamiento ver [Flujo de Creación de Datos Sintéticos para Encoders](../../../data/encoders/documentation/flujoDatosSinteticos.md).

# 3. Estrategia de entrenamiento.  
Partimos de N ternas de alta calidad generadas según se especifica en la Sección 2. Usamos 90% para entrenar y 10% para evaluar. Combinamos tres estrategias distintas: 

* *Contrastive learning*: Combinamos ejemplos positivos y negativos para mejorar la separabilidad de los embeddings [(Weng, 2021)](https://lilianweng.github.io/posts/2021-05-31-contrastive/).
* *Curriculum learning*: Entrenamos en diferentes etapas de dificultad progresiva. Por ejemplo: fácil, medio y difícil [(Bengio et al., 2009)](https://dl.acm.org/doi/10.1145/1553374.1553380).
* *Positive-Aware Mining (NVIDIA approach)*: Evitamos falsos negativos usando el score del positivo como referencia [(Moreira et al., 2024)](https://arxiv.org/abs/2407.15831). Solo se considera negativo si: `score < score_positive - margin`. Ejemplo:
    ```
    scores = compute_similarity(query, candidates) # cosine, i.e. dot product
    hard_negatives = candidates[scores < (positive_score_threshold - 0.1)]
    ```

Hacemos un entrenamiento en dos fases, de dificultad progresiva *(curriculum learning)*. 

**FASE 1**: Empezar entrenando con random negatives construyendo lotes *(contrastive learning)* en los que tenemos varias preguntas, los valores objetivo son 1 para la diagonal (pregunta con su contexto correcto) y el resto 0. 
* 6 épocas: 2 épocas preguntas fáciles, 2 preguntas medias, 2 preguntas difíciles.
* 64-128 por lote
* Learning rate: 1e-5

**FASE 2**: Terminamos con *hard-negatives* con un margen de 0.05.
* 3 épocas: 1 época preguntas fáciles, 1 preguntas medias, 1 preguntas difíciles.
* 32 por lote
* Learning rate: 1e-6

Consideraciones adicionales
* Al cambiar de fase hacemos 200 pasos de calentamiento (ratio de aprendizaje incrementa linealmente de 0 a valor nominal).
* En todo momento supervisamos las curvas y la evaluación tras cada época y cada 10,000 pasos.
* Usar LoRA.

### 3.1. Entrenamiento bi-encoder.
* Parámetros usados.
* Script de entrenamiento.

### 3.2. Entrenamiento cross-encoder.
* Parámetros usados.
* Script de entrenamiento.

# 4. Estrategia de evaluación.

# Referencias
* [bRAG with LangChain](https://github.com/BragAI/bRAG-langchain/blob/main/README.md). Documentación y código para montar RAGs con LangChain
* [Research Assistant - NVIDIA Blueprint](https://build.nvidia.com/nvidia/aiq)
* [RAGAS](https://docs.ragas.io/en/stable/). Biblioteca de evaluación para RAG
* [Embedding Leaderboard](https://huggingface.co/spaces/mteb/leaderboard). Un ránking de modelos encoder para considerar como base para los entrenamientos.
* Zhang, Y., Li, M., Long, D., Zhang, X., Lin, H., Yang, B., ... & Zhou, J. (2025). Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models. arXiv preprint [arXiv:2506.05176](https://arxiv.org/abs/2506.05176).
* Ge, T., Chan, X., Wang, X., Yu, D., Mi, H., & Yu, D. (2024). Scaling synthetic data creation with 1,000,000,000 personas. arXiv preprint [arXiv:2406.20094](https://arxiv.org/abs/2406.20094).
* Weng, Lilian. (May 2021). Contrastive representation learning. Lil’Log. [https://lilianweng.github.io/posts/2021-05-31-contrastive/](https://lilianweng.github.io/posts/2021-05-31-contrastive/)
* Bengio, Y., Louradour, J., Collobert, R., & Weston, J. (2009, June). Curriculum learning. In Proceedings of the 26th annual international conference on machine learning (pp. 41-48). [https://dl.acm.org/doi/abs/10.1145/1553374.1553380](https://dl.acm.org/doi/abs/10.1145/1553374.1553380)
* Moreira, G. D. S. P., Osmulski, R., Xu, M., Ak, R., Schifferer, B., & Oldridge, E. (2024). NV-Retriever: Improving text embedding models with effective hard-negative mining. arXiv preprint [arXiv:2407.15831](https://arxiv.org/abs/2407.15831).