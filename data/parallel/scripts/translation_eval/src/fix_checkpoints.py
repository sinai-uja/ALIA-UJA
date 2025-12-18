#!/usr/bin/env python3
"""
Script para modificar los checkpoints de COMET para usar XLM-RoBERTa local.
Ejecutar DESPUÉS de download_comet_offline.py
"""

import torch
from pathlib import Path

BASE_DIR = Path("models")

# Ruta al modelo XLM-RoBERTa local
XLM_LOCAL_PATH = str((BASE_DIR / "xlm-roberta-large").absolute())

# Checkpoints de COMET a modificar
checkpoints = [
    BASE_DIR / "wmt22-comet-da" / "checkpoints" / "model.ckpt",
    BASE_DIR / "wmt20-comet-qe-da" / "checkpoints" / "model.ckpt",
]

print("Modificando checkpoints de COMET para usar XLM-RoBERTa local...")
print(f"XLM-RoBERTa local: {XLM_LOCAL_PATH}\n")

for ckpt_path in checkpoints:
    if not ckpt_path.exists():
        print(f"⚠ Checkpoint no encontrado: {ckpt_path}")
        continue
    
    print(f"Procesando: {ckpt_path}")
    
    try:
        # Cargar checkpoint
        checkpoint = torch.load(ckpt_path, map_location='cpu')
        
        # Modificar la configuración del encoder
        if 'hyper_parameters' in checkpoint:
            hparams = checkpoint['hyper_parameters']
            
            # Cambiar el encoder_model a la ruta local
            if 'encoder_model' in hparams:
                old_model = hparams['encoder_model']
                hparams['encoder_model'] = XLM_LOCAL_PATH
                print(f"  ✓ encoder_model: {old_model} -> {XLM_LOCAL_PATH}")
            
            # Forzar local_files_only
            if 'load_pretrained_weights' not in hparams:
                hparams['load_pretrained_weights'] = False
                print(f"  ✓ load_pretrained_weights: False")
        
        # Guardar checkpoint modificado
        backup_path = ckpt_path.with_suffix('.ckpt.backup')
        if not backup_path.exists():
            ckpt_path.rename(backup_path)
            print(f"  ✓ Backup creado: {backup_path.name}")
        
        torch.save(checkpoint, ckpt_path)
        print(f"  ✓ Checkpoint modificado guardado\n")
        
    except Exception as e:
        print(f"  ✗ Error: {e}\n")

print("=" * 70)
print("MODIFICACIÓN COMPLETADA")
print("=" * 70)
print("\nAhora COMET usará el XLM-RoBERTa local sin intentar descargarlo.")