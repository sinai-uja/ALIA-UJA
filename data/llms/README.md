# ALIA | Grupo SINAI 
***Directorio de Datos | Modelos de Lenguaje***

Bienvenido al repositorio de código del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y queremos que estas tecnologías sean abiertas y transparentes. Por eso, compartir nuestro código es parte de este compromiso.

En este repositorio no solo encontrarás cómo *entrenar* y *explotar* **modelos del lenguaje grandes**, sino también la documentación que hemos generado en el proceso y que puede ser útil para entender cómo hemos construido nuestros modelos (que también son tuyos).

*Happy coding*

---

## Índice de Documentación
- Documentación de Datasets
  - [Documentación del Flujo de Trabajo para Contruir y Documentar un Dataset](/documentation/data/llms/plain/workflow.md)
    - [Proceso de Descarga](/documentation/data/llms/plain/process_download.md)
    - [Proceso de Documentación con metadatos](/documentation/data/llms/plain/process_metadata.md)
    - [Estándar de Estructura de Dataset](/documentation/data/llms/plain/standard_dataset_structure.md)
    - [Estándar de Estructura de Metadatos](/documentation/data/llms/plain/standard_metadata.md)
    - [Estándar de Licencias Disponibles y Usables](/documentation/data/llms/plain/standard_licenses.md)
  - [Información sobre los datasets contruidos](/documentation/data/llms/datasets)
    - [Datasets del dominio Biomédico](/documentation/data/llms/datasets/biomedical)
- Documentación de Corpora
  - [Proceso de Limpieza de Datos](/documentation/data/llms/corpora/process_curation.md)
- Documentación de Instrucciones
  - [Documentación de Genración de cabeceras para contextos](/documentation/data/llms/instructions/generate_headers.md)
  - [Documentación de Construcción de contextos](/documentation/data/llms/instructions/agreggate_contexts.md)
  - [Documentación de Generación de Instrucciones Sintéticas con MAGPIE](/documentation/data/llms/instructions/process_magpie.md)
- Documentación de Evaluación
  - [Tests de Evaluación para Oposiciones Legal-Administrativas Españolas](/documentation/data/llms/evaluation/legal_dataset.md)
  - [Tests de Evaluación para Oposiciones Sanitarias Españolas](/documentation/data/llms/evaluation/biomedical_dataset.md)


## Índice de ficheros en el directorio
- Ficheros de código
  - [Directorio de scripts para texto plano](/data/llms/scripts/plain)
  - [Directorio de scripts para instrucciones](/data/llms/scripts/instructions)
    - [Script de construcción de contextos](/data/llms/scripts/instructions/agreggate_contexts.py)
  - [Directorio de scripts para corpora](/data/llms/scripts/corpora)
  - [Directorio de scripts para evaluación](/data/llms/scripts/evaluation)

---

## Índice de Directorios Principales
- [Directorio de Documentacion](/documentation)
  - [Directorio de Documentación de Datos](/documentation/data)
  - [Directorio de Documentación de Modelos](/documentation/models)
  - [Directorio de Documentación de Evaluación](/documentation/evaluation)
- [Directorio de Datos](/data)
  - [Directorio de Datos para LLMs](/data/llms)
  - [Directorio de Datos para Modelos Encoders](/data/encoders)
  - [Directorio de Datos Paralelos](/data/parallel)
  - [Directorio de Datos Discriminativos](/data/discriminative)
- [Directorio de Modelos](/models)
  - [Directorio de Datos para LLMs](/models/llms)
  - [Directorio de Datos para Modelos Encoders](/models/encoders)
- [Directorio de Evaluación](/evaluation)

**Sigue estas guías para asegurar la coherencia y eficiencia en el trabajo con ALIA.**