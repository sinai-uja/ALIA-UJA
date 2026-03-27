**ms-swift**

Descripción del framework y parámetros de entrenamiento para modelos de embeddings y reranker

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

---

# ¿Qué es MS-Swift?
* Paper: [SWIFT: A Scalable lightWeight Infrastructure for Fine-Tuning (work in progress)](https://arxiv.org/html/2408.05517v3)
* Documentación: [Swift DOCUMENTATION](https://swift.readthedocs.io/en/latest/)
* Repositorio: [modelscope/ms-swift](https://github.com/modelscope/ms-swift)
    * [Preguntas frecuentes](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Frequently-asked-questions.md)

# Command Line Parameters
Los parámetros marcados con 🔥 son importantes. La lista completa de argumentos está disponible en [*Command-line-parameters.md*](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md) del respositorio original.

1. [Base Arguments](#base-arguments)
2. [Model Arguments](#model-arguments)
3. [Data Arguments](#data-arguments)
4. [Template Arguments](#template-arguments)
5. [Generation Arguments](#generation-arguments)
6. [Seq2SeqTrainer Arguments](#seq2seqtrainer-arguments)
7. [Tuner Arguments](#tuner-arguments)
8. [LoRA](#lora)
9. [vLLM](#vllm)
10. [Training Arguments](#training-arguments)
11. [Inference Arguments](#inference-arguments)
12. [Evaluation Arguments](#evaluation-arguments)
13. [Export Arguments](#export-arguments)

## [Base Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#base-arguments)

* 🔥 tuner_backend: Este argumento define qué backend o sistema se utilizará para afinar (tune) el modelo durante el entrenamiento o ajuste fino (fine-tuning). Es un parámetro clave para configurar cómo se realizará la adaptación del modelo. Opciones disponibles:
    *  `peft` (por defecto): Hace referencia a PEFT (Parameter-Efficient Fine-Tuning), una técnica que permite afinar modelos grandes modificando solo una pequeña parte de los parámetros, como LoRA, AdaLoRA, etc. Es eficiente en memoria y tiempo de entrenamiento. Ideal cuando tienes recursos limitados.
    * `unsloth`: Usa el enfoque de Unsloth, que es una variante optimizada de PEFT. Se enfoca en hacer que el entrenamiento de LLMs sea más rápido y eficiente, especialmente con adaptadores como LoRA. Es compatible con modelos y pipelines aceleradas, especialmente útiles para entornos de bajo coste o notebooks.

* 🔥train_type: Este parámetro indica el tipo de entrenamiento o técnica de fine-tuning que se va a utilizar sobre el modelo. Define cómo se ajustarán los pesos del modelo base durante el entrenamiento. Cada opción representa una técnica diferente, con ventajas y limitaciones según el caso de uso, la eficiencia deseada y la arquitectura del modelo.  Opciones disponibles:
    *  `lora` (por defecto): Low-Rank Adaptation. Técnica PEFT muy popular. Solo entrena unas capas adicionales de bajo rango, reduciendo el coste de entrenamiento. Ideal para fine-tuning de modelos grandes con pocos recursos.
    *  `full`: Entrena todos los parámetros del modelo base. Requiere mucha memoria y potencia de cómputo. Solo recomendable si tienes acceso a varios GPUs o TPUs.
    * `longlora`: Variante de LoRA optimizada para contextos largos (Long Context). Útil si estás entrenando modelos para tareas que implican entradas extensas, como documentos largos o código fuente.
    *  `adalora`: Adaptive LoRA. Variante de LoRA que ajusta dinámicamente el rango (rank) durante el entrenamiento. Mejora la eficiencia sin comprometer el rendimiento.
    *  `llamapro`: Técnica optimizada para modelos tipo LLaMA. Incluye ajustes específicos para mejorar rendimiento y compatibilidad.
    *  `adapter`: Técnica clásica de PEFT. Inserta capas adicionales (adapter layers) entre las capas del modelo original. Menos eficiente que LoRA, pero más flexible en algunas arquitecturas.
    *  `vera`: Versatile Adapter (seguramente una técnica nueva o interna del framework). Diseñada para ser compatible con múltiples estructuras de modelo y tareas. Puede mezclar varias estrategias adaptativas.
    *  `boft`: Bias-Only Fine-Tuning. Solo ajusta los biases (sesgos) de las capas del modelo. Extremadamente eficiente pero con menor capacidad de adaptación.
    *  `fourierft`: Técnica experimental basada en transformaciones de Fourier. Busca capturar patrones globales mediante proyecciones de frecuencia. Muy experimental y menos común.
    *  `reft`: Residual-Efficient Fine-Tuning. Basada en añadir pequeños bloques residuales que se entrenan mientras el modelo base permanece congelado. Similar a LoRA, pero puede ofrecer mejoras en ciertas tareas.

* 🔥 adapters: Este argumento permite especificar uno o más adapters que se van a cargar junto con el modelo base. Los adapters son módulos adicionales entrenados por separado (como con LoRA, AdaLoRA, etc.) que pueden ser inyectados en el modelo base sin modificar sus pesos originales, permitiendo reutilizar adaptaciones previas, combinar diferentes adaptaciones para multitarea o transferencia, cargar varios adapters en paralelo (según soporte del backend). Si usas `--train_type lora`, este argumento permite recuperar adaptadores previamente entrenados. Si se deja vacío ([]), el modelo se carga sin ningún adaptador adicional.

* seed: Por defecto: 42. Establece la semilla aleatoria para el entrenamiento y otros procesos aleatorizados (como inicialización de pesos, barajado de datos, etc.).

* model_kwargs: Este argumento permite pasar parámetros específicos del modelo, es decir, configuraciones que solo aplican a ciertos tipos de modelos (por ejemplo, modelos de vídeo, visión, texto largo, etc.). Es una forma flexible de ajustar el comportamiento interno del modelo sin necesidad de modificar el código. Estos parámetros se pasan como un diccionario en formato JSON desde la línea de comandos.

* load_args: Por defecto: True durante inferencia o exportación de modelos. False durante el entrenamiento (para evitar conflictos si estás reconfigurando hiperparámetros). Este argumento controla si se deben cargar automáticamente los argumentos guardados (args.json) desde un checkpoint anterior. Cuando se entrena o se infiere un modelo, ms-swift guarda una copia de todos los argumentos utilizados en un archivo llamado args.json. Este archivo contiene los valores de todos los parámetros pasados por línea de comandos en esa sesión.

* load_data_args: Por defecto: False. Este argumento controla si se deben cargar automáticamente los argumentos relacionados con los datos (como dataset, batch size, num workers, etc.) desde el archivo args.json de un checkpoint previo. Es similar a load_args, pero específicamente enfocado en parámetros de datos.

* use_hf: Por defecto: False → se utiliza ModelScope. Controla si se usa Hugging Face Hub en lugar de ModelScope Hub para descargar modelos y datasets y subir modelos finetuneados al hub.

* ddp_timeout: Establece el timeout para la inicialización de DDP (Distributed Data Parallel). El valor está en segundos, y por defecto es muy alto: 18,000,000 s (aproximadamente 208 días). Es útil para grandes clústeres o entornos con tiempos de arranque lentos (como algunos servidores cloud o entornos HPC).

* ddp_backend: Por defecto: None. Indica el backend de comunicación a usar para entrenamiento distribuido con DDP. Opciones disponibles:
    * `"nccl"` (por defecto en GPUs NVIDIA, muy recomendado)
    * `"gloo"` (para CPUs o debugging)
    * `"mpi"`, `"ccl"`, `"hccl"`, `"cncl"`, `"mccl"` (otros entornos HPC)

## [Model Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#model-arguments)

* 🔥 model: Este es el ID del modelo o la ruta local al modelo base que quieres usar. Puede ser:
    * Un ID de modelo público en ModelScope o Hugging Face.
    * Una ruta local al modelo (por ejemplo, si ya lo descargaste o entrenaste). Si es un modelo personalizado debes usarlo junto con `--model_type` y posiblemente `--template` para indicarle al framework cómo manejarlo correctamente.
    * En nuestro caso ponemos la ruta al modelo BSC-LT/salamandra-2b-instruct alojado en nuestro servidor local.

* 🔥 model_type: Define el tipo de modelo que se está usando. Esto permite que ms-swift: Sepa cómo cargar los pesos y configuraciones. Sepa qué plantilla de entrada/salida usar si es un modelo conversacional. Determine qué clases o lógica usar para fine-tuning, tokenizer, etc.  ¿Es obligatorio?
    * Si `--model` apunta a un modelo conocido por ms-swift, puede inferirse automáticamente (por el config.json y el nombre del modelo).
    * Pero si es un modelo personalizado, debes especificarlo. En nuestro caso debemos indicar 'llama3'.

* 🔥 task_type: Este parámetro define el tipo de tarea de aprendizaje que se va a entrenar o ejecutar con el modelo. Permite a ms-swift preparar correctamente: Los datos de entrada/salida. La arquitectura final (cabezas de salida, etc.). Las métricas de evaluación. El proceso de inferencia o fine-tuning. Valores posibles:
    * causal_lm: (Por defecto) Language modeling causal: generación de texto autoregresiva (p.ej., ChatGLM, LLaMA, Qwen, etc.).
    * seq_cls: Clasificación de secuencias: tareas como análisis de sentimientos, detección de temas, etc.
    * embedding: Generación de embeddings: tareas donde se desea obtener representaciones vectoriales del texto. Por ejemplo, para búsqueda semántica o clustering.

* 🔥 torch_dtype: Este argumento define el tipo de dato (data type) que se utilizará para los pesos del modelo cuando se cargan en PyTorch. Afecta directamente a: el uso de memoria (RAM y GPU), la velocidad de entrenamiento/inferencia y la compatibilidad con hardware (como GPUs que soporten bfloat16). Valor por defecto: Se leerá automáticamente desde el archivo config.json del modelo (campo "torch_dtype"). Valores soportados:
    * `float16`.
    * `bfloat16`.
    * `float32`.

* device_map: Este argumento controla cómo se distribuyen los componentes del modelo (como capas o bloques) entre distintos dispositivos, como GPU, CPU o múltiples GPUs. Permite una asignación automática o personalizada de los pesos del modelo a los dispositivos disponibles. Si no se especifica, ms-swift elegirá la asignación automáticamente según si estás usando entrenamiento distribuido (DDP) o qué hardware tienes disponible. Valores posibles:
    * `'auto'`: Asignación automática según la memoria disponible y el número de GPUs o CPUs.
    * `'cpu'`: Carga todo el modelo en CPU. Útil si no tienes GPU o si solo estás exportando/convirtiendo.
    * JSON string: Puedes definir manualmente a qué dispositivo va cada parte del modelo, con un JSON en línea.
    * Ruta a archivo JSON: Puedes pasar la ruta de un .json con el mapeo personalizado de capas a dispositivos.

## [Data Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#data-arguments)

* 🔥 dataset: Es el argumento que usas para especificar de dónde vendrán los datos de entrenamiento o evaluación. Puedes usar uno o varios datasets. Componentes del formato:
    1.  Dataset ID o Ruta (obligatorio): 
        * Un ID de un dataset conocido (ej. "glue", "yelp_polarity"). 
        * Un path local a un dataset (ej. "./data/mi_dataset.jsonl").
        * Una carpeta con subdatasets o múltiples archivos.
    2. Sub-dataset (opcional):
        * Solo aplica si el dataset tiene subconjuntos predefinidos (por ejemplo, "train", "validation"). Se especifica con `':'` después del dataset.
        * Si no se especifica se usa el subdataset registrado por defecto o "default" si no hay uno específico.
    3. Sampling size (opcional): Indica cuántas muestras quieres usar de ese dataset (útil para debug o entrenamiento parcial). Se pone con `#` después del subdataset.
    * Nosotros usamos un dataset personalizado, por lo que primero debemos asegurarnos de tenerlos en un formato disponible. 

* 🔥 val_dataset: Por defecto: []. Este argumento permite especificar uno o varios conjuntos de validación que se usarán durante el entrenamiento. Mismo formato que 'dataset'.

* 🔥 split_dataset_ratio: Este parámetro define el porcentaje del conjunto de entrenamiento (`--dataset`) que se usará como conjunto de validación, si no has especificado explícitamente `--val_dataset`. Por defecto: 0.01.

* data_seed: Por defecto: 42. Es la semilla aleatoria que se utiliza para todas las operaciones de aleatorizaSción relacionadas con los datos.

* 🔥 dataset_num_proc: Por defecto: 1. controla el número de procesos paralelos que se utilizarán para preprocesar el dataset antes de entrenar el modelo. Este procesamiento incluye tareas como: Tokenización, transformaciones de texto, conversión a tensores, aplicación de plantillas de conversación, etc.
    *  Generalmente, puedes usar un valor igual al número de núcleos de CPU disponibles (o un poco menos para evitar saturar el sistema).

* 🔥 load_from_cache_file: Por defecto: True. Este parámetro controla si el dataset debe cargarse desde archivos de caché previamente procesados en lugar de volver a preprocesarlo desde cero. Cuando se preprocesa un dataset (por ejemplo, aplicando tokenización, plantillas, etc.), Megatron-SWIFT guarda una copia cacheada en disco. Si más adelante vuelves a entrenar con el mismo dataset y parámetros, el sistema puede cargar directamente esa caché para ahorrar tiempo.
    * ¿Cuándo ponerlo en False? Durante la fase de pruebas (debug), para asegurarte de que estás viendo el efecto de cambios recientes (como nuevas plantillas o transformaciones) o si modificas el código de procesamiento (por ejemplo, la plantilla de conversación o la tokenización).

* dataset_shuffle: Por defecto: True. Este parámetro indica si el dataset debe ser mezclado aleatoriamente antes de ser pasado al dataloader durante el entrenamiento. Existen dos niveles de barajado: dataset_shuffle (baraja los datos antes de crear el dataloader, esto afecta directamente el orden base del dataset) y train_dataloader_shuffle (Baraja los datos en cada época dentro del dataloader,esto es más común en PyTorch y otras libs de deep learning).

* 🔥streaming: Por defecto: False. Este parámetro activa el modo de lectura por streaming del dataset, en lugar de cargar todo el dataset en memoria.
    * Cuando `--streaming` está activado, el dataset no tiene una longitud predefinida. Por ello, es obligatorio definir explícitamente el número de pasos de entrenamiento mediante `--max_steps`, o bien controlar el entrenamiento por épocas con `--max_epochs`. Si usas `--max_steps`, define también una estrategia de guardado como `--save_strategy` epoch para validar y guardar el modelo periódicamente. Alternativamente, puedes controlar la duración del entrenamiento con `--max_epochs`, lo cual asegura que el entrenamiento se detenga después del número deseado de épocas. 

* shuffle_buffer_size: Este parámetro controla el tamaño del buffer usado para mezclar aleatoriamente los datos cuando se trabaja con datasets en modo streaming (`--streaming True`). Funciona como una ventana deslizante: se cargan N ejemplos en memoria (donde N es el valor de este parámetro) y se barajan antes de devolverlos al dataloader. Valor por defecto: 1000.

* columns: Por defecto: None. Este parámetro permite mapear los nombres de las columnas del dataset a los nombres esperados por el preprocesador automático (AutoPreprocessor) de ms-swift. Es útil cuando estás utilizando datasets personalizados o con nombres de columnas distintos a los estándares. Ejemplo: `'{"text1": "query", "text2": "response"}'`
    * 🔗 Más información sobre datasets personalizados: [Custom Dataset en ms-swift](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Customization/Custom-dataset.md)

* custom_dataset_info: Por defecto: []. Este parámetro se utiliza para registrar datasets personalizados en ms-swift, proporcionando un archivo .json con la información necesaria para definir su estructura, tareas, formatos y divisiones. 

## [Template Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#template-arguments)

* 🔥template: Este parámetro define el tipo de plantilla de diálogo que se utilizará para estructurar las entradas y salidas del modelo durante el preprocesamiento.
    * Es obligatorio cuando se usa un modelo personalizado o un modelo cuyo tipo no es detectado automáticamente. Si no se especifica, se intenta inferir automáticamente a partir del modelo usado.

* 🔥system: Este parámetro permite establecer un mensaje del sistema personalizado (también llamado system prompt), que define el comportamiento general del modelo conversacional. Formatos aceptados: a) Un string con el contenido del mensaje del sistema. b) Una ruta a un archivo .txt que contenga el mensaje. Prioridad de aplicación:
    1. El mensaje definido dentro del dataset (si existe) tiene la prioridad más alta.
    2. Luego se aplica el valor de `--system`, si se ha definido manualmente.
    3. (Por defecto) Si ninguno de los anteriores está disponible, se utiliza el default_system de la plantilla (template) correspondiente.

* 🔥max_length: Este parámetro define la longitud máxima (en tokens) permitida para una única muestra de entrada (por ejemplo, un mensaje o conversación). Es útil para controlar el tamaño del contexto que recibe el modelo. Si no se especifica, se establece automáticamente al valor máximo permitido por el modelo (`max_model_len`, definido en su configuración interna).

* truncation_strategy: Define cómo se gestionan las muestras individuales que superan el límite de tokens establecido por max_length. Es decir, si una entrada tiene más tokens de los permitidos, esta estrategia determina qué parte se elimina. Opciones disponibles:
    * `'delete'` (por defecto): Si la muestra excede max_length, se descarta por completo y no se usa en el entrenamiento o inferencia.
    * `'left'`: Se eliminan tokens desde el inicio de la secuencia hasta ajustarse a max_length. Se conserva el final del texto.
    * `'right'`: Se eliminan tokens desde el final de la secuencia. Se conserva el inicio del texto. --> La que usamos nosotros

* use_chat_template: Este parámetro controla si se utiliza una plantilla de conversación tipo chat (chat template) o una plantilla de generación general (generation template) durante el preprocesamiento de datos y la generación de texto. Valores posibles:
    * `True` (por defecto): Se utiliza la plantilla de chat, diseñada para modelos conversacionales tipo chatbot. Estas plantillas estructuran el texto en formato pregunta-respuesta con roles como usuario y asistente.
    * `False`: Se usa una plantilla de generación general, pensada para tareas de texto genérico, como completar un texto o generar contenido a partir de un prompt libre. Cuando se usa Swift para entrenamiento (Swift PT), este parámetro se establece automáticamente en False para emplear la plantilla de generación, ya que es más adecuada para los fines de preentrenamiento.

* 🔥padding_free: Por defecto: False. Elimina el uso de relleno (padding) dentro de un batch durante el entrenamiento, lo que permite: reducir el uso de memoria y acelerar el entrenamiento.

* padding_side: Especifica de qué lado se aplicará el padding (relleno de secuencias) cuando se entrena con batch_size >= 2. Opciones válidas: `'left'` o `'right'`.

* loss_scale: Controla cómo se pondera la pérdida (*loss*) durante el entrenamiento con cross-entropy, especialmente cuando se usan modelos de agentes o plantillas con múltiples turnos de conversación. Algunos valores posibles:
    * `default`: Todas las respuestas (incluyendo historial) se usan con peso 1. Se ignora la pérdida de tool_response.
    * `last_round`: Solo se calcula la pérdida de la última ronda de respuesta del modelo (útil si solo te interesa que el modelo aprenda de la última interacción, lo cual es común en entrenamiento supervisado con ejemplos conversacionales).
    * `all`: Se calcula la pérdida para todos los tokens del conjunto.

* sequence_parallel_size: Define el número de particiones paralelas para aplicar paralelismo de secuencia durante el entrenamiento. Este tipo de paralelismo divide la secuencia de entrada entre varios procesos para acelerar el entrenamiento o reducir el uso de memoria. Valor por defecto: 1. [Script de ejemplo](https://github.com/modelscope/ms-swift/blob/main/examples/train/long_text/ulysses/sequence_parallel.sh).

## [Generation Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#generation-arguments)

* 🔥max_new_tokens: Número máximo de tokens nuevos que el modelo puede generar. Si es None, no hay límite.
* temperature
* top_k
* top_p
* repetition_penalty: Penaliza que se repitan tokens en la salida.
* num_beams: Por defecto: 1
* 🔥stream.
* stop_words: 
* logprobs: Por defecto: False. Si se activa, devuelve las probabilidades logarítmicas de los tokens generados.
* top_logprobs: Por defecto: None. Cuántos tokens mostrar con sus logprobs.

## [Seq2SeqTrainer Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#seq2seqtrainer-arguments)

* 🔥output_dir: Ruta donde se guardarán los checkpoints del modelo, logs, evaluaciones, y configuraciones del experimento.

* 🔥gradient_checkpointing: Por defecto: True. Técnica para reducir el uso de memoria RAM/GPU durante el entrenamiento, a costa de un pequeño aumento en el tiempo de cómputo. Al activarlo, se evitan almacenar algunas activaciones intermedias, y se recalculan en el backward pass.

* 🔥deepspeed: activa entrenamiento distribuido eficiente usando DeepSpeed, una librería de Microsoft diseñada para entrenar modelos grandes con menos consumo de memoria y mejor rendimiento. Valores posibles:
    * `'zero0'`: DeepSpeed básico.
    * `'zero1'`: Optimización de memoria en los optimizadores.
    * `'zero2'`: Optimización de optimizadores y gradients.
    * `'zero3'`: Máxima eficiencia; distribuye parámetros, gradients y optimizadores entre GPUs.
    * `'zero2_offload'` y `'zero3_offload'`: Igual que zero2/zero3, pero con offloading a CPU o disco para reducir uso de GPU RAM.
    * Valor por defecto: None. No se usa DeepSpeed.

* 🔥 per_device_train_batch_size: Establece el tamaño de batch por dispositivo (GPU) durante el entrenamiento. Valor por defecto: 1.

* 🔥 per_device_eval_batch_size: Igual que el anterior, pero para la fase de evaluación/validación. Valor por defecto: 1.

* 🔥 gradient_accumulation_steps: Permite acumular gradientes durante varios pasos antes de hacer una actualización del modelo, lo que simula un batch mayor sin necesidad de más memoria. Valor por defecto: None.

* weight_decay: Es un término de regularización que evita que los pesos crezcan demasiado (previene el overfitting). Funciona penalizando grandes valores de los pesos en la función de pérdida. Valor por defecto: 0.1.

* adam_beta2: Es el parámetro β₂ del optimizador Adam, que controla el promedio de los cuadrados de los gradientes pasados. Valor por defecto: 0.95.

* 🔥 learning_rate: Controla la velocidad con la que el modelo aprende. Valor por defecto:
    * `1e-5` si haces full fine-tuning del modelo (ajustas todos los pesos).
    * `1e-4` si usas LoRA u otro método de adaptación eficiente.

* lr_scheduler_type: Controla cómo varía la tasa de aprendizaje (learning rate) a lo largo del entrenamiento. Opciones posibles:
    * `'linear'`: Empieza con learning_rate y lo reduce linealmente hasta 0.
    * `'cosine'` (por defecto): Hace una reducción en forma de coseno → baja rápido al principio y más lentamente al final.
    * `'constant'`, `'polynomial'`, `'constant_with_warmup'`, etc.

* 🔥 gradient_checkpointing_kwargs: Permite pasar argumentos específicos a torch.utils.checkpoint, que se usa cuando tienes activado gradient_checkpointing. Si usas DDP (DistributedDataParallel) sin DeepSpeed o FSDP, y no defines este parámetro, se aplica por defecto: `{"use_reentrant": false}`

* 🔥 report_to: Define a qué herramienta de monitorización enviar los logs de entrenamiento (loss, learning rate, métricas...). Valores posibles:
    * `'tensorboard'` (por defecto) → crea archivos .tfevents que puedes visualizar con [TensorBoard](https://www.tensorflow.org/tensorboard?hl=es-419).
    * `'wandb'` → registra los experimentos en [Weights & Biases](https://wandb.ai/site/).
    * `'swanlab'` → una alternativa a wandb.
    * `'all'` → reporta a todas las herramientas anteriores que estén activadas.

* logging_steps: Define cada cuántos pasos de entrenamiento se deben registrar métricas como loss, learning_rate, etc. Valor por defecto: 5.

* 🔥 max_epochs: Fuerza que el entrenamiento termine después de haber completado el número de épocas indicado, haciendo validación y guardando los pesos. Muy importante cuando usas datasets en streaming, que no tienen longitud fija, y no puedes basar el entrenamiento en num_train_epochs tradicional. Valor por defecto: None.

* 🔥 num_train_epochs: Número total de épocas (vueltas completas) para entrenar el modelo. Por defecto: 3

* 🔥 save_strategy: Estrategia para guardar el modelo durante el entrenamiento. Opciones:
    * `'no'`: No guarda checkpoints durante el entrenamiento.
    * `'steps'` (por defecto): Guarda checkpoints cada cierta cantidad de pasos (batches).
    * `'epoch'`: Guarda checkpoints al final de cada época.

* 🔥 save_steps: Número de pasos entre cada guardado del checkpoint, usado si `save_strategy` es `'steps'`. Por defecto: 500.

* 🔥 eval_strategy: Estrategia para realizar evaluaciones durante el entrenamiento. Por defecto sigue la misma estrategia que `save_strategy`.

* 🔥 eval_steps: Número de pasos entre cada evaluación, usado si `eval_strategy` es `'steps'`.

* 🔥 save_total_limit: Límite máximo de checkpoints guardados. Por defecto es None, lo que significa que se guardan todos los checkpoints sin límite.

* max_steps: Número máximo total de pasos de entrenamiento. Muy importante cuando usas datasets en streaming (sin tamaño fijo), porque el número de pasos define cuándo parar el entrenamiento. Por defecto es -1, lo que significa que no hay límite y se usa num_train_epochs para controlar duración.

* 🔥 warmup_ratio: Proporción del total de pasos que se usan para el calentamiento (warmup) del aprendizaje. Durante warmup, la tasa de aprendizaje aumenta gradualmente desde 0 hasta el valor definido. Por defecto es 0.
* 🔥 warmup_steps: Número de pasos que se usan para el calentamiento del aprendizaje. Por defecto 0.
* 🔥 resume_from_checkpoint: Por defecto es None. Permite reanudar el entrenamiento desde un checkpoint guardado previamente. Debes pasar la ruta (path) del checkpoint para continuar. Al usarlo, carga pesos del modelo, estado del optimizador y semilla, y sigue desde el último paso entrenado.

* 🔥dataloader_num_workers: Número de procesos paralelos que usará cada DataLoader para cargar los datos en memoria mientras entrenas. Valores posibles:
    * `0`: carga los datos en el proceso principal (más lento, pero más estable en Windows).
    * `>0`: usa varios subprocesos para acelerar la carga de datos (más rápido en Linux/macOS).
    * `None`: usa un valor por defecto que depende del sistema operativo (0 en windows y 1 en linux/macOS).

* 🔥 ddp_find_unused_parameters: Este parámetro se utiliza cuando entrenas en modo Distributed Data Parallel (DDP) de PyTorch. Indica si el motor DDP debe buscar parámetros que no se usaron en el forward pass. Valores posibles:
    * `True`: habilita la detección de parámetros no utilizados.
    * `False`: desactiva la detección. Más eficiente, pero puede lanzar errores si realmente hay parámetros sin usar.
    * `None`: la librería decide automáticamente si lo activa o no según el modelo y configuración.

* 🔥 neftune_noise_alpha: Es un coeficiente que controla la cantidad de ruido añadido por la técnica neftune durante el entrenamiento. El ruido puede ayudar a mejorar la generalización y evitar sobreajuste. Valor por defecto: 0 (sin ruido). Se suele usar valores como 5, 10 o 15 para añadir ruido progresivamente.

* 🔥use_liger_kernel: Por defento: False. Se refiere a una optimización de bajo nivel para acelerar el entrenamiento y reducir el uso de memoria en GPU mediante el uso de un "kernel" específico llamado Liger. [Ejemplo](https://github.com/modelscope/ms-swift/blob/main/examples/train/liger/sft.sh)




## [Tuner Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#tuner-arguments)

* 🔥 target_modules: Indica qué módulos (capas) del modelo serán tunados con LoRA (o cualquier otro tuner). Por defecto: ['all-linear'] → busca todas las capas lineales excepto la cabeza de salida (lm_head) para añadir LoRA.

* 🔥 target_regex: En vez de target_modules, puedes usar una expresión regular para seleccionar módulos a tunar. Si usas esto, target_modules se ignora.

## [LoRA](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#lora)

* 🔥 lora_rank: Defecto: 8. Es el rango de las matrices de baja dimensión que LoRA añade para adaptar el modelo.
* 🔥 lora_alpha: Defecto: 32. Es un factor de escala para las matrices LoRA, controla la intensidad del ajuste.
* lora_dropout: Defecto: 0.05. Tasa de dropout aplicada a las matrices LoRA durante el entrenamiento, para evitar sobreajuste.
* lora_bias: Controla si las biases (sesgos) del modelo son entrenables con LoRA. Opciones:
    * `'none'` (por defecto): No entrenar biases.
    * `'all'`: Entrenar todas las biases.
* lora_dtype: Tipo de dato usado para las matrices LoRA. Opciones: `'float16'`, `'bfloat16'`, `'float32'`. Por defecto sigue el tipo de dato original del modelo.

## [vLLM](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#vllm-arguments)

* 🔥 gpu_memory_utilization: Indica el porcentaje de memoria GPU que quieres reservar para vLLM durante la ejecución. Rango: 0 (0%) a 1 (100%). Por defecto: 0.9 (90% de la memoria GPU).
* 🔥 tensor_parallel_size: Tamaño del paralelismo tensorial, es decir, cuántos dispositivos/tensores se usan para dividir el modelo y acelerar inferencia. Por defecto: 1 (sin paralelismo tensorial).

## [Training Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#training-arguments)

* check_model: Establecer a `False` en entorno offline. 
* loss_type: Define qué función de pérdida se utiliza durante el entrenamiento. Por defecto: None.
* 🔥 packing: Sirve para activar el empaquetado de secuencias (sequence packing) durante el entrenamiento de modelos de lenguaje. Este mecanismo permite que varias secuencias cortas se agrupen en un solo ejemplo de entrada para aprovechar mejor la capacidad del modelo y reducir el padding innecesario, lo que aumenta la eficiencia computacional.

## [Inference Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#inference-arguments)
* 🔥infer_backend: Determina el motor que se usará para ejecutar la inferencia. Opciones:
    * `'pt'` (por defecto): PyTorch (compatible con casi todos los modelos).
    * `'vllm'`: Usa vLLM para inferencia más rápida y eficiente.
    * `'sglang'`: Backend para ejecución con SGLang, diseñado para servir modelos como chatbots.
    * `'lmdeploy'`: Para usar con el stack de LMDeploy, centrado en producción.
* 🔥max_batch_size: Define cuántas entradas se procesan por lote durante la inferencia. Solo aplica si `infer_backend` = pt.
    * `1` : una entrada a la vez (lo habitual en chatbots).
    * `>1` : útil si haces inferencia en paralelo (por ejemplo, validación o evaluación).
    * `-1` : sin límite.
* 🔥result_path: Ruta donde se almacenan los resultados de inferencia (.jsonl). Si no se especifica, se guarda en el directorio del checkpoint (si existe) o en `./result`

## [Evaluation Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#evaluation-arguments)
* 🔥eval_backend: Define el backend o sistema encargado de realizar la evaluación automática del modelo. Opciones:
    * `'Native'` (por defecto): Usa el sistema interno de evaluación de ModelScope.
    * `'OpenCompass'`: Para evaluaciones más completas y benchmark multitarea.
    * `'VLMEvalKit'`: Específico para modelos multimodales (visión + lenguaje).
* 🔥eval_dataset: Especifica el dataset que se usará para evaluar tu modelo. Puede ser un conjunto predefinido en ModelScope o uno propio (en formato compatible).

## [Export Arguments](https://github.com/modelscope/ms-swift/blob/main/docs/source_en/Instruction/Command-line-parameters.md#export-arguments)

* 🔥 output_dir: Carpeta donde se guardan los resultados exportados (modelos, pesos, configuraciones). 
* 🔥 quant_method: Método de cuantización para reducir el tamaño del modelo y acelerar inferencia. Opciones: `'gptq'`, `'awq'`, `'bnb'`, `'fp8'`. Por defecto: None. [Ejemplos de uso](https://github.com/modelscope/ms-swift/tree/main/examples/export/quantize)
* max_length: Longitud máxima para las muestras usadas en calibración durante la cuantización. Por defecto: 2048.


