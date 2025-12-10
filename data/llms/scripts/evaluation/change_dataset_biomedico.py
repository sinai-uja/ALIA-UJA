import polars as pl
import ast
import re
import sys

# Leer el CSV
df = pl.read_csv(
    "/mnt/beegfs/ammunoz/alia/data/llms/evaluation/evaluacion_biomedico_original.csv",
    quote_char='"',
    encoding='utf8'
)

# Filtrar filas que NO contengan "imagen" en la pregunta (case-insensitive)
df = df.filter(~pl.col('Pregunta').str.to_lowercase().str.contains('imagen'))

# Función para procesar cada fila
print(f"Filas después de filtrar 'imagen': {len(df)}")

# Función para parsear el formato especial de lista
def parsear_opciones(opciones_str):
    """
    Convierte el formato:
    ['texto1'
     'texto2'
     'texto3']
    
    A una lista real de Python
    """
    try:
        # Limpiar el string
        opciones_str = opciones_str.strip()
        
        # Extraer todas las strings entre comillas simples
        # Patrón: captura texto entre comillas simples
        patron = r"'([^']+)'"
        matches = re.findall(patron, opciones_str)
        
        if not matches:
            print(f"No se encontraron opciones en: {opciones_str[:100]}")
            return None
        
        return matches
        
    except Exception as e:
        print(f"Error parseando: {e}")
        return None

# Función para procesar cada fila
def procesar_fila(pregunta, opciones_str, respuesta_num, row_id):
    try:
        # Parsear las opciones
        opciones = parsear_opciones(opciones_str)
        
        if opciones is None:
            print(f"⚠️ ID {row_id}: No se pudieron parsear las opciones")
            return None, None
        
        num_opciones = len(opciones)
        print(f"✓ ID {row_id}: {num_opciones} opciones detectadas")
        
        # Validar rango
        if respuesta_num < 1 or respuesta_num > num_opciones:
            print(f"⚠️ ID {row_id}: Respuesta {respuesta_num} fuera de rango (hay {num_opciones} opciones)")
            return None, None
        
        # Crear pregunta completa
        texto_opciones = "\n".join([f"{i+1}. {opcion.strip()}" for i, opcion in enumerate(opciones)])
        pregunta_completa = f"{pregunta}\n\n{texto_opciones}"
        
        # Obtener respuesta correcta
        respuesta_correcta = opciones[respuesta_num - 1].strip()
        
        return pregunta_completa, respuesta_correcta
        
    except Exception as e:
        print(f"❌ ID {row_id}: Error - {type(e).__name__}: {e}")
        return None, None

# Procesar filas
resultado = []
filas_saltadas = 0

for row in df.iter_rows(named=True):
    pregunta_completa, respuesta_correcta = procesar_fila(
        row['Pregunta'],
        row['Opciones'],
        row['Respuesta_Correcta'],
        row['ID']
    )
    
    if pregunta_completa is not None:
        resultado.append({
            'ID': row['ID'],
            'Categoria': row['Categoria'],
            'Examen': row['Examen'],
            'Numero_Pregunta': row['Numero_Pregunta'],
            'Pregunta_Completa': pregunta_completa,
            'Respuesta_Correcta': respuesta_correcta
        })
    else:
        filas_saltadas += 1

# Crear nuevo DataFrame
df_nuevo = pl.DataFrame(resultado)

df_nuevo = df_nuevo.rename({
    'ID': 'instance_id',
    'Pregunta_Completa': 'input',
    'Respuesta_Correcta': 'expected_output'
    })

# Guardar
df_nuevo.write_csv("/mnt/beegfs/ammunoz/alia/data/llms/evaluation/evaluacion_biomedico_proces_galtea.csv")
print(f"Filas procesadas: {len(df_nuevo)}")
print(df_nuevo)
print(f"\n✅ Filas procesadas: {len(df_nuevo)}")
print(f"⚠️ Filas saltadas: {filas_saltadas}")
print(df_nuevo.head())