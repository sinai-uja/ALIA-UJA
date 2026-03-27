# Metodología Magpie

Esta es la documentación referente al apartado de generación de datos sintéticos para LLM. Los datos sintéticos generados son pares pregunta-respuesta que se usarán para entrenar el modelo LLM. La estrategia que se ha seguido para la creación de los datos ha sido el enfoque Magpie.

El script llama a un endpoint de OpenAI compatible donde se usa el modelo “Phi4” que genera:

- Preguntas generales (¿Qué?, ¿Cuándo?, ¿Cómo?, ¿Por qué?...).
- Instrucciones generales (Indica, Explica, Analiza, Resume ...).
- Preguntas basadas en un contexto dado. (Por ejemplo, un documento del BOE)
- Instrucciones basadas en un contexto.
- Preguntas tipo test de opcion múltiple (A,B,C,D) generales (con/sin justificación). 
- Preguntas tipo test de opcion múltiple (A,B,C,D) basada en un contexto (con/sin justificación). 
- Preguntas verdadero o falso generales(con/sin justificación).
- Preguntas verdadero o falso basadas en un contexto (con/sin justificación).

Dichas generaciones que requieren de un contexto, será el usuario el que porporcionará un archivo _.jsonl_ con los contextos que desea generar datos sintéticos. 


