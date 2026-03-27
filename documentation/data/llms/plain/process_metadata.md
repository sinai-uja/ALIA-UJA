Para cada dataset descargado y tratado en el marco del Proyecto ALIA, se debe generar la documentación descriptiva correspondiente que incluya sus metadatos estructurados.

*Grupo de investigación de Sistemas Inteligentes de Acceso a la Información | sinai@ujaen.es | Proyecto ALIA*

**Tabla de contenido**
- [Funcionamiento de las clases internas](#funcionamiento-de-las-clases-internas)
  - [Flujo principal](#flujo-principal)
    - [Documentación generada](#documentación-generada)
- [Ejecución del proceso de metadatos](#ejecución-del-proceso-de-metadatos)

---

# Funcionamiento de las clases internas

## Flujo principal

La función ``generate_metadata`` tiene como objetivo principal generar un archivo de metadatos en formato YAML para un conjunto de datos específico, identificado por un ``id``. Este proceso incluye la recopilación de información sobre el conjunto de datos, la extracción de características y la creación de un archivo estructurado que contiene todos los detalles relevantes.

La función genera un archivo de metadatos basado en una plantilla predefinida ([*template*](/data/llms/scripts/plain/documentation/template_metadata.yaml)). Si ya existe un archivo de metadatos previo, se carga para preservar información existente, como la versión del conjunto de datos, que se incrementa automáticamente. 

Primero, la función registra un mensaje de inicio en los logs y busca la ruta del directorio del conjunto de datos utilizando el método ``_search_dataset_dir``. 
- Esta función busca un directorio específico dentro de una estructura de carpetas, basado en un identificador (id). El identificador puede ser una ruta parcial como 'Boletines_Oficiales/BOC'. Los pasos principales son:
  1. Normalización del identificador: Se utiliza ``os.path.normpath`` para normalizar la ruta del identificador, eliminando redundancias como dobles barras ('//') y asegurando compatibilidad con diferentes sistemas operativos. Luego, se divide en partes usando ``os.sep`` como separador.
  2. Recorrido del árbol de directorios: Con ``os.walk``, se recorre recursivamente el árbol de directorios a partir del [directorio raíz](/data/llms/datasets). Este método devuelve una tupla con la ruta actual, las subcarpetas y los archivos.
  3. Cálculo de la ruta relativa: Se obtiene la ruta relativa de cada directorio (*rel_path*) respecto al directorio raíz usando ``os.path.relpath``. Esta ruta también se normaliza y se divide en partes.
  4. Comparación de rutas: Se verifica si las últimas partes de la ruta relativa coinciden con las partes del identificador. Si hay coincidencia, se devuelve la ruta completa del directorio.
  5. Retorno en caso de no encontrar coincidencias: Si no se encuentra un directorio que coincida con el identificador, la función devuelve None.

A partir de esta ruta, extrae dos elementos clave: el estado o procedencia (*provenance*) y el dominio principal (*subject*) del conjunto de datos. Luego, identifica los archivos de datos asociados al conjunto de datos, como los archivos en formato Parquet, y registra esta información en los logs.

A continuación, la función carga un archivo CSV llamado ``datasheet.csv`` que contiene información adicional sobre el conjunto de datos. Este archivo se utiliza para extraer detalles como el identificador, el nombre, la descripción, las tareas asociadas, la licencia, los derechos de autor, y otros metadatos relevantes. 

Todas estas características del fichero ``datasheet.csv`` se han conseguido a su vez de las resusetas proporcionadas por el desarrollador en el [Formulario de Documentación de un Dataset](https://docs.google.com/forms/d/e/1FAIpQLSdhJZBJZ0UD6rjiU0O1D4W9TOkYpHkyvhMfI8oyOzNKELlfCQ/viewform?usp=header).

Además, se extraen los atributos (*features*) y las instancias del conjunto de datos utilizando el método ``_extract_instances_and_features``, que analiza el archivo Parquet y clasifica las características según su tipo y descripción.
- La función tiene como objetivo extraer información sobre las características (*features*) y el número de instancias de un conjunto de datos almacenado en un archivo Parquet. Esta información se organiza en un formato estructurado que puede ser utilizado para generar metadatos.
  1. Carga del archivo Parquet:
     - Se utiliza la biblioteca Polars para leer el archivo Parquet especificado en el parámetro path.
     - Una vez cargado, se extraen los nombres de las columnas, los tipos de datos de las columnas y el número de filas o instancias del DataFrame.
  2. Iteración sobre las características:
     - Para cada columna del DataFrame, se verifica si su nombre está presente en la lista de divisores (divisors).
     - Si la columna es un **divisor**, se genera una descripción que incluye los valores únicos posibles de esa columna. Esto se logra llamando al método ``_get_divisors``, que extrae los valores únicos dependiendo del tipo de datos de la columna.
     - Se crea una entrada para la característica utilizando una plantilla ([template](/data/llms/scripts/plain/documentation/template_metadata.yaml)). Esta entrada incluye:
       - El identificador de la característica (``dc:identifier``), que corresponde al nombre de la columna.
       - La descripción (``dc:description``), que puede incluir información sobre si es un divisor y sus valores posibles.
       - El tipo de dato (``dc:type``), que se obtiene del tipo de la columna en el DataFrame.
  3. Manejo de errores durante la iteración:
     - Si ocurre un error al procesar una característica, se crea una entrada especial que indica el error.
  4. Retorno de resultados:
     1. Una lista de entradas (*entries*), donde cada entrada representa una característica del conjunto de datos.
     2. El número de instancias (*instances*) en el archivo Parquet.


### Documentación generada

Finalmente, la función guarda los metadatos generados en un archivo YAML utilizando el método _generate_yaml y también crea un archivo JSON con información adicional mediante ``_generate_info``. Ambos archivos se guardan en el directorio del conjunto de datos, y se registran mensajes en los logs para confirmar que los archivos se generaron correctamente. Este proceso asegura que toda la información relevante del conjunto de datos esté documentada y estructurada para su posterior uso.

# Ejecución del proceso de metadatos

Para que este proceso sea lo más sensillo posible para los desarrolladores, se ha creado un [fichero python](/data/llms/scripts/plain/main.py) para realizar el proceso completo con solo indicar el identificador del dataset a documentar.

Se utilizan dos clases, ``SpreadsheetRetriever`` y ``MetadataExtractor``, para procesar un conjunto de datos identificado por un argumento proporcionado desde la línea de comandos. 

A continuación, se explica su funcionamiento:

1. **Importación de clases**.
   - ``SpreadsheetRetriever``: Clase encargada de manejar hojas de cálculo y generar informes relacionados con los datos.
   - ``MetadataExtractor``: Clase que se encarga de extraer y generar metadatos estructurados para un conjunto de datos.

2. **Función ``process_documentation.py``**. La función principal realiza las siguientes tareas:

   1. Creación de objetos:
      - Se instancia un objeto de la clase ``SpreadsheetRetriever`` para manejar hojas de cálculo.
      - Se instancia un objeto de la clase ``MetadataExtractor`` para gestionar la extracción de metadatos.
   2. Procesamiento del conjunto de datos:
      - Se llama al método ``generate_report`` del objeto ``SpreadsheetRetriever``, que genera un informe basado en el identificador del conjunto de datos (``args.id``).
      - Se llama al método ``generate_metadata`` del objeto ``MetadataExtractor``, que genera un archivo de metadatos para el mismo conjunto de datos.
3. **Definición de argumentos**.
   - Se utiliza ``ArgumentParser`` para definir un argumento obligatorio (*-id*), que representa el identificador del conjunto de datos.


