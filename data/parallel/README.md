# ALIA | Grupo SINAI 
***Directorio de Datos | Corpus Paralelo y Entrenamiento de Modelos de Traducción***

Bienvenido al repositorio de código del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y queremos que estas tecnologías sean abiertas y transparentes. Por eso, compartir nuestro código es parte de este compromiso.

En este repositorio no solo encontrarás cómo *entrenar* y *explotar* **modelos del lenguaje grandes**, sino también la documentación que hemos generado en el proceso y que puede ser útil para entender cómo hemos construido nuestros modelos (que también son tuyos).

*Happy coding*

---

Este directorio contiene el pipeline completo para la preparación de datos, entrenamiento y evaluación de modelos de traducción automática (Español <-> Inglés), adaptados a dominios específicos como **Biomédico**, **Legal** y **Patrimonio**.

## Índice de Documentación
- [Directorio de datos de resultados](/data/parallel/data)
- [Directorio de documentación de BLEURT](/data/parallel/scripts/translation_eval/src/metrics/bleurt)

## Índice de ficheros en el directorio
- [Directorio de scripts](/data/parallel/scripts)
    - [Directorio del proceso de entrenamiento de los modelos de traducción](/data/parallel/scripts/train)
    - [Directorio del proceso de evaluación](/data/parallel/scripts/translation_eval)

---

## Estructura del Proyecto

El repositorio se organiza fundamentalmente en datos y scripts de procesamiento:

```
parallel/
├── data/
│   ├── raw/                 # Datos en bruto (archivos .parquet) organizados por dominio
│   └── proccessed/          # Datos limpios y divididos (train, validation, test)
└── scripts/
    ├── split_dataset_*.py   # Scripts de limpieza, normalización y división de datos
    ├── generate_translations_test.py # Inferencia: Generación de traducciones con modelos entrenados
    ├── train/               # Scripts de entrenamiento (Fine-tuning)
    └── translation_eval/    # Framework de evaluación de calidad (Métricas)
```

## Prerrequisitos

El entorno requiere Python y las siguientes librerías principales:
- **Procesamiento de datos**: `polars` (optimizado para grandes volúmenes), `pandas`
- **Modelado**: `torch`, `transformers`
- **Utilidades**: `tqdm`, `psutil`

## 1. Procesamiento de Datos (`scripts/split_dataset_*.py`)

Existen scripts específicos para cada dominio (`biomedical`, `legal`, `heritage`). Su función es transformar los datos crudos (`data/raw`) en conjuntos listos para el entrenamiento (`data/proccessed`).

### Flujo de Trabajo:
1.  **Ingestión**: Busca recursivamente archivos `.parquet` en la carpeta raw correspondiente.
2.  **Limpieza**: Filtra filas que no tengan contenido en los pares de idiomas (`text_es`, `text_en`).
3.  **Identificación**: Asigna y normaliza IDs únicos para cada muestra, incorporando identificadores de la fuente original (ej. EURLEX, IBECS).
4.  **Data Augmentation / Robustez**: Aplica transformaciones aleatorias (con 50% de probabilidad) al formato del texto (intercambio de saltos de línea y tabulaciones) para mejorar la robustez del modelo frente a variaciones de formato.
5.  **Splitting**: Divide el dataset de manera determinista (semilla fija):
    - **Test**: 5,000 muestras.
    - **Validación**: 100 muestras.
    - **Train**: Resto de datos.

### Ejecución:
```bash
python scripts/split_dataset_legal.py
python scripts/split_dataset_biomedical.py
# etc.
```

## 2. Entrenamiento (`scripts/train/`)

Contiene la lógica para el fine-tuning de modelos (basados en arquitecturas como Salamandra/Llama).
- **Scripts**: `train_biomedical.py`, `train_legal.py`, etc.
- **Configuración**: Archivos `.yaml` o `.json` (ej. `config_legal.yaml`) que definen hiperparámetros, rutas y configuraciones del modelo.

## 3. Inferencia y Generación (`scripts/generate_translations_test.py`)

Este script permite probar un modelo entrenado generando traducciones sobre el conjunto de test.

- **Entrada**: Archivo `test.parquet`.
- **Funcionamiento**:
    - Carga el modelo y tokenizador especificado (por defecto configurado para modelos tipo chat/instruct).
    - Detecta textos largos para dividirlos en párrafos si es necesario.
    - Genera traducciones en ambas direcciones: **ES -> EN** y **EN -> ES**.
    - Utiliza procesamiento por lotes (`BATCH_SIZE`) para eficiencia.
- **Resultados**: Genera un nuevo parquet con columnas `text_en_predicted` y `text_es_predicted`.

## 4. Evaluación (`scripts/translation_eval/`)

Módulo dedicado al cálculo de métricas de calidad de traducción automática.

### `main.py`
Punto de entrada para la evaluación. Soporta métricas léxicas (como BLEU) y semánticas/neuronales (como COMET o BLEURT).

**Argumentos Clave:**
- `--data`: Ruta al archivo `.parquet` con las predicciones.
- `--col-source`, `--col-reference`, `--col-prediction`: Nombres de las columnas en el dataframe.
- `--use-gpu`: Habilita aceleración por GPU para métricas pesadas.
- `--metrics`: Lista de métricas a calcular.

**Ejemplo:**
```bash
python scripts/translation_eval/main.py \
    --data data/proccessed/legal/test_results.parquet \
    --col-source text_es \
    --col-reference text_en \
    --col-prediction text_en_predicted \
    --metrics bleu comet
```