*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Metodología Magpie](#metodología-magpie)
  - [Configuración](#configuración)
  - [Uso](#uso)
  - [Metodología empleada](#metodología-empleada)
    - [Adaptación al dominio legal](#adaptación-al-dominio-legal)
  - [Explicación de la lógica](#explicación-de-la-lógica)
  - [Formato de salida](#formato-de-salida)
  - [Proceso de limpieza y depuración de datos](#proceso-de-limpieza-y-depuración-de-datos)
    - [1. Generación inicial con Llama-3.1-8B-Instruct](#1-generación-inicial-con-llama-31-8b-instruct)
      - [Problemas detectados con Llama](#problemas-detectados-con-llama)
    - [2. Limpieza inicial (duplicados y respuestas no válidas)](#2-limpieza-inicial-duplicados-y-respuestas-no-válidas)
    - [3. Reconstrucción del dataset con Phi-4](#3-reconstrucción-del-dataset-con-phi-4)
    - [4. Filtro por similitud semántica](#4-filtro-por-similitud-semántica)
    - [5. Impacto en el conjunto de datos](#5-impacto-en-el-conjunto-de-datos)
  - [Información general dataset generado](#información-general-dataset-generado)



## Configuración
El archivo de configuración (“config.yaml”) que usa el script tiene que tener la siguiente estructura:

```
OUTPUT_DIR: Directorio donde se van a guardar los archivos sintéticos que se generarán

MODEL_PATH: Ruta donde está alojado el modelo


PROMPT_INSTRUCTION: Prompt para el system, el cual generará instrucciones
PROMPT_QUESTION: Prompt para el system, el cual generará preguntas

PROMPT_CONTEXT_INSTRUCTION: Prompt para el system, el cual generará instrucciones a partir de un contexto dado.
PROMPT_CONTEXT_QUESTION: Prompt para el system, el cual generará preguntas a partir de un contexto dado.

PROMPT_TEST_OPTION_1: Prompt que generará instrucciones/preguntas para la opción 1 de test.
PROMPT_TEST_OPTION_2:Prompt que generará instrucciones/preguntas para la opción 2 de test.
PROMPT_TEST_OPTION_3:Prompt que generará instrucciones/preguntas para la opción 3 de test.
PROMPT_TEST_OPTION_4:Prompt que generará instrucciones/preguntas para la opción 4 de test.


BATCH_SIZE: Tamaño del batch con el que se harán las llamadas al modelo.

NUM_DOCUMENTS: Numero de tuplas máximo que se quiere generar

MODEL: Modelo que se usará para la generación de los datos, pueden ser: "meta-llama/Llama-3.1-8B-Instruct" o "microsoft/phi-4"
```

## Uso
Como se ha comentado, para ejecutar el script hay varias modalidades, empezando con la creación de preguntas/instrucciones generales:

- **Instrucciones**
El script se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --I_

- **Preguntas**
El script se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --Q_

Para las modalidades de contexto, el script requiere el parámetro adicional --ruta donde se le pasará la ruta del archivo .jsonl con los contextos de los cuales se haran preguntas/instrucciones :

- **Contexto preguntas**
El script se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CQ --ruta ruta/del/archivo/contextos/jsonl_

- **Contexto instrucciones**
El script se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CI --ruta ruta/del/archivo/contextos/jsonl_
 
Para las modalidades de test, el script requiere el parámetro adicional --option con un valor entre 1 y 4 que determina el tipo de test y si incluye justificación:

- **Test Multirespuesta CON justificación (sin contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --T --option 1_
- **Test Multirespuesta SIN justificación (sin contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --T --option 2_
- **Test Verdadero/Falso CON justificación (sin contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --T --option 3_
- **Test Verdadero/Falso SIN justificación (sin contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --T --option 4_

Para generar tests basados en contextos extraídos de documentos, se utiliza --CT junto con --ruta y --option:

- **Test Multirespuesta CON justificación (con contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CT --option 1 --ruta ruta/del/archivo/contextos.jsonl_
- **Test Multirespuesta SIN justificación (con contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CT --option 2 --ruta ruta/del/archivo/contextos.jsonl_
- **Test Verdadero/Falso CON justificación (con contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CT --option 3 --ruta ruta/del/archivo/contextos.jsonl_
- **Test Verdadero/Falso SIN justificación (con contexto)**
Se ejecutaría de la siguiente forma: _metodo_magpie_vllm.py --CT --option 4 --ruta ruta/del/archivo/contextos.jsonl_

Obviamente, estos prompts dependen del archivo config.yaml y cada modalidad y opción puede ser variada de la forma que se desee simplemente cambiando el prompt en dicho archivo.

## Metodología empleada

En cuanto a metodología empleada para la generación de datos sintéticos se ha optado por usar la metodología Magpie tras leer el siguiente paper: [link](https://arxiv.org/abs/2406.08464).


Esta metodología indica que se puede usar un modelo instruct ya existente para la generación de pregunta/instrucciones y respuestas para el entrenamiento de un modelo LLM.

La metodología se basa en lo siguiente:

Un modelo instruct tiene como entrada la siguiente estructura:


```
<|system|>
System_prompt
<|eot_ID|>

<|user|>
User_prompt
<|eot_ID|>

<|assistant|>
Assistant_prompt
<|eot_ID|>
```

Normalmente la parte de user es la consulta que introduce el usuario y la respuesta sería lo que responda el assitant. Bien, como lo que se quiere es simular preguntas que puede hacer un usuario sobre el ambito que se desee simplemente el prompt que se le introduce sería el siguiente:

```
<|begin_of_text|>\n<|start_header_id|>system<|end_header_id|>\n{system_prompt}\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>
```
De esta forma el propio modelo de lenguaje rellena la parte correspondiente al usuario devolviendo preguntas o instrucciones. Estas consultas generadas automaticamente son respondidas más tarde por el mismo modelo.

La idea para generar datos sintéticos basados en un contexto se basa en que en vez de que el modelo genere la parte entera del usuario, genere a partir de un contexto ya dada de la siguiente forma:

```
<|begin_of_text|>\n<|start_header_id|>system<|end_header_id|>\n{system_prompt}\n<|eot_id|>\n<|start_header_id|>user<|end_header_id|>Dado el siguiente contexto: '{context}'\n 
```

Así el modelo generará la pregunta/instrucción en base a lo que ya esta pregenerado en el rol de usuario. Obviamnente {context} va sustituyendose por los diferentes contextos para los que interesan generar datos sintéticos.


Para que el modelo sea capaz de hacer esto es importante crear un buen system_prompt el cual se explicará en el siguiente apartado.

### Adaptación al dominio legal

Destacat tambien, que, a diferencia de magpie estándar, se emplean prompts de sistema fuertemente condicionados al dominio legal para forzar que las instrucciones y preguntas se mantengan dentro de este ámbito


## Explicación de la lógica
- Generación de preguntas/instrucciones
El hecho de que estas modalidades existan es porque están enfocadas a usar un tipo de system prompt u otro. A continuación se deja cada prompt dependiendo si el objetivo es hacer preguntas o instrucciones:


**Instrucciones:**

```
Eres un asistente consultor especializado en el ámbito legal, donde tendrás que responder preguntas al usuario sobre el dominio castellano.


Debes ser capaz de manejar distintos tipos de consultas, estos son algunos ejemplos de instrucciones que pueden hacerte:


Instrucciones o solicitudes (en imperativo o indicativo) unicamente sobre temas legales, como por ejemplo:
- Haz un resumen sobre...
- Redacta...
- Resume...
- Elabora...
- Describe...
- Analiza...
- Indica...
- Señala...
- Genera...
- Explícame...
```

**Preguntas:**
```
Eres un asistente consultor especializado en el ámbito legal, donde tendrás que responder preguntas al usuario sobre el dominio castellano.


Debes ser capaz de manejar distintos tipos de consultas, estos son algunos ejemplos de preguntas que pueden hacerte:


- Preguntas directas unicamente sobre temas legales, algunos ejemplos son:
    - ¿Qué...?
    - ¿Cómo...?
    - ¿Cuáles...?
    - ¿Por qué...?
    - ¿Dónde...?
    - ¿Cuándo...?
    - ¿Cuál...?

```

**Multirespuesta con justificación**
```
Eres un asistente consultor especializado en el ámbito legal, cuya función es responder preguntas tipo test (de opción múltiple) sobre temas legales en castellano.

Tu objetivo es responder preguntas claras, precisas y correctamente formuladas, con tres o cuatro opciones de respuesta, de las cuales una o varias pueden ser correctas.

Las preguntas estarán redactadas de forma profesional.

El usuario proporcionará tres o cuatro posibles opciones (A, B, C, D).

Céntrate únicamente en el ámbito legal (civil, penal, laboral, administrativo, constitucional, mercantil, etc.).


Ejemplo de pregunta:

Pregunta: Según el Código Civil español, ¿cuál de las siguientes opciones corresponde a un requisito esencial para la validez del contrato?

A) Que sea celebrado ante notario.
B) Que exista consentimiento, objeto y causa.
C) Que se inscriba en el Registro de la Propiedad.
D) Que sea verbal y no escrito.

```
**Multirespuesta sin justificación:**
```
Eres un asistente consultor especializado en el ámbito legal, cuya función es responder preguntas tipo test (de opción múltiple) sobre temas legales en castellano.

Tu objetivo es responder preguntas claras, precisas y correctamente formuladas, con tres o cuatro opciones de respuesta, de las cuales una o varias pueden ser correctas.

Las respuestas deben de ser muy escuetas y breves, es decir, diciendo la opción correcta sin dar ninguna justificación.

Las preguntas estarán redactadas de forma profesional.

El usuario proporcionará tres o cuatro posibles opciones (A, B, C, D).

Céntrate únicamente en el ámbito legal del dominio legal (civil, penal, laboral, administrativo, constitucional, mercantil, etc.).


Ejemplo de pregunta:

Pregunta: Según el Código Civil español, ¿cuál de las siguientes opciones corresponde a un requisito esencial para la validez del contrato?

A) Que sea celebrado ante notario.
B) Que exista consentimiento, objeto y causa.
C) Que se inscriba en el Registro de la Propiedad.
D) Que sea verbal y no escrito.

```
**Verdadero o Falso con justificación:**
```
Eres un asistente consultor especializado en el ámbito legal, cuya función es responder preguntas tipo Verdadero o Falso (V/F) sobre temas legales en el idioma castellano.

Tu objetivo es analizar y responder afirmaciones en el ámbito legal de forma clara, precisa y fundamentada, indicando si son verdaderas o falsas, de acuerdo con el marco normativo vigente en el ámbito legal.

Las afirmaciones estarán redactadas de manera profesional y basadas en normas, principios o jurisprudencia aplicable.


Ejemplo de pregunta:

Pregunta: Responde verdadero o falso: En el Derecho Civil español, el contrato de compraventa requiere necesariamente forma escrita para ser válido.

Respuesta esperada: Falso. La forma escrita no es requisito esencial para la validez del contrato de compraventa, salvo en casos específicos (por ejemplo, transmisión de bienes inmuebles que requiere escritura pública para su inscripción registral).

Limítate estrictamente al análisis del ámbito legal, sin incluir opiniones personales o consideraciones ajenas al Derecho.

```
**Verdadero o Falso sin justificación:**
```
Eres un asistente consultor especializado en el ámbito legal, cuya función es responder preguntas tipo Verdadero o Falso (V/F) sobre temas legales en el idioma castellano.

Tu objetivo es analizar y responder afirmaciones en el ámbito legal de forma escueta, precisa, respondiendo únicamente si la afirmación es Verdadero o Falso, sin dar más explicaciones, de acuerdo con el marco normativo vigente en el ámbito legal.

Las afirmaciones estarán redactadas de manera profesional y basadas en normas, principios o jurisprudencia aplicable.


Ejemplo de pregunta:

Pregunta: Responde verdadero o falso: En el Derecho Civil español, el contrato de compraventa requiere necesariamente forma escrita para ser válido.

Respuesta esperada: Falso.

```

**Aclaración sobre prompts**:
Todo esto se puede ver en el fichero de configuracion config.yaml:
- Las opciones --CQ (Context Question) y --CI (Context Instruction) cuentan con prompts especializados (PROMPT_CONTEXT_QUESTION y PROMPT_CONTEXT_INSTRUCTION) específicamente diseñados para trabajar con contextos.
- En cambio, las opciones de test con contexto --CT (Context Test) no requieren prompts adicionales, ya que emplean los mismos prompts base de las modalidades de test general (--T: PROMPT_TEST_OPTION_1 a PROMPT_TEST_OPTION_4).
  

Para generar preguntas/instrucciones con contexto se puede utilizar el mismo prompt que para preguntas generales, con copiar, por ejemplo, el prompt que hay en PROMPT_QUESTION y pegarlo en PROMPT_CONTEXT_QUESTION basta para generar preguntas con contexto. 

Para generar preguntas multirespuesta o verdadero o falso con contexto no haría falta hacer nada. Con verificar que a la hora de ejecutar el script se haga con la opción -CT basta.



Tras múltiples pruebas se cree que este es el prompt óptimo para cada una de las alternativas.

En primera instancia se optó por usar ejemplos para que el modelo reflejara preguntas similares a las que se le proporcionaba, como por ejemplo, en cuanto a generación de preguntas:

```
- ¿Qué documentos necesito para una demanda de desahucio?
- ¿Cómo se calcula la pensión compensatoria en un divorcio en España?
- ¿Cuáles son las penas por estafa agravada?
```

El problema de este tipo de prompt era que el modelo se sobre ajustaba demasiado a los ejemplos y generaba estos mismo ejemplos como pregunta. Si que es verdad que generaba preguntas no tan similares a estas pero la mayoría de las preguntas eran idénticas o muy parecidas a las que se le pasaba como ejemplo. Es por esto que se crearon estos prompts que utilizan puntos suspensivos para que el modelo rellene la pregunta o instrucción correspondiente.

**Generación de respuesta**: 
Para la generación de la respuesta es el mismo enfoque en las dos alternativas ya que se utiliza como prompt del usuario la instrucción que se ha generado anteriormente.


## Formato de salida

El formato de salida que se espera es el siguiente:
```
{
  "system_prompt": "<PROMPT_DEL_SISTEMA>",
  "question": "<INSTRUCCION_GENERADA>",
  "response": "<RESPUESTA_GENERADA>"
}
```

## Proceso de limpieza y depuración de datos

Con el objetivo de garantizar la calidad de los datos utilizados durante el entrenamiento y la evaluación de modelos, se aplicó un proceso de limpieza y depuración en varias etapas. Este proceso evolucionó en el tiempo: inicialmente se trabajó con datos generados por **Llama-3.1-8B-Instruct** y **Phi-4**, pero tras detectar problemas de calidad, se reconstruyó todo el conjunto utilizando únicamente datos de **Phi-4**.

---

### 1. Generación inicial con Llama-3.1-8B-Instruct

En una primera fase, el dataset se generó combinando instrucciones y preguntas con los modelos **Llama-3.1-8B-Instruct** y **Phi-4**.  

Durante esta etapa inicial, el volumen de datos fue el siguiente:

- **Generados con Llama-3.1-8B-Instruct**:  
  - 1 460 248 líneas de instrucciones  
  - 858 714 líneas de preguntas  

- **Generados con Phi-4**:  
  - 817 408 líneas de instrucciones  
  - 952 766 líneas de preguntas  

- **Totales iniciales**: 4 089 136 líneas  

#### Problemas detectados con Llama
Tras la primera limpieza, se observó que muchas instrucciones generadas por **Llama** contenían tokens extraños incrustados dentro de las frases y, en general, una falta de coherencia en el contenido.  

Esto afectaba negativamente a la calidad de los datos, por lo que se tomó la decisión de **descartar completamente las instrucciones provenientes de Llama** y reconstruir el dataset final únicamente con **Phi-4**.

---

### 2. Limpieza inicial (duplicados y respuestas no válidas)

- **`Detección de duplicados`**:  
  Se analizaron todas las preguntas del conjunto de datos para identificar entradas idénticas mediante coincidencia exacta de cadenas.  

- **`Eliminación de duplicados`**:  
  Una vez detectados, se conservaron únicamente instancias únicas.  

- **`Eliminación de respuestas no válidas`**:  
  Se descartaron aquellas respuestas en las que el modelo no respondía y, en su lugar, pedía disculpas (respuestas que comenzaban con *"Lo siento"*).

---

### 3. Reconstrucción del dataset con Phi-4

Tras descartar los datos generados por **Llama-3.1-8B-Instruct**, se rehízo el dataset únicamente con datos generados con **Phi-4**, garantizando mayor coherencia y consistencia.

---

### 4. Filtro por similitud semántica

- Se aplicó un filtrado adicional para garantizar la coherencia entre pregunta y respuesta.  
- Preguntas y respuestas fueron convertidas en vectores de *embeddings* utilizando **jina-embeddings-v3**.  
- Se calculó la **similitud del coseno** para cada par.  
- Aquellas instancias con una similitud inferior al **50%** se eliminaron por considerarse incoherentes.  

---

### 5. Impacto en el conjunto de datos

El proceso de depuración se ha aplicado únicamente a la generación de instrucciones las cuales se han generado sin contexto, generaciones que dependen únicamente del conocimiento del modelo y no de un contexto que se le pase. Dicha limpieza se refleja en las siguientes cifras:

**Preguntas/Instrucciones**

| Etapa | Nº Instrucciones | Reducción vs. etapa anterior | Reducción acumulada |
|-------|-----------|------------------------------|----------------------|
| Dataset inicial (sin limpieza) | 3 300 000 | – | – |
| Después de limpieza básica (duplicados + respuestas no válidas) | 2 911 366 | -388 634 (-11.8%) | -388 634 (-11.8%) |
| Después de filtro por similitud ≥ 50% | 2 910 210 | -1 156 (≈0.04%) | -389 790 (-11.8%) |

En total, se eliminaron aproximadamente **389 790 ejemplos (11.8 % del dataset original)**, mejorando así la calidad y consistencia de los datos finales.

## Información general dataset generado
Se adjunta a continuación una tabla informativa sobre el nº de instrucciones y de tokens de cada uno de los datasets que se han generado:



| Archivo                                                                 | Tokens          | Líneas     |
|-------------------------------------------------------------------------|-----------------|------------|
| datos_sinteticos-legal-instrucciones-con_contexto.jsonl                | 2,193,000,545   | 1,304,300  |
| datos_sinteticos-legal-preguntas-con_contexto.jsonl                    | 2,140,299,681   | 1,309,738  |
| datos_sinteticos-legal-instrucciones-sin_contexto.jsonl                | 1,489,117,414   | 1,575,096  |
| datos_sinteticos-legal-preguntas-sin_contexto.jsonl                    | 1,327,174,522   | 1,715,133  |
| datos_sinteticos-legal-v_f-con_contexto-sin_justificacion.jsonl        | 158,277,017     | 132,036    |
| datos_sinteticos-legal-multirespuesta-sin_contexto-con_justificacion.jsonl | 130,851,646 | 200,860 |
| datos_sinteticos-legal-v_f-sin_contexto-con_justificacion.jsonl        | 103,113,730     | 200,344    |
| datos_sinteticos-legal-multirespuesta-sin_contexto-sin_justificacion.jsonl | 82,433,715  | 200,544    |
| datos_sinteticos-legal-v_f-con_contexto_sin_aparicion-sin_justificacion.jsonl | 66,069,001 | 225,557 |
| datos_sinteticos-legal-multirespuesta-con_contexto-sin_justificacion.jsonl | 62,672,377  | 43,706     |
| datos_sinteticos-legal-v_f-con_contexto-con_justificacion.jsonl        | 56,683,073      | 34,574     |
| datos_sinteticos-legal-multirespuesta-con_contexto-con_justificacion.jsonl | 56,240,005  | 34,908     |
| datos_sinteticos-legal-multirespuesta-con_contexto_sin_aparicion-sin_justificacion.jsonl | 56,079,917 | 109,936 |
| datos_sinteticos-legal-v_f-sin_contexto-sin_justificacion.jsonl        | 53,454,775      | 203,498    |
| datos_sinteticos-legal-v_f-con_contexto_sin_aparicion-con_justificacion.jsonl | 43,947,955 | 61,554 |
| datos_sinteticos-legal-multirespuesta-con_contexto_sin_aparicion-con_justificacion.jsonl | 42,632,875 | 60,025 |


En total se han generado 7,411,809 instrucciones con  un total de 8,061,047,248 tokens en total.

<!-- #### Scripts utilizados

- **`dataset_synthetic_data.json`** → Responsable de la limpieza inicial (duplicados y respuestas no válidas).  
- **`quality_embeddings.py`** → Encargado de calcular similitudes semánticas entre pregunta y respuesta y de generar los subconjuntos filtrados.   -->
