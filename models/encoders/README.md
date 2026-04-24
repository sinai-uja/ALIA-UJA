# ALIA | Grupo SINAI
***Directorio de Modelos | Modelos Encoders: Embeddings y Reranker***

Bienvenido al repositorio de código del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y creemos que estas tecnologías deben ser abiertas y transparentes. Compartir nuestro código es parte de ese compromiso.

En este repositorio encontrarás no solo cómo *entrenar* y *explotar* **modelos del lenguaje grandes**, sino también la documentación que hemos generado en el proceso y que puede ser útil para entender cómo hemos construido nuestros modelos (que también son tuyos).

*Happy coding*

---

## Primeros Pasos

Este directorio contiene los scripts de entrenamiento y los ficheros de configuración para modelos encoder de tipo **Sentence Transformer** (bi-encoders y cross-encoders), con soporte tanto para entrenamiento estándar como para búsqueda de hiperparámetros con Optuna.

### Configuración

Antes de ejecutar cualquier script de entrenamiento, copia los ficheros de configuración de ejemplo y rellena tus rutas y parámetros:

```bash
cp config_optuna.yaml.example config_optuna.yaml
cp config_train.yaml.example config_train.yaml
```

Edita cada fichero para establecer la ruta del modelo, las rutas de los datasets, el directorio de salida y los hiperparámetros.

### Scripts de Entrenamiento

| Script | Descripción |
|---|---|
| `train_cl_biencoder.py` | Entrenamiento estándar de un modelo bi-encoder |
| `train_cl_crossencoder.py` | Entrenamiento estándar de un cross-encoder (reranker) |
| `train_optuna_biencoder.py` | Búsqueda de hiperparámetros con Optuna para bi-encoder |
| `train_optuna_crossencoder.py` | Búsqueda de hiperparámetros con Optuna para cross-encoder |

### Flujo de Trabajo Típico

1. **Búsqueda de hiperparámetros** — ejecuta `train_optuna_*.py` para encontrar la mejor configuración para tu dominio y dataset.
2. **Entrenamiento completo** — introduce los mejores hiperparámetros en `config_train.yaml` y ejecuta `train_cl_*.py`.

---

## Índice de Documentación
- [Flujo de trabajo del entrenamiento de los Modelos de Embeddings y Reranker](/documentation/models/encoders/metodology.md)

## Índice de Ficheros en el Directorio
- Ficheros de configuración
  - [`config_optuna.yaml.example`](/models/encoders/config_optuna.yaml.example) — Plantilla de configuración para la búsqueda de hiperparámetros con Optuna
  - [`config_train.yaml.example`](/models/encoders/config_train.yaml.example) — Plantilla de configuración para el entrenamiento estándar
- Scripts de entrenamiento
  - [`train_cl_biencoder.py`](/models/encoders/train_cl_biencoder.py) — Entrenamiento de bi-encoder
  - [`train_cl_crossencoder.py`](/models/encoders/train_cl_crossencoder.py) — Entrenamiento de cross-encoder
  - [`train_optuna_biencoder.py`](/models/encoders/train_optuna_biencoder.py) — Búsqueda Optuna para bi-encoder
  - [`train_optuna_crossencoder.py`](/models/encoders/train_optuna_crossencoder.py) — Búsqueda Optuna para cross-encoder

---

## Índice de Directorios Principales

- [Directorio de Documentación](/documentation)
  - [Directorio de Documentación de Datos](/documentation/data)
  - [Directorio de Documentación de Modelos](/documentation/models)
  - [Directorio de Documentación de Evaluación](/documentation/evaluation)
- [Directorio de Datos](/data)
  - [Directorio de Datos para LLMs](/data/llms)
  - [Directorio de Datos para Modelos Encoders](/data/encoders)
  - [Directorio de Datos Paralelos](/data/parallel)
- [Directorio de Modelos](/models)
  - [Directorio de Modelos LLMs](/models/llms)
  - [Directorio de Modelos Encoders](/models/encoders)
- [Directorio de Evaluación](/evaluation)

**Sigue estas guías para asegurar la coherencia y eficiencia en el trabajo con ALIA.**