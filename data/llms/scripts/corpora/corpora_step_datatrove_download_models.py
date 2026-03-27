# -----------------------------------------------------------------------------------------------------------------------
# INSTALAR LO NECESARIO DEL DATATROVE - EJECUTAR EN NODO00 CON PYTHON
# -----------------------------------------------------------------------------------------------------------------------

"""
Script para descargar modelos necesarios para datatrove en modo offline
Ejecutar desde una máquina con acceso a internet
"""

import os, sys
import requests
import logging
from tqdm import tqdm
# Importación de utilidades locales
sys.path.append(os.path.realpath("./"))
from utils.utils_alia import RichArgumentParser, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(funcName)s() - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.info(f"Iniciando módulo {os.path.basename(__file__)}")

# Configuración
config = load_config(os.path.join(os.path.dirname(__file__), "config.yaml"))

# Capturar el directorio de destino como argumento
parser = RichArgumentParser(description="Script para descargar modelos necesarios para datatrove en modo offline")
parser.add_argument("--model_dir", type=str, default=config['paths']['path-dir-datatrove-models'], help="Directorio donde se guardarán los modelos")
args = parser.parse_args()

DATATROVE_MODELS_DIR = args.model_dir

def download_file(url, destination):
    """Descarga un archivo con barra de progreso"""
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    
    if os.path.exists(destination):
        logging.info(f"✓ Ya existe: {destination}")
        return True
    
    try:
        logging.info(f"Descargando: {url}")
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        
        with open(destination, 'wb') as f, tqdm(
            desc=os.path.basename(destination),
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            for chunk in response.iter_content(chunk_size=8192):
                size = f.write(chunk)
                pbar.update(size)
        
        logging.info(f"✓ Descargado: {destination}")
        os.chmod(destination, 0o644)
        return True
    
    except Exception as e:
        logging.error(f"✗ Error descargando {url}: {e}")
        if os.path.exists(destination):
            os.remove(destination)
        return False

def main():
    
    logging.info("=" * 60)
    logging.info("DESCARGA DE MODELOS PARA DATATROVE (OFFLINE MODE)")
    logging.info("=" * 60)
    
    # Crear directorio base
    os.makedirs(DATATROVE_MODELS_DIR, exist_ok=True)
    
    # Modelos a descargar
    models = [
        {
            "name": "FastText Language Identification (lid.176.bin)",
            "url": "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin",
            "path": os.path.join(DATATROVE_MODELS_DIR, "lid", "ft176", "lid.176.bin")
        },
        {
            "name": "FastText Language Identification Compressed (lid.176.ftz)",
            "url": "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz",
            "path": os.path.join(DATATROVE_MODELS_DIR, "lid", "ft176", "lid.176.ftz")
        }
    ]
    
    # Descargar cada modelo
    results = []
    for model in models:
        logging.info(f"\n--- {model['name']} ---")
        success = download_file(model['url'], model['path'])
        results.append((model['name'], success))
    
    # Resumen
    logging.info("\n" + "=" * 60)
    logging.info("RESUMEN DE DESCARGAS")
    logging.info("=" * 60)
    for name, success in results:
        status = "✓ OK" if success else "✗ FAILED"
        logging.info(f"{status}: {name}")
    
    # Crear script de configuración de variables de entorno
    env_script = os.path.join(DATATROVE_MODELS_DIR, "setup_env.sh")
    with open(env_script, 'w') as f:
        f.write("#!/bin/bash\n")
        f.write("# Script para configurar variables de entorno para datatrove offline\n\n")
        f.write(f"export HF_HOME={DATATROVE_MODELS_DIR}\n")
        f.write(f"export HF_DATASETS_CACHE={DATATROVE_MODELS_DIR}/datasets\n")
        f.write(f"export DATATROVE_CACHE_DIR={DATATROVE_MODELS_DIR}\n")
        f.write("\necho 'Variables de entorno configuradas para datatrove offline'\n")
    
    os.chmod(env_script, 0o644)
    logging.info(f"\n✓ Script de configuración creado: {env_script}")
    logging.info(f"  Para usarlo: source {env_script}")
    
    # Instrucciones finales
    print("\n" + "=" * 60)
    print("INSTRUCCIONES DE USO")
    print("=" * 60)
    print(f"1. Los modelos se han descargado en: {DATATROVE_MODELS_DIR}")
    print(f"2. Antes de ejecutar tu script, ejecuta:")
    print(f"   source {env_script}")
    print(f"3. O añade estas líneas al inicio de tu script Python:")
    print(f"   import os")
    print(f"   os.environ['HF_HOME'] = '{DATATROVE_MODELS_DIR}'")
    print("=" * 60)

if __name__ == "__main__":
    main()

