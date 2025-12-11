## Documentación

### Descripción general
Este sistema automatiza la limpieza y preparación de grandes volúmenes de texto en español, eliminando contenido duplicado y de baja calidad. Es una herramienta diseñada para investigadores, científicos de datos y equipos que necesitan preparar corpus textuales para entrenar modelos de lenguaje o realizar análisis lingüísticos a gran escala

### Pasos del procesamiento

- **Paso 1: Carga de configuración y rutas**
  - Carga un archivo de configuración YAML con parámetros (umbral de idioma, filtros, etc.).
  - Definición de rutas de trabajo
  - Preparación del entorno de procesamiento

- **Paso 2: Filtrado por idioma**
  - Análisis automático del idioma de cada documento
  - Selección de textos en español según umbral de confianza

- **Paso 3: Deduplicado con MinHash**
  - Detección avanzada de contenido repetido o altamente similar
  - Utiliza algoritmos de comparación escalables para grandes volúmenes

- **Paso 4: Filtros de calidad y limpieza final**
  - Aplicación de múltiples filtros especializados
  - Corrección de errores de codificación
  - Eliminación de información sensible o identificable

### Limpieza de datos aplicada

- Filtrado inicial por idioma para asegurar solo texto en español.
- Detección y eliminación de duplicados usando MinHash, minimizando repeticiones exactas o muy similares.
- Filtros para remover textos con repeticiones internas, baja calidad web, o características no deseadas (p.ej., exceso de símbolos, palabras no alfabéticas).
- Formateo final que incluye corrección de formato (FTFY), anonimización de datos sensibles (PIIFormatter) y eliminación de líneas con símbolos específicos.

Los documentos descartados se guardan con trazabilidad.

### Bibliotecas y módulos clave usados
- `yaml`: para cargar configuraciones.
- `datatrove.executor.local.LocalPipelineExecutor`: para ejecutar pipelines de procesamiento en paralelo.
- `datatrove.pipeline.readers.JsonlReader` y `writers.JsonlWriter`: para manejo de archivos JSONL.
- Filtros específicos de calidad y deduplicado (ej. `LanguageFilter, MinhashDedupSignature, GopherQualityFilter`).
- Formateadores para limpieza y anonimización (`FTFYFormatter`, `PIIFormatter`, `SymbolLinesFormatter`).

# En detalle

## Paso 1: Filtrado por idioma

El primer paso selecciona únicamente textos en español:

- **LanguageFilter:** Usa puntuación de detección de idioma (`language_score`) para seleccionar documentos en español (“es”), ignorando los que no llegan al umbral.

El parámetro **language_score** ajusta la sensibilidad: valores bajos permiten más documentos dudosos, valores altos son más estrictos.

***

## Paso 2: Deduplicación avanzada con MinHash

La deduplicación masiva utiliza el algoritmo **MinHash**, que detecta textos similares de manera escalable:

### ¿Qué hace MinHash?

- **Divide el texto en n-gramas:** Fragmenta cada documento en piezas de tamaño definido, permitiendo comparar similitud entre textos, incluso con pequeñas diferencias.
- **Hash de n-gramas:** Cada n-grama es convertido a un valor numérico con una función hash eficiente (`xxhash`). La precisión de estos hashes se puede controlar.
- **Firma MinHash:** Selecciona un subconjunto de hashes, formando una “firma” que caracteriza el documento sin guardar todo el contenido.
- **Agrupamiento en buckets:** Asigna firmas parecidas a los mismos buckets, facilitando la comparación y agrupación por similitud.
- **Clusterización:** Agrupa documentos que son similares en muchos buckets, identificando duplicados, incluso si tienen pequeños cambios.
- **Filtrado final:** Elimina documentos duplicados, dejando solo un ejemplo único de cada conjunto similar.

#### Implementación paso a paso

1. **Firma MinHash:** Calcula y guarda la firma para cada documento.
2. **Buckets:** Agrupa firmas con hashes similares.
3. **Cluster:** Detecta y agrupa documentos duplicados.
4. **Filtro final:** Elimina textos duplicados del corpus, utilizando los IDs identificados.

Este enfoque resulta escalable y robusto frente a pequeñas variaciones en los textos, permitiendo limpiar corpus de millones de documentos de forma eficiente.

***

## Paso 3: Filtros de calidad y limpieza final

Después de deduplicar, el corpus pasa por una serie de filtros para garantizar que solo se mantengan textos de alta calidad:

### GopherRepetitionFilter

Este filtro está diseñado para detectar y eliminar documentos con **repeticiones excesivas** que suelen indicar spam, contenido de baja calidad o textos poco naturales.

- **dup_line_frac:** Establece la fracción máxima permitida de líneas exactamente repetidas dentro de un texto. Por ejemplo, un valor de 0.35 permite hasta un 35% de líneas repetidas, sobrepasar ese ratio implica rechazo.
- **top_n_grams:** Evalúa la frecuencia de los n-gramas más comunes. El filtro observa la proporción máxima permitida para estos n-gramas más frecuentes (ejemplo: si un trigrama aparece en más del 60% del texto, podría ser indicativo de contenido repetitivo que no aporta valor).
- **dup_n_grams:** Complementa este chequeo detectando duplicaciones directas de n-gramas en el texto con un umbral ajustado para cada tamaño (ejemplo: 75% para trigrams, 55% para pentagrams). Si se detectan demasiados n-gramas repetidos, el texto se elimina.

Este filtro protege el corpus frente a textos que podrían inflar artificialmente la cantidad de datos sin aportar diversidad, manteniendo la calidad y variedad de frases y contenido.

### FineWebQualityFilter

Evalúa calidad textual a nivel de caracteres y líneas, con criterios muy específicos para evitar texto defectuoso o ruido que pueda afectar modelos o análisis posteriores:

- **char_duplicates_ratio:** Este parámetro mide la proporción de caracteres consecutivos repetidos en el texto (ejemplo: secuencias largas de letras idénticas como “aaaaaa” o símbolos). Si esta proporción excede un umbral, se considera que el texto tiene mala calidad debido a patrones repetitivos no naturales, descartándolo automáticamente.
  
- **line_punct_thr:** Esta métrica evalúa la proporción de líneas que contienen una cantidad excesiva de signos de puntuación, como demasiados símbolos de interrogación, exclamación, comas, puntos suspensivos, etc. Si la cantidad de líneas con alta puntuación supera el umbral (por ejemplo 0.6 o 60%), se descarta el documento considerando que puede ser una página de mala calidad, código mal copiado, o spam contextual.
  
- **new_line_ratio:** Este filtro observa la densidad de saltos de línea en comparación con la cantidad de tokens en el texto. Textos con muchas líneas nuevas en proporción a la longitud total suelen ser tablas, listados o datos semiestructurados.

En conjunto, **FineWebQualityFilter** ayuda a eliminar documentos con características típicas de contenido pobre, desordenado o estructurado incorrectamente, asegurando que el corpus tenga una calidad lingüística y estructural alta para su consumo posterior.


### GopherQualityFilter

Este filtro se centra en asegurar que el contenido tenga características lingüísticas naturales propias del idioma español y descarte textos dañinos o basura:

- **max_avg_word_length / min_avg_word_length:** Elimina textos con palabras demasiado largas (como cadenas codificadas, URLs, código) o demasiado cortas (como spam de caracteres repetidos).
- **max_non_alpha_words_ratio:** Permite controlar la fracción máxima de palabras no alfabéticas (números, símbolos) en un texto. Por encima del umbral, se considera ruido o contenido inválido.
- **stopwords:** Requiere que el texto contenga un número mínimo de palabras vacías típicas del español para asegurar naturalidad y evitar textos artificiales o generan ruido.

### Limpieza y formateo final

Se aplican formateadores automáticos para pulir detalles:

- **FTFYFormatter:** Corrige errores comunes de codificación y caracteres malformados.
- **PIIFormatter:** Detecta y elimina posibles datos personales identificables (PII).
- **SymbolLinesFormatter:** Elimina líneas compuestas solo por símbolos especificados, eliminado ruido.
- Finalmente, el corpus limpio se guarda.

***

## Configuración YAML

Personaliza el comportamiento del pipeline con los siguientes parámetros:

```yaml
## === Language Filter ===
language_score: 0.35  

## === GopherRepetitionFilter ===
dup_line_frac: 0.35  
top_n_grams:     
  - [3, 0.6]       
  - [4, 0.55]
  - [5, 0.4]
dup_n_grams:       
  - [3, 0.75]
  - [4, 0.65]
  - [5, 0.55]

## === FineWebQualityFilter ===
char_duplicates_ratio: 0.35  
line_punct_thr: 0.15 
new_line_ratio: 1   

## === GopherQualityFilter ===
max_avg_word_length: 16
min_avg_word_length: 2 
max_non_alpha_words_ratio: 0.3

stopwords:
  - alguna
  - algunas
  - alguno
  - algunos
  - ambos
  - ampleamos
  - ante
  - antes
  - aquel
  - aquellas
  - aquellos
  - aqui
  - arriba
  - atras
  - bajo
  - bastante
  - bien
  - cada
  - cierta
  - ciertas
  - cierto
  - ciertos
  - como
  - con
  - conseguimos
  - conseguir
  - consigo
  - consigue
  - consiguen
  - consigues
  - cual
  - cuando
  - dentro
  - desde
  - donde
  - dos
  - el
  - ellas
  - ellos
  - empleais
  - emplean
  - emplear
  - empleas
  - empleo
  - en
  - encima
  - entonces
  - entre
  - era
  - eramos
  - eran
  - eras
  - eres
  - es
  - esta
  - estaba
  - estado
  - estais
  - estamos
  - estan
  - estoy
  - fin
  - fue
  - fueron
  - fui
  - fuimos
  - gueno
  - ha
  - hace
  - haceis
  - hacemos
  - hacen
  - hacer
  - haces
  - hago
  - incluso
  - intenta
  - intentais
  - intentamos
  - intentan
  - intentar
  - intentas
  - intento
  - ir
  - la
  - largo
  - las
  - lo
  - los
  - mientras
  - mio
  - modo
  - muchos
  - muy
  - nos
  - nosotros
  - otro
  - para
  - pero
  - podeis
  - podemos
  - poder
  - podria
  - podriais
  - podriamos
  - podrian
  - podrias
  - por
  - por qué
  - porque
  - primero
  - puede
  - pueden
  - puedo
  - quien
  - sabe
  - sabeis
  - sabemos
  - saben
  - saber
  - sabes
  - ser
  - si
  - siendo
  - sin
  - sobre
  - sois
  - solamente
  - solo
  - somos
  - soy
  - su
  - sus
  - también
  - teneis
  - tenemos
  - tener
  - tengo
  - tiempo
  - tiene
  - tienen
  - todo
  - trabaja
  - trabajais
  - trabajamos
  - trabajan
  - trabajar
  - trabajas
  - trabajo
  - tras
  - tuyo
  - ultimo
  - un
  - una
  - unas
  - uno
  - unos
  - usa
  - usais
  - usamos
  - usan
  - usar
  - usas
  - uso
  - va
  - vais
  - valor
  - vamos
  - van
  - vaya
  - verdad
  - verdadera
  - verdadero
  - vosotras
  - vosotros
  - voy
  - yo
```