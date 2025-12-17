# Configuración del Pipeline de Personas (`config.yaml`)

Este fichero configura un script que procesa archivos Parquet para asignar "personas" a fragmentos de texto (chunks) basándose en similitud de embeddings.

---

## Parámetros Principales

### Entorno y Modelo
- `model_path`: Ruta local al modelo de embeddings (compatible con vLLM).
- `tensor_parallel_size`: Número de GPUs para paralelismo.
- `gpu_utilization`: Porcentaje de VRAM a utilizar (ej. `0.9`).
- `cpus_per_task`: Hilos de CPU para MKL/OMP (ej. `"64"`).
- `max_model_len`: Longitud máxima de tokens por texto.
- `seed`: Semilla para reproducibilidad.

### Lotes (Batching)
- `batch_size`: Textos a procesar en paralelo en GPU.
- `write_batch_size`: Filas a acumular antes de escribir a disco.

### Rutas de Datos (I/O)
- `parquet_path`: Patrón `glob` para los Parquet de entrada (ej. `/data/chunks/*.parquet`).
- `output_path`: Directorio donde se guardarán los Parquet de salida.
- `personas_source_path`: Ruta al Parquet con la lista de personas (debe tener columna `character`).
- `embeddings_pkl_path`: Ruta al fichero `.pkl` para cachear los embeddings de las personas.