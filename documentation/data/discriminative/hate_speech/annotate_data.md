# Annotation Data Process - ALIA Spanish Discriminative Hate Speech Corpus Documentation

This document closes the end-to-end process of building the annotated corpus. The goal of this final stage is simple: take the curated Spanish corpus, annotate it with several LLM experts and fuse those annotations into a single prediction thanks to the best fusion model obtained as a reusable artifact for later analysis.

## 1. Best FoE model search and conducted runs

Based on the FoE experiments described in [foe_experiments.md](foe_experiments.md), the search for the best fusion model was carried out on the four reference datasets used throughout the project: HaSCoSVA, HaterNet, HatEval, and MTLHate. For this final stage, the dataset splits were pooled across corpora in the way described in the FoE methodology: all train splits were combined to fit the candidate fusion models, all validation splits were combined to compare and rank candidates, and all test splits were held back for the final one-time evaluation of the selected artifact.

The actual search was performed as a cross-evaluation over a controlled configuration space of FoE candidates. Each candidate combined the three kinds of inputs: the binary annotations produced by the LLM experts, the embeddings of the comments, and the embeddings of the generated explanations. The ranking criterion was the **pooled validation** `f1_macro`, with `kappa` used as a secondary tie-breaker in the ranking tables.

In summary, the conducted runs in this stage followed this sequence:

1. Pool the train/validation/test splits of the four reference datasets.
2. Train multiple FoE candidates on the pooled train data.
3. Rank candidates by pooled validation `f1_macro`.
4. Select the best candidate configuration.
5. Retrain that configuration as the final persisted model.
6. Evaluate the persisted model once on the pooled test splits and report those metrics as final.

This distinction between the ranked candidate and the retrained persisted model is important for interpreting the numbers in this document: the ranking files tell us which configuration was selected, while the persisted run log tells us the final validation and test performance of the model that was actually kept.

## 2. Best-ranked configuration and results

The top-ranked candidate combines three few-shot prompted experts (`apertus_it_8B`, `gemma_4_31B_it`, and `minimax_m2.5`), `sentence_transformer` embeddings, and the `sentiment_mlp` fusion head. That candidate was selected because it obtained the best pooled validation `f1_macro` in the ranking table, with `kappa` used as a secondary tie-breaker. Its configuration can be summarized as follows:

| Parameter | Value |
|---|---|
| `enhanced_max_features` | `2000` |
| `enhanced_method` | `sentence_transformer` |
| `enhanced_pca_components` | `128` |
| `fusion_architecture.kind` | `sentiment_mlp` |
| `fusion_architecture.hidden_dim` | `1024` |
| `fusion_architecture.dropout` | `0.5` |
| `input_features.binary_annotations` | `true` |
| `input_features.comment_embeddings` | `true` |
| `input_features.explanation_embeddings` | `true` |
| `model_prompt_pairs` | `apertus_it_8B + gemma_4_31B_it + minimax_m2.5` |
| `learning_rate` | `0.001` |
| `batch_size` | `64` |
| `epochs` | `100` |
| `selection_metric` | `f1_macro` |
| `random_state` | `42` |

The metrics that made this configuration the best-ranked candidate were: `f1_macro = 0.8180`, `kappa = 0.6360`, `accuracy = 0.8241`, with `n_test = 7122`.


## 3. Final model and its performance

After the best-ranked configuration was selected, the model was retrained from scratch on the pooled training data and persisted as `fusion_model.pkl`.

The final aggregated validation and test metrics for the persisted model are:

| Split | Accuracy | F1-macro | Kappa |
|---|---:|---:|---:|
| Pooled Validation | 0.8230 | 0.8194 | 0.6389 |
| Pooled Test | 0.8179 | 0.8112 | 0.6225 |

## 4. Annotation process and stats

