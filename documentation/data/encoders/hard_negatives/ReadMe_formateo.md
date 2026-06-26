# Conversor de Dataset JSONL a Formato SWIFT

Este script en **Python** convierte un dataset en formato **JSONL** con
ejemplos de búsqueda (query, positivos y negativos) al formato requerido
por **SWIFT**, agrupando múltiples negativos por cada query.

El script también permite adaptar datasets que usen distintos nombres de
campos, por ejemplo:

-   `query` o `question`
-   `passage` o `context`

Esto se controla mediante argumentos por línea de comandos.

------------------------------------------------------------------------

# Características

-   Agrupa múltiples negativos por cada query.
-   Convierte datasets JSONL al formato requerido por SWIFT.
-   Permite definir nombres personalizados para:
    -   campo de consulta (`query_field`)
    -   campo de documento positivo (`passage_field`)
-   Puede procesar:
    -   un archivo JSONL
    -   una carpeta completa con múltiples JSONL.
-   Ignora líneas JSON inválidas sin detener el procesamiento.

------------------------------------------------------------------------

# Formato de Entrada

Cada línea del JSONL debe tener una estructura similar a:

``` json
{
  "query": "¿Qué es la fotosíntesis?",
  "passage": "La fotosíntesis es el proceso mediante el cual...",
  "negative": "Los volcanes se forman cuando..."
}
```

Algunos datasets usan otros nombres:

``` json
{
  "question": "¿Qué es la fotosíntesis?",
  "context": "La fotosíntesis es el proceso mediante el cual...",
  "negative": "Los volcanes se forman cuando..."
}
```

El script permite indicar estos nombres mediante parámetros.

------------------------------------------------------------------------

# Formato de Salida

Cada registro generado tendrá la estructura requerida:

``` json
{
  "messages": [
    {"role": "user", "content": "query"}
  ],
  "positive_messages": [
    [
      {"role": "user", "content": "passage"}
    ]
  ],
  "negative_messages": [
    [
      {"role": "user", "content": "negative 1"}
    ],
    [
      {"role": "user", "content": "negative 2"}
    ]
  ]
}
```

Cada negativo se guarda como una lista independiente dentro de
`negative_messages`.

------------------------------------------------------------------------

# Instalación

Requisitos:

-   Python 3.11 o superior

------------------------------------------------------------------------

# Uso

## Uso básico

``` bash
python formatear_datos_list_neg.py -i dataset.jsonl -o salida.jsonl
```

Los argumentos `-i` y `-o` son obligatorios. El script no incluye rutas
locales por defecto.

------------------------------------------------------------------------

## Especificar archivo de entrada y salida

``` bash
python formatear_datos_list_neg.py -i dataset.jsonl -o salida.jsonl
```

------------------------------------------------------------------------

## Usar campos personalizados (question/context)

``` bash
python formatear_datos_list_neg.py -i dataset.jsonl -o salida.jsonl --query_field question --passage_field context
```

------------------------------------------------------------------------

## Procesar una carpeta completa

``` bash
python formatear_datos_list_neg.py -i carpeta_datasets -o carpeta_salida
```

Todos los archivos `.jsonl` dentro de la carpeta serán convertidos.

------------------------------------------------------------------------

# Argumentos

  -----------------------------------------------------------------------
  Argumento                      Descripción
  ------------------------------ ----------------------------------------
  `-i`, `--input`                Archivo o carpeta de entrada

  `-o`, `--output`               Archivo o carpeta de salida

  `--query_field`                Nombre del campo de query (default:
                                 `query`)

  `--passage_field`              Nombre del campo de documento positivo
                                 (default: `passage`)
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# Flujo del Script

1.  Lee el dataset JSONL línea por línea.
2.  Agrupa los registros por query.
3.  Asocia:
    -   1 positivo
    -   múltiples negativos
4.  Genera el formato compatible con SWIFT.
5.  Guarda el resultado en un nuevo archivo JSONL.

------------------------------------------------------------------------

# Ejemplo de ejecución

``` bash
python formatear_datos_list_neg.py -i hard_negatives_dataset.jsonl -o dataset_swift.jsonl --query_field question --passage_field context
```

------------------------------------------------------------------------

# Autor

Script diseñado para preparar datasets de **hard negatives** para
entrenamiento con **SWIFT**.
