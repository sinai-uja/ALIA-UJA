"""
Script para procesar una carpeta completa de archivos Parquet
"""
import asyncio
import argparse
from pathlib import Path
from main import load_config, run_pipeline

async def main():
    parser = argparse.ArgumentParser(description="Procesa una carpeta completa de archivos .parquet")
    parser = argparse.ArgumentParser(description="Procesa una carpeta completa de archivos .parquet")
    parser.add_argument("folder", nargs="?", help="Ruta a la carpeta (opcional). Si no se indica, usa la carpeta del dataset_path del config.")
    parser.add_argument("--config", default="config.yaml", help="Ruta al config.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print("❌ Config no encontrado")
        return

    config = load_config(config_path)

    if args.folder:
        folder_path = Path(args.folder)
    else:
        if "dataset_path" in config:
            dataset_path = Path(config["dataset_path"])
            folder_path = dataset_path.parent
            print(f"📂 No se especificó carpeta. Usando directorio del config: {folder_path}")
        else:
            print("❌ No se especificó carpeta y 'dataset_path' no está en config.")
            return

    if not folder_path.exists() or not folder_path.is_dir():
        print(f"❌ La ruta no es una carpeta válida: {folder_path}")
        return

    # Buscar todos los parquets
    files = list(folder_path.glob("*.parquet"))
    if not files:
        print(f"⚠️ No se encontraron archivos .parquet en {folder_path}")
        return

    print(f"📂 Encontrados {len(files)} archivos en la carpeta.")
    
    # Procesar secuencialmente el bucle de archivos, 
    # pero cada archivo usa su propio paralelismo interno por batches
    for i, file_path in enumerate(files):
        print(f"\n[{i+1}/{len(files)}] 🚀 Iniciando: {file_path.name}")
        try:
            await run_pipeline(config, dataset_path_override=file_path)
        except Exception as e:
            print(f"❌ Error procesando {file_path.name}: {e}")
            continue

    print(f"\n✅ Todos los archivos de la carpeta procesados.")

if __name__ == "__main__":
    asyncio.run(main())
