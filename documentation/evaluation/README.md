# ALIA | Grupo SINAI

***Documentación del módulo de Evaluación***

Bienvenido al repositorio de código del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y queremos que estas tecnologías sean abiertas y transparentes. Por eso, compartir nuestro código es parte de este compromiso.

En este repositorio no solo encontrarás cómo *entrenar* y *explotar* **modelos del lenguaje grandes**, sino también la documentación que hemos generado en el proceso y que puede ser útil para entender cómo hemos construido nuestros modelos (que también son tuyos).

*Happy coding*

---

## Índice de Documentación

- [Evaluación de encoders con MTEB](/documentation/evaluation/encoders/process_evaluation_mteb.md)
- [Evaluación LLM-as-judge con RAGAS (estado preliminar)](/documentation/evaluation/encoders/process_evaluation_ragas.md)


---

## Objetivo

Este directorio reúne la documentación técnica, metodológica y operativa del módulo [evaluation](/evaluation).

## Qué documenta este módulo

- Metodologías de evaluación por tipo de modelo/tarea.
- Estructura de datos de entrada/salida para los scripts de evaluación.
- Convenciones para reproducibilidad (configuración, rutas, ejecución offline y resultados).

## Subdirectorios

- [documentation/evaluation/encoders](encoders): documentación de evaluación de encoders.

## Recomendación de lectura

1. Empezar por [process_evaluation_mteb.md](encoders/process_evaluation_mteb.md).
2. Revisar después [process_evaluation_ragas.md](encoders/process_evaluation_ragas.md) para la línea LLM-as-judge.
3. Contrastar rutas y scripts con [evaluation/encoders/scripts](../../evaluation/encoders/scripts).

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