The curated corpus was annotated automatically by the set of few-shot prompted LLM experts used in this project. Annotations were produced as per-model JSONL files (one record per comment and model) using the pipeline described in [foe_experiments.md](foe_experiments.md).

Below are the verified summary statistics computed on the intersection of the three models `apertus_it_8B`, `gemma_4_31B_it` and `minimax_m2.5`:

| Metric | Value |
|---|---:|
| Number of comments (common IDs) | 228,708 |
| Fleiss' Kappa (3 models) | 0.49827 |
| Global majority-vote hate (%) | 25.97% |
| Global majority-vote no-hate (%) | 74.03% |


Per-model label distribution (on the common IDs):

| Model | Hate (count) | Hate (%) | No-hate (count) | No-hate (%) |
|---|---:|---:|---:|---:|
| apertus_it_8B | 60,323 | 26.38% | 168,385 | 73.62% |
| gemma_4_31B_it | 47,463 | 20.75% | 181,245 | 79.25% |
| minimax_m2.5 | 74,110 | 32.40% | 154,598 | 67.60% |

Majority-vote distribution by source (on the common IDs):

| Source | Total (count) | Hate (count) | Hate (%) | No-hate (count) | No-hate (%) |
|---|---:|---:|---:|---:|---:|
| youtube | 201,612 | 56,812 | 28.18% | 144,800 | 71.82% |
| tiktok | 27,096 | 2,581 | 9.53% | 24,515 | 90.47% |

## 5. FoE classification

