import xml.etree.ElementTree as ET
import csv
from bs4 import BeautifulSoup
import os


# Ruta al archivo TMX
directorio_raiz = "C:/Users/Cristian/Espacio_virtual/ALIA/Patrimonio/parallel_global_voices"


segmentos_espanol = []

# Recorrer todas las carpetas y archivos
for carpeta_raiz, subcarpetas, archivos in os.walk(directorio_raiz):
    for archivo in archivos:
        if archivo.endswith('.html'):
            ruta_completa = os.path.join(carpeta_raiz, archivo)
            with open(ruta_completa, 'r', encoding='utf-8') as f:
                try:
                    soup = BeautifulSoup(f, 'html.parser')

                    # Buscar todas las filas de la tabla
                    filas = soup.find_all('tr')
                    for fila in filas:
                        columnas = fila.find_all('td')
                        if len(columnas) == 3:
                            texto_espanol = columnas[2].get_text(strip=True)
                            if texto_espanol:
                                print(f"Texto esp: {texto_espanol}")
                                segmentos_espanol.append(texto_espanol)
                except:
                    print("No se ha podido escrapear su contenido")

# Guardar todo en un archivo CSV
with open('segmentos_espanol.csv', 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['segmento_es'])
    for segmento in segmentos_espanol:
        writer.writerow([segmento])