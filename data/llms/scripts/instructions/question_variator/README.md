# Question Variator

Este directorio contiene el codigo ejecutable del proyecto y ficheros de configuracion `.example` anonimizados. No incluye datasets, salidas, logs, rutas privadas ni claves.

Uso:

1. Crea un entorno Python e instala las dependencias:

   ```bash
   pip install -r requirements.txt
   ```

2. Copia el fichero de ejemplo que necesites y quita el sufijo `.example`.
3. Sustituye los valores `CHANGE_ME_*` por los de tu entorno.

Estructura:

- `requirements.txt`: dependencias de Python.
- `inference/`: modo de inferencia remota.
- `inference/process_questions.py`: cliente interactivo para una API HTTP configurable.
- `inference/new_questions.py`: cliente asincrono para un endpoint compatible con OpenAI.
- `inference/config.yaml.example`: un unico config anonimo para los dos modos de inferencia.
- `inference/README.md`: notas de ejecucion para inferencia remota.
- `vllm/`: modo con servidor vLLM local.
- `vllm/config.yaml.example`: configuracion local de vLLM y del cliente.
- `vllm/process_questions.py`: cliente asincrono para el servidor vLLM local.
- `vllm/run.py`: arranca vLLM y despues ejecuta `process_questions.py`.
- `vllm/launcher_question_variator.sh.example`: plantilla SLURM generica para lanzar el flujo local con vLLM.
- `vllm/README.md`: notas de ejecucion para vLLM.

## Endpoint compatible con OpenAI

```bash
cd inference
cp config.yaml.example config.yaml
python new_questions.py
```

## Inferencia remota interactiva

```bash
cd inference
cp config.yaml.example config.yaml
python process_questions.py
```

## vLLM local

```bash
cd vllm
cp config.yaml.example config.yaml
python run.py
```

## vLLM en SLURM

```bash
cd github
cp vllm/config.yaml.example vllm/config.yaml
cp vllm/launcher_question_variator.sh.example vllm/launcher_question_variator.sh
sbatch vllm/launcher_question_variator.sh
```
