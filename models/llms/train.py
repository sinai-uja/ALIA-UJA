import os
import sys
import argparse
from codecarbon import OfflineEmissionsTracker
import subprocess
import yaml

# 🔧 Parche para evitar el bucle infinito en SLURM (muy importante)
os.environ["CODECARBON_SLURM"] = "false"

OUTPUT_DIR = "/path/to/your/carbon_data"
PATH_YML = "/path/to/your/path/yaml"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--deepspeed", required=True)
    parser.add_argument("--run_name", required=True)
    args, unknown = parser.parse_known_args()

    mode = args.run_name
    yaml_path = PATH_YML
    if not os.path.exists(args.config):
        print(f"❌ Error: no existe {args.config}")
        sys.exit(1)

    # Leer paths.yaml
    with open(yaml_path, "r") as f:
        paths_cfg = yaml.safe_load(f)

    # Extraer las rutas que quieres
    dataset_2_path = None
    if mode == "raw" or mode == "inst":
        dataset_prepared_path = paths_cfg[args.run_name].get("dataset_prepared_path")
        output_dir = paths_cfg[args.run_name].get("output_dir")
        dataset_1_path = paths_cfg[args.run_name].get("dataset_1_path")
    elif mode == "30raw70inst" or mode == "50raw50inst" or mode == "70raw30inst":
        dataset_prepared_path = paths_cfg[args.run_name].get("dataset_prepared_path")
        output_dir = paths_cfg[args.run_name].get("output_dir")
        dataset_1_path = paths_cfg[args.run_name].get("dataset_1_path")
        dataset_2_path = paths_cfg[args.run_name].get("dataset_2_path")

    # Leer la configuración de Axolotl
    with open(args.config, "r") as f:
        axo_cfg = yaml.safe_load(f)

    # Sobrescribir rutas en Axolotl
    if dataset_1_path:
        axo_cfg["datasets"][0]["path"] = dataset_1_path
        print(dataset_1_path)
    if dataset_2_path:
        axo_cfg["datasets"][1]["path"] = dataset_2_path
        print(dataset_2_path)
    if dataset_prepared_path:
        axo_cfg["dataset_prepared_path"] = dataset_prepared_path
        print(dataset_prepared_path)
    if output_dir:
        axo_cfg["output_dir"] = output_dir
        print(output_dir)

    # Guardar configuración temporal
    tmp_config_path = "/tmp/axo_config_tmp.yaml"
    with open(tmp_config_path, "w") as f:
        yaml.dump(axo_cfg, f)

    # CodeCarbon Tracker
    proc_id = int(os.environ.get('SLURM_PROCID', 0))
    node_id = int(os.environ.get('SLURM_NODEID', 0))
    job_id = os.environ.get('SLURM_JOBID', 'unknown')
    output_file = f"{args.run_name}_base_job{job_id}_node{node_id}_proc{proc_id}.csv"

    tracker_cfg = {
        "save_to_file": True,
        "log_level": "WARNING",
        "tracking_mode": "machine",
        "output_dir": OUTPUT_DIR,
        "output_file": output_file,
        "country_iso_code": "ESP",
    }

    tracker = OfflineEmissionsTracker(**tracker_cfg)
    command = [
        "python", "-m", "axolotl.cli.train",
        "--config", tmp_config_path,
        "--deepspeed", args.deepspeed,
        "--log_level", "DEBUG"
    ]
    subprocess.run(command)

    try:
        print("=" * 80)
        print(f"NODO {node_id} - PROCID {proc_id} - INICIANDO CODECARBON")
        print(f"Archivo de salida: {output_file}")
        print(" ".join(command))
        print("=" * 80)

        tracker.start()
        process = subprocess.Popen(command)
        process.wait()

    except KeyboardInterrupt:
        print("\n⛔ Interrumpido por el usuario.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        print("=" * 80)
        print(f"NODO {node_id} - FINALIZANDO RASTREADOR")
        print("=" * 80)
        emissions_data = tracker.stop()
        if emissions_data:
            print(f"🌱 Nodo {node_id} - Emisiones: {emissions_data:.6f} kg CO₂")
            print(f"📂 Guardado")
        else:
            print(f"⚠️ Nodo {node_id} - No se pudieron calcular emisiones.")

if __name__ == "__main__":
    main()
