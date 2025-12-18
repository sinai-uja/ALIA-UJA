#!/usr/bin/env python3
"""
Script para descargar COMET y todas sus dependencias para uso offline.
"""

import os
from pathlib import Path
from huggingface_hub import snapshot_download
from comet import load_from_checkpoint

# Configurar directorios
BASE_DIR = Path("models")
BASE_DIR.mkdir(exist_ok=True)

CACHE_DIR = BASE_DIR / "hf_cache"
CACHE_DIR.mkdir(exist_ok=True)

os.environ['HF_HOME'] = str(CACHE_DIR)
os.environ['TRANSFORMERS_CACHE'] = str(CACHE_DIR)

print("=" * 70)
print("Descargando modelo COMET desde Hugging Face")
print("=" * 70)

model_id = "Unbabel/wmt22-cometkiwi-da"
local_dir = BASE_DIR / "wmt22-cometkiwi-da"
# Descarga una lista de modelos y hace una verificación básica cuando es posible
models_to_download = [
    "Unbabel/wmt22-cometkiwi-da",
    "microsoft/infoxlm-large",
]

for model_id in models_to_download:
    local_dir = BASE_DIR / model_id.split("/")[-1]
    try:
        print("\n" + "=" * 60)
        print(f"Descargando {model_id} -> {local_dir}")
        print("=" * 60)

        snapshot_download(
            repo_id=model_id,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
        )

        print(f"✓ Modelo descargado en: {local_dir}")

        # Intentar verificación genérica:
        # 1) buscar checkpoints (.ckpt) y para esos intentar usar comet.load_from_checkpoint
        # 2) si no hay .ckpt, intentar cargar con transformers (si está disponible)
        ckpt_files = list(local_dir.rglob("*.ckpt"))

        if ckpt_files:
            ckpt_path = ckpt_files[0]
            print(f"✓ Checkpoint encontrado: {ckpt_path}")
            try:
                print("Verificando checkpoint con comet.load_from_checkpoint...")
                model = load_from_checkpoint(str(ckpt_path))
                print("✓ Checkpoint verificado correctamente (comet)")
            except Exception as e:
                print(f"⚠️  No se pudo verificar el checkpoint con comet: {e}")

            with open(local_dir / "checkpoint_path.txt", "w") as f:
                f.write(str(ckpt_path))

        else:
            # Intentar verificar con transformers si está instalado
            try:
                from transformers import AutoModel

                print("Buscando archivos de modelo y tratando de verificar con transformers...")
                try:
                    m = AutoModel.from_pretrained(str(local_dir))
                    print("✓ Modelo verificado con transformers (carga exitosa)")
                    # Guardar señal de verificación
                    with open(local_dir / "verified_with_transformers.txt", "w") as f:
                        f.write("verified")
                except Exception as e:
                    print(f"⚠️  No se pudo cargar el modelo local con transformers: {e}")
                    print("Listando archivos descargados:")
                    for f in local_dir.rglob("*"):
                        if f.is_file():
                            print(f"  {f.relative_to(local_dir)}")
            except Exception:
                print("transformers no disponible o fallo en import, no se realiza verificación con transformers.")
                print("Listando archivos descargados:")
                for f in local_dir.rglob("*"):
                    if f.is_file():
                        print(f"  {f.relative_to(local_dir)}")

    except Exception as e:
        print(f"✗ Error descargando/verificando {model_id}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("DESCARGA COMPLETADA")
print(f"Para cargar offline usa:")
print(f"  load_from_checkpoint('{local_dir}/checkpoints/model.ckpt')")
print("=" * 70)