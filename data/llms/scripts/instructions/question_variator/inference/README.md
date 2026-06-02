# Inference

Este directorio contiene los flujos de inferencia remota.

## `new_questions.py`

Cliente asincrono para endpoints compatibles con OpenAI. Usalo cuando tu servidor exponga `/v1/chat/completions`.

```bash
cp config.yaml.example config.yaml
python new_questions.py
```

## `process_questions.py`

Cliente interactivo para APIs HTTP configurables con autenticacion, listado de modelos y chat.

```bash
cp config.yaml.example config.yaml
python process_questions.py
```

Los datos de entrada deben ser JSONL con al menos el campo `question`. Si existe un campo `response`, `new_questions.py` lo usa como contexto.