The following aggregates are computed over the final corpus in [SINAI/ALIA-es-discriminative-hate-speech](https://huggingface.co/datasets/SINAI/ALIA-es-discriminative-hate-speech).

| Metric | Value |
|---|---:|
| Number of records | 228,708 |
| `foe_class = 0` (no-hate) | 167,774 (73.36%) |
| `foe_class = 1` (hate) | 60,934 (26.64%) |

The distribution of `foe_score` (continuous confidence in the hate prediction) is available as a histogram image: [foe_score_hist.png](foe_score_hist.png).

## 6. Human Validation and Agreement (Prolific)

To validate the quality of the automated annotation pipeline and the Fusion of Experts (FoE) classifier, a validation study was conducted with human annotators through the **[Prolific](https://www.prolific.com/)** platform. All metrics reported below (Fleiss' Kappa, Cohen's Kappa, F1-macro, and Accuracy) are defined in [foe_experiments.md](foe_experiments.md#5-evaluation-metrics) (Section 5).

### Methodology and Participant Selection
- **Annotators**: Three human annotators were selected from the Prolific participant pool based on strict demographic filters to ensure they were representative of the native Spanish context:
  - **Nationality**: Spain
  - **Country of Birth**: Spain
  - **Current Country of Residence**: Spain
  - **First Language**: Spanish
  - **Primary Language**: Spanish
  - **Fluent Languages**: Spanish
- **Sample Selection**: A sample of **3,000 comments** was selected using a source-balanced stratified diversity sampling methodology:
  - **Stratification**: The sample is equally divided across the content sources (YouTube and TikTok), targeting 1,500 comments per source. Within each source, the selection is further stratified to preserve the exact proportion of positive (hate) and negative (non-hate) predictions generated by the FoE model.
  - **Candidate Prefiltering**: For each stratum (source and label combination), comments are vectorized using TF-IDF (unigrams and bigrams, up to 50,000 features). To ensure memory efficiency, a candidate pool of the top 4,000 most representative comments (highest cosine similarity to the stratum's average TF-IDF vector/centroid) is pre-filtered.
  - **MMR Diversity Selection**: Within each candidate pool, Maximal Marginal Relevance (MMR) is applied with a diversity weight of $\lambda = 0.7$. This iteratively selects comments that are highly representative of the stratum's semantic core while minimizing similarity to comments already selected, maximizing semantic diversity in the final sample.
- **Anonymization**: Human annotators' Prolific identifiers have been anonymized in the reports as `Annotator 1`, `Annotator 2`, and `Annotator 3`.

### Annotation Study

To collect the human annotations, a study was launched on the Prolific platform. The overall annotation of the 3,000 comments was divided into 6 sequential parts. Each part consisted of 5 Google Forms, and each form contained 100 comments to annotate (amounting to 500 comments per part). Three Spanish native participants (referred to as Annotators 1, 2, and 3) completed all 6 parts, resulting in 3,000 annotated comments per participant (for a total of 9,000 annotations).

The following is the original study description and annotation guide provided to the human annotators in Spanish (shown here as presented in the first part of the study):

> Este estudio constituye la **PRIMERA PARTE** de una exhaustiva y exigente tarea de anotación en la que requerimos 3 participantes para anotar un total de 3000 comentarios recopilados de redes sociales como YouTube o TikTok, contextualizados durante períodos de disturbios sociales y tensión comunitaria sobre temas relacionados con la inmigración, el racismo, y sus respectivas vertientes políticas.
> 
> La tarea consiste en determinar la presencia de discurso de odio en estos comentarios. Para ello, en este estudio se ofrecerán los primeros 5 enlaces a formularios de Google en los que se presentan 100 comentarios a anotar en cada uno, divididos en lotes de 20 comentarios por página. Es decir, cada participante deberá anotar un total de 500 comentarios para completar este estudio.
> 
> Cada formulario se estima que será completado en 1 hora. Por tanto, completar todos los formularios de este estudio requiere un trabajo de anotación total de 5 horas. Esa es la duración asignada a este estudio, sin embargo, los primeros participantes en completarlo seguirán siendo recompensados siempre y cuando no superen el tiempo máximo establecido por la plataforma.
> 
> Los usuarios que accedan a participar en este estudio deberán compartir su id de Prolific al inicio de cada formulario. Se ruega compromiso total de los participantes en esta tarea, asumiendo que su participación en esta primera parte supone su participación en posteriores estudios. Al final del último formulario, se proporcionará enlace y código de finalización de Prolific.
> 
> Por favor, lean atentamente cada comentario y presten especial atención a la definición de discurso de odio proporcionada de forma visible en cada formulario. No duden en contactar ante cualquier incidencia.
> 
> #### Instrucciones de anotación
> Este corpus contiene una muestra de 100 registros de comentarios recopilados en redes sociales como YouTube o TikTok durante períodos de disturbios sociales y tensión comunitaria, tratando temas relacionados con la inmigración, el racismo, y sus respectivas vertientes políticas.
> 
> Tu tarea consiste en indicar si existe presencia de discurso de odio o no en dicho comentario. Se advierte al usuario de la presencia de hasta 5 registros adicionales que deberán ser ignorados.
> 
> Un mensaje contiene discurso de odio cuando cumple AL MENOS UNO de estos criterios:
> - Incita, promueve o justifica violencia física contra personas o grupos específicos.
> - Deshumaniza o utiliza lenguaje degradante hacia colectivos vulnerables (por raza, etnia, religión, género, orientación sexual, nacionalidad, discapacidad, edad, identidad de género, situación socioeconómica).
> - Llama explícitamente a discriminar, segregar o excluir a grupos protegidos.
> - Glorifica, celebra o trivializa actos violentos contra grupos vulnerables.
> - Utiliza eslóganes, símbolos o retórica de grupos extremistas conocidos.
> - Promueve estereotipos negativos dañinos de forma implícita o mediante sarcasmo.
> 
> Por otra parte, no se considera discurso de odio:
> - Crítica política o social, aunque sea dura o polarizada.
> - Expresiones de frustración, enfado o insultos genéricos sin objetivo grupal.
> - Sátira, ironía o humor, aunque sea de mal gusto.
> - Información factual sobre eventos violentos sin promoción.
> - Opiniones controversiales que no inciten a violencia o discriminación.
> 
> ##### Ejemplos de referencia:
> 
> ###### ODIO EXPLÍCITO
> - **Ejemplo 1**: Los musulmanes con algún poder son una amenaza para la civilización
>   - **Etiqueta**: Odio (1)
>   - **Justificación**: El comentario incita al odio contra los musulmanes porque contiene descripciones con atributos muy negativos que promueven el prejuicio y la discriminación.
> - **Ejemplo 2**: Las personas homosexuales pertenecen al zoológico.
>   - **Etiqueta**: Odio (1)
>   - **Justificación**: El comentario incita el odio hacia los homosexuales porque contiene una descalificación implícita que compara a los homosexuales con animales.
> 
> ###### ODIO IMPLÍCITO
> - **Ejemplo 3**: Deberíamos probar los nuevos medicamentos en inmigrantes antes de probarlos en animales.
>   - **Etiqueta**: Odio (1)
>   - **Justificación**: El comentario incita el odio contra los inmigrantes porque contiene un menosprecio implícito que sugiere que los inmigrantes no merecen vivir y son inferiores a los animales.
> - **Ejemplo 4**: Los musulmanes siempre se sienten provocados y ofendidos... por eso hay que prohibir el islam en las democracias.
>   - **Etiqueta**: Odio (1)
>   - **Justificación**: El comentario incita al odio hacia los musulmanes porque da a entender que son demasiado sensibles.
> 
> ###### LENGUAJE CIFRADO
> - **Ejemplo 5**: Hay que defender a los ciudadanos españoles de los que vienen a robarnos el trabajo.
>   - **Etiqueta**: Odio (1)
>   - **Justificación**: El comentario incita el odio hacia los inmigrantes porque la frase "de los que vienen a robarnos el trabajo" puede ser un mensaje encubierto que refuerza los estereotipos antiinmigrantes perjudiciales.
> 
> ###### INSULTOS REAPROPIADOS
> - **Ejemplo 6**: Guárdate tus opiniones para ti mismo. Somos maricones y estamos orgullosos de ello.
>   - **Etiqueta**: No odio (0)
>   - **Justificación**: El comentario no incita al odio. Miembros del grupo al que hace alusión el insulto utilizan el propio insulto como símbolo de empoderamiento y orgullo.
> 
> ###### DENUNCIA O CONTRA-DISCURSO
> - **Ejemplo 7**: En solo 5 minutos, un fan me ha llamado tóxico y neonazi por no gustarme esta serie.
>   - **Etiqueta**: No odio (0)
>   - **Justificación**: Este comentario no incita al odio porque cita insultos para reportarlos, criticarlos o narrar una experiencia de victimización.

### Human Annotation Statistics
- **Annotated samples**: 3,000 comments per annotator (total of 9,000 annotations).
- **Included users**: 3 annotators.

#### Annotations per User

| Annotator | Total Annotations | Non-hate | Hate | % Non-hate | % Hate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Annotator 1 | 3,000 | 2,715 | 285 | 90.500% | 9.500% |
| Annotator 2 | 3,000 | 2,538 | 462 | 84.600% | 15.400% |
| Annotator 3 | 3,000 | 2,749 | 251 | 91.633% | 8.367% |
| **Total (All Annotations)** | **9,000** | **8,002** | **998** | **88.911%** | **11.089%** |

### Agreement between Annotators and FoE Model
- **Fleiss' Kappa (Annotators + FoE)**: **0.309** (indicating moderate agreement).

### Agreement between Human Annotators

| Annotator A | Annotator B | Accuracy | F1-macro | Cohen's Kappa |
| --- | --- | ---: | ---: | ---: |
| Annotator 1 | Annotator 3 | 0.856 | 0.557 | 0.115 |
| Annotator 1 | Annotator 2 | 0.892 | 0.753 | **0.510** |
| Annotator 3 | Annotator 2 | 0.811 | 0.549 | 0.108 |

### Agreement between Human Annotators vs FoE

| Annotator | Accuracy vs FoE | F1-macro vs FoE | Cohen's Kappa vs FoE |
| --- | ---: | ---: | ---: |
| Annotator 1 | 0.866 | 0.737 | **0.485** |
| Annotator 2 | 0.837 | 0.723 | **0.448** |
| Annotator 3 | 0.774 | 0.541 | 0.108 |

### Dataset Models vs Each Human Annotator

| Annotator | Model | Accuracy | F1-macro | Cohen's Kappa |
| --- | --- | ---: | ---: | ---: |
| Annotator 1 | `apertus_it_8B` | 0.833 | 0.649 | 0.308 |
| Annotator 1 | `gemma_4_31B_it` | 0.883 | 0.744 | **0.495** |
| Annotator 1 | `minimax_m2.5` | 0.798 | 0.667 | 0.369 |
| Annotator 1 | `majority_vote(apertus_it_8B, gemma_4_31B_it, minimax_m2.5)` | 0.873 | 0.737 | **0.482** |
| Annotator 2 | `apertus_it_8B` | 0.803 | 0.647 | 0.295 |
| Annotator 2 | `gemma_4_31B_it` | 0.903 | 0.820 | **0.640** |
| Annotator 2 | `minimax_m2.5` | 0.820 | 0.734 | **0.479** |
| Annotator 2 | `majority_vote(apertus_it_8B, gemma_4_31B_it, minimax_m2.5)` | 0.879 | 0.786 | **0.572** |
| Annotator 3 | `apertus_it_8B` | 0.802 | 0.568 | 0.153 |
| Annotator 3 | `gemma_4_31B_it` | 0.798 | 0.543 | 0.100 |
| Annotator 3 | `minimax_m2.5` | 0.711 | 0.512 | 0.083 |
| Annotator 3 | `majority_vote(apertus_it_8B, gemma_4_31B_it, minimax_m2.5)` | 0.794 | 0.559 | 0.137 |

## **Example Record (random sample)**

Below is a randomly selected example from the final corpus (fields of interest shown):

```json
{
  "id": "record_199077",
  "source": "youtube",
  "text": "Moros fuera TVE sicópatas iros a marruecos",
  "foe_class": 1,
  "foe_score": 0.9392520189285278,
  "apertus_it_8B": {
    "class": 1,
    "explanation": "El comentario contiene lenguaje degradante hacia colectivos vulnerables (moros) y utiliza un término despectivo (sicópatas) que deshumaniza a las personas de origen marroquí. Además, incita a la discriminación y exclusión al pedir que se vayan a Marruecos."
  },
  "gemma_4_31B_it": {
    "class": 1,
    "explanation": "El comentario constituye discurso de odio ya que utiliza el término 'moros' de forma despectiva y exige la expulsión de un grupo basado en su origen nacional o etnia ('fuera', 'iros a marruecos'). Esto cumple con los criterios de llamar explícitamente a la exclusión y segregación de un grupo protegido, promoviendo la xenofobia."
  },
  "minimax_m2.5": {
    "class": 1,
    "explanation": "El comentario 'Moros fuera TVE sicópatas iros a marruecos' contiene discurso de odio porque utiliza el término despectivo 'moros' para referirse a personas de origen árabe o norteafricano, lo cual es un insulto étnico. La expresión 'fuera' implica una llamada a la expulsión o exclusión de este colectivo, lo cual constituye incitación a la discriminación y segregación. Además, el insulto 'sicópatas' directed toward TVE (la televisión pública española) y la orden 'iros a marruecos' refuerzan el mensaje de rechazo hacia personas de origen marroquí o magrebí. El comentario combina un insulto étnico con una llamada explícita a la exclusión, cumpliendo los criterios de discurso de odio."
  }
}
```

The example above illustrates how the per-expert annotations, the fused `foe_score` and the final `foe_class` are stored together for each comment in the released corpus.

