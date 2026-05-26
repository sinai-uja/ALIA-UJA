# vLLM

Este directorio contiene el flujo local con vLLM.

## Ejecutar todo desde Python

```bash
cp config.yaml.example config.yaml
python run.py
```

`run.py` arranca `vllm serve`, espera a que el servidor responda y despues ejecuta `process_questions.py`.

## Ejecutar en SLURM

```bash
cp config.yaml.example config.yaml
cp launcher_question_variator.sh.example launcher_question_variator.sh
sbatch launcher_question_variator.sh
```

Edita `config.yaml` para indicar el modelo, el puerto, la memoria de GPU, el paralelismo y las rutas de entrada/salida.
El launcher arranca `vllm serve`, espera a que responda y despues ejecuta `process_questions.py`.
