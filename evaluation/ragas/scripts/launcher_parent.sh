#!/usr/bin/env bash

# uso:
# bash launcher_parent.sh 

set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

LAUNCHER_SCRIPT="${LAUNCHER_SCRIPT:-$BASE_DIR/launcher.sh}"
CONFIG_FILE="${CONFIG_FILE:-config.yaml}"
LOGS_DIR="${LOGS_DIR:-$BASE_DIR/logs/launcher_parent}"

# false: detiene el lote en el primer fallo
# true: continúa con las siguientes ejecuciones aunque una falle
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-true}"

# true: imprime comandos sin ejecutar
DRY_RUN="${DRY_RUN:-false}"

if [[ ! -f "$LAUNCHER_SCRIPT" ]]; then
	echo "[ERROR] No existe launcher.sh en: $LAUNCHER_SCRIPT"
	exit 1
fi

mkdir -p "$LOGS_DIR"

# -----------------------------------------------------------------------------
# Definición de ejecuciones
# Formato por línea (separador '|'):
# domain|task|query_sample|context_sample|force
# task admitidas: retrieval|generation|all|hit
# -----------------------------------------------------------------------------
RUNS=()

# Ejemplos por defecto (puedes editar/agregar libremente):
# biomedical
RUNS+=("absanitas|retrieval|800|12596|false") # ejemplo

# También puedes inyectar runs por variable de entorno:
# export EXTRA_RUNS=$'legal|retrieval|1300|1300|false\nwilfredo|retrieval|500|11234|true'
if [[ -n "${EXTRA_RUNS:-}" ]]; then
	while IFS= read -r line; do
		[[ -z "$line" ]] && continue
		RUNS+=("$line")
	done <<< "$EXTRA_RUNS"
fi

echo "============================================================"
echo "Launching parent batch"
echo "- Launcher script: $LAUNCHER_SCRIPT"
echo "- Config: $CONFIG_FILE"
echo "- Logs dir: $LOGS_DIR"
echo "- Continue on error: $CONTINUE_ON_ERROR"
echo "- Dry run: $DRY_RUN"
echo "- Total runs: ${#RUNS[@]}"
echo "============================================================"

if [[ ${#RUNS[@]} -eq 0 ]]; then
	echo "[ERROR] No hay ejecuciones definidas en RUNS."
	exit 1
fi

success_count=0
fail_count=0

for i in "${!RUNS[@]}"; do
	run_def="${RUNS[$i]}"

	IFS='|' read -r domain task query_sample context_sample force <<< "$run_def"

	if [[ -z "${domain:-}" || -z "${task:-}" || -z "${query_sample:-}" || -z "${context_sample:-}" || -z "${force:-}" ]]; then
		echo "[WARN] Formato invalido en RUNS[$i]: '$run_def'"
		fail_count=$((fail_count + 1))
		if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
			exit 1
		fi
		continue
	fi

	case "$task" in
		retrieval|generation|all|hit)
			;;
		*)
			echo "[WARN] Task inválida en RUNS[$i]: '$task' (válidas: retrieval|generation|all|hit)"
			fail_count=$((fail_count + 1))
			if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
				exit 1
			fi
			continue
			;;
	esac

	run_id=$((i + 1))
	ts="$(date +%Y%m%d_%H%M%S)"
	log_file="$LOGS_DIR/run_${run_id}_${domain}_q${query_sample}_c${context_sample}_${ts}.log"

	echo ""
	echo "------------------------------------------------------------"
	echo "Run ${run_id}/${#RUNS[@]}"
	echo "- Domain: $domain"
	echo "- Task: $task"
	echo "- Query sample: $query_sample"
	echo "- Context sample: $context_sample"
	echo "- Force: $force"
	echo "- Log file: $log_file"
	echo "------------------------------------------------------------"

	cmd=(
		env
		DOMAIN="$domain"
		TASK="$task"
		FORCE="$force"
		QUERY_SAMPLE="$query_sample"
		CONTEXT_SAMPLE="$context_sample"
		RETRIEVAL_QUERY_SAMPLE="$query_sample"
		RETRIEVAL_CONTEXT_SAMPLE="$context_sample"
		FORMAT_QUERY_SAMPLE="$query_sample"
		FORMAT_CONTEXT_SAMPLE="$context_sample"
		RAGAS_QUERY_SAMPLE="$query_sample"
		RAGAS_CONTEXT_SAMPLE="$context_sample"
		CONFIG_FILE="$CONFIG_FILE"
		bash "$LAUNCHER_SCRIPT"
	)

	if [[ "$DRY_RUN" == "true" ]]; then
		printf '[DRY_RUN] '
		printf '%q ' "${cmd[@]}"
		printf '\n'
		success_count=$((success_count + 1))
		continue
	fi

	set +e
	"${cmd[@]}" 2>&1 | tee "$log_file"
	run_status=${PIPESTATUS[0]}
	set -e

	if [[ $run_status -eq 0 ]]; then
		echo "[OK] Run ${run_id} completado"
		success_count=$((success_count + 1))
	else
		echo "[ERROR] Run ${run_id} fallo con codigo: $run_status"
		fail_count=$((fail_count + 1))
		if [[ "$CONTINUE_ON_ERROR" != "true" ]]; then
			echo "[ERROR] Deteniendo lote por CONTINUE_ON_ERROR=false"
			exit "$run_status"
		fi
	fi
done

echo ""
echo "============================================================"
echo "Batch finished"
echo "- Successful runs: $success_count"
echo "- Failed runs: $fail_count"
echo "- Logs dir: $LOGS_DIR"
echo "============================================================"

if [[ $fail_count -gt 0 ]]; then
	exit 1
fi
