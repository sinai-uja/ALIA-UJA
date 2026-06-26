import os
import sys
import argparse
import subprocess
from codecarbon import OfflineEmissionsTracker

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "carbon_reports")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--deepspeed", required=True)
    parser.add_argument("--run_name", required=False, default="default")
    args, unknown = parser.parse_known_args()

    # Validar config
    if not os.path.exists(args.config):
        print(f"❌ Error: no existe {args.config}")
        sys.exit(1)

    # CodeCarbon Tracker
    proc_id = int(os.environ.get("SLURM_PROCID", 0))
    node_id = int(os.environ.get("SLURM_NODEID", 0))
    job_id = os.environ.get("SLURM_JOBID", "unknown")
    output_file = f"{args.run_name}_base_job{job_id}_node{node_id}_proc{proc_id}.csv"

    tracker_cfg = {
        "save_to_file": True,
        "log_level": "ERROR",
        "tracking_mode": "machine",
        "output_dir": OUTPUT_DIR,
        "output_file": output_file,
        "country_iso_code": "ESP",
    }

    tracker = OfflineEmissionsTracker(**tracker_cfg)

    # Ejecutar Axolotl (sin config temporal)
    command = [
        "python", "-m", "axolotl.cli.train",
        "--config", args.config,
        "--deepspeed", args.deepspeed,
        "--log_level", "DEBUG",
    ]

    try:
        print("=" * 80)
        print(f"NODO {node_id} - PROCID {proc_id} - INICIANDO CODECARBON")
        print(f"Archivo de salida: {output_file}")
        print("=" * 80)

        tracker.start()
        process = subprocess.Popen(command)
        process.wait()
        returncode = process.returncode

    finally:
        print("=" * 80)
        print(f"NODO {node_id} - FINALIZANDO RASTREADOR")
        print("=" * 80)
        emissions_data = tracker.stop()
        if emissions_data:
            print(f"🌱 Nodo {node_id} - Emisiones: {emissions_data:.6f} kg CO₂")
            print(f"📂 Guardado en: {os.path.join(OUTPUT_DIR, output_file)}")
        else:
            print("⚠️ No se pudieron calcular emisiones.")

    sys.exit(returncode if returncode is not None else 1)

if __name__ == "__main__":
    main()
