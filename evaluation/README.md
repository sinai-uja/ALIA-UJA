# ALIA | Grupo SINAI

***Módulo de Evaluación***

Bienvenido al repositorio de código del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y queremos que estas tecnologías sean abiertas y transparentes. Por eso, compartir nuestro código es parte de este compromiso.

En este repositorio no solo encontrarás cómo *entrenar* y *explotar* **modelos del lenguaje grandes**, sino también la documentación que hemos generado en el proceso y que puede ser útil para entender cómo hemos construido nuestros modelos (que también son tuyos).

*Happy coding*

---

## Índice de Documentación

- [Documentación de evaluación](/documentation/evaluation)
- [Evaluación de encoders con MTEB](/documentation/evaluation/encoders/process_evaluation_mteb.md)
- [Evaluación de modelos de embeddings LLM-as-judge con RAGAS (estado preliminar)](/documentation/evaluation/encoders/process_evaluation_ragas.md)


---

## Alcance del módulo

Este módulo centraliza la evaluación reproducible de modelos y tareas del proyecto ALIA.

Actualmente incluye:

- Evaluación de **encoders** (bi-encoders y cross-encoders).
- Scripts de formateo y ejecución batch para métricas estáticas.
- Estructura de resultados por tarea y dominio.

## Estructura actual

- [evaluation/encoders/scripts](encoders/scripts): scripts y plantillas de configuración.
- [evaluation/encoders/results](encoders/results): salidas de evaluación organizadas por tarea/dominio.
- [evaluation/encoders/README.md](encoders/README.md): README local del submódulo.

## Flujo rápido de uso

1. Copia y adapta los ficheros `.example` de [evaluation/encoders/scripts](encoders/scripts).
2. Prepara/formatea datos de evaluación con `evaluation_format_data.py` cuando aplique.
3. Lanza evaluación con `launcher_evaluation_biencoder.sh` o `launcher_evaluation_crossencoder.sh`.
4. Revisa salidas en [evaluation/encoders/results](encoders/results).

## Notas

- Este directorio centraliza la parte de evaluación del proyecto.
- La documentación funcional y metodológica vive en [documentation/evaluation](../documentation/evaluation).

## Índice de Directorios Principales
- [Directorio de Documentacion](/documentation)
  - [Directorio de Documentación de Datos](/documentation/data)
  - [Directorio de Documentación de Modelos](/documentation/models)
  - [Directorio de Documentación de Evaluación](/documentation/evaluation)
- [Directorio de Datos](/data)
  - [Directorio de Datos para LLMs](/data/llms)
  - [Directorio de Datos para Modelos Encoders](/data/encoders)
  - [Directorio de Datos Paralelos](/data/parallel)
- [Directorio de Modelos](/models)
  - [Directorio de Datos para LLMs](/models/llms)
  - [Directorio de Datos para Modelos Encoders](/models/encoders)
- [Directorio de Evaluación](/evaluation)

**Sigue estas guías para asegurar la coherencia y eficiencia en el trabajo con ALIA.**
