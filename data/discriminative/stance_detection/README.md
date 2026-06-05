# ALIA | Grupo SINAI  
***Directorio de Datos | Discriminativos: Detección de Postura (Stance Detection)***

Bienvenido al subdirectorio de datos del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Compartir nuestro código y recursos es fundamental para promover tecnologías de lenguaje abiertas y transparentes.

En este subdirectorio agrupamos los scripts, dependencias y configuraciones para la construcción del corpus de Detección de Postura (Stance Detection) basado en los datos abiertos de Decide Madrid.

*Happy coding*

---

## Índice de Documentación
- [Documentación de Datos Discriminativos de Detección de Postura](/documentation/data/discriminative/stance_detection)

## Índice de ficheros en el directorio
- **[config.yaml](config.yaml)** — Archivo de configuración para todo el pipeline.
- **[requirements.txt](requirements.txt)** — Dependencias requeridas para la ejecución de los scripts.
- **[scripts/](scripts/)** — Directorio con los scripts secuenciales del pipeline:
  - **[scripts/build_corpus.py](scripts/build_corpus.py)** — Paso 1: Construcción del corpus crudo a partir de los CSVs de Decide Madrid.
  - **[scripts/sampling.py](scripts/sampling.py)** — Paso 2: Muestreo estratificado de 3,000 comentarios.
  - **[scripts/generate_blocks.py](scripts/generate_blocks.py)** — Paso 3: División en 60 bloques de anotación con preguntas de control (gold standards).
  - **[scripts/create_forms.gs](scripts/create_forms.gs)** — Paso 4: Código de Google Apps Script para generar Google Forms automáticamente.
  - **[scripts/process_responses.py](scripts/process_responses.py)** — Paso 5: Procesamiento de las respuestas de los anotadores, validación de controles y cálculo de acuerdo inter-anotador (Fleiss' kappa).
  - **[scripts/README.md](scripts/README.md)** — Documentación detallada sobre el uso de cada script y el flujo completo de ejecución.

---

**Sigue estas guías para asegurar la coherencia y eficiencia en el trabajo con ALIA.**
