# ALIA | Grupo SINAI  
***Directorio de Datos | Discriminativos: Discurso de Odio (Hate Speech)***

Bienvenido al subdirectorio de datos del [Grupo SINAI](https://sinai.ujaen.es/alia) para el proyecto [ALIA](https://alia.gob.es/).

Investigamos en tecnologías del lenguaje y queremos que estas tecnologías sean abiertas y transparentes. Por eso, compartir nuestros recursos y documentación es parte de este compromiso.

En este subdirectorio agrupamos los scripts, configuraciones y lanzadores para la recolección, curación y anotación de datos destinados a tareas discriminativas relacionadas con discurso de odio.

*Happy coding*

---

## Índice de Documentación
- [Documentación de Datos Discriminativos de Discurso de Odio](/documentation/data/discriminative/hate_speech)

## Índice de ficheros en el directorio
- Ficheros y subdirectorios principales
  - [data/discriminative/hate_speech/collect_data](data/discriminative/hate_speech/collect_data)
    - [data/discriminative/hate_speech/collect_data/collect_tiktok.py](data/discriminative/hate_speech/collect_data/collect_tiktok.py) — Script para recolectar datos de TikTok.
    - [data/discriminative/hate_speech/collect_data/collect_youtube.py](data/discriminative/hate_speech/collect_data/collect_youtube.py) — Script para recolectar datos de YouTube.
    - [data/discriminative/hate_speech/collect_data/config.yaml.example](data/discriminative/hate_speech/collect_data/config.yaml.example) — Ejemplo de configuración para la recolección.
    - [data/discriminative/hate_speech/collect_data/environment.yml](data/discriminative/hate_speech/collect_data/environment.yml) — Entorno Conda recomendado.
  - [data/discriminative/hate_speech/curate_data](data/discriminative/hate_speech/curate_data)
    - [data/discriminative/hate_speech/curate_data/curation_process.py](data/discriminative/hate_speech/curate_data/curation_process.py) — Proceso de curación y filtrado.
    - [data/discriminative/hate_speech/curate_data/config.yaml.example](data/discriminative/hate_speech/curate_data/config.yaml.example) — Ejemplo de configuración de curación.
    - [data/discriminative/hate_speech/curate_data/launcher.sbs](data/discriminative/hate_speech/curate_data/launcher.sbs) — Lanzador para ejecución en cluster/cola.
    - [data/discriminative/hate_speech/curate_data/environment.yml](data/discriminative/hate_speech/curate_data/environment.yml) — Entorno Conda recomendado.
  - [data/discriminative/hate_speech/annotate_data](data/discriminative/hate_speech/annotate_data)
    - [data/discriminative/hate_speech/annotate_data/annotate_process.py](data/discriminative/hate_speech/annotate_data/annotate_process.py) — Script principal de anotación.
    - [data/discriminative/hate_speech/annotate_data/annotate_config.yaml.example](data/discriminative/hate_speech/annotate_data/annotate_config.yaml.example) — Ejemplo de configuración de anotación.
    - [data/discriminative/hate_speech/annotate_data/annotate_launcher.sbs](data/discriminative/hate_speech/annotate_data/annotate_launcher.sbs) — Lanzador para el pipeline de anotación.
    - [data/discriminative/hate_speech/annotate_data/fusion_process.py](data/discriminative/hate_speech/annotate_data/fusion_process.py) — Proceso de fusión/ensemble de anotaciones.
    - [data/discriminative/hate_speech/annotate_data/fusion_config.yaml.example](data/discriminative/hate_speech/annotate_data/fusion_config.yaml.example) — Ejemplo de configuración de fusión.
    - [data/discriminative/hate_speech/annotate_data/fusion_launcher.sbs](data/discriminative/hate_speech/annotate_data/fusion_launcher.sbs) — Lanzador para el proceso de fusión.
    - [data/discriminative/hate_speech/annotate_data/fusion_model.pkl](data/discriminative/hate_speech/annotate_data/fusion_model.pkl) — Modelo de fusión (serializado).
    - [data/discriminative/hate_speech/annotate_data/prompt.md](data/discriminative/hate_speech/annotate_data/prompt.md) — Plantillas de prompt para anotadores/LLMs.
    - [data/discriminative/hate_speech/annotate_data/environment.yml](data/discriminative/hate_speech/annotate_data/environment.yml) — Entorno Conda recomendado.

---

**Sigue estas guías para asegurar la coherencia y eficiencia en el trabajo con ALIA.**
