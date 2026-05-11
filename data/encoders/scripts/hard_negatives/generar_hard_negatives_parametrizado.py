from sentence_transformers.util import mine_hard_negatives
from sentence_transformers import SentenceTransformer
import polars as pl
from datasets import Dataset
import gc
import torch
import os
from pathlib import Path
import argparse
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("⚠️  psutil no está instalado. El monitoreo de memoria estará desactivado.")


def monitorear_memoria(etiqueta=""):
    """Imprime el uso actual de memoria"""
    if not PSUTIL_AVAILABLE:
        return  # No hacer nada si psutil no está disponible


    """Imprime el uso actual de memoria"""
    mem = psutil.virtual_memory()
    gpu_mem = torch.cuda.memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
    gpu_reserved = torch.cuda.memory_reserved() / 1024**3 if torch.cuda.is_available() else 0
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] 💾 {etiqueta}")
    print(f"  RAM: {mem.used/1024**3:.1f}GB/{mem.total/1024**3:.1f}GB ({mem.percent:.1f}%)")
    if torch.cuda.is_available():
        print(f"  GPU: {gpu_mem:.1f}GB allocated, {gpu_reserved:.1f}GB reserved")

def cargar_modelo(model_path):
    print(f"--- Cargando modelo: {model_path} ---")
    model = SentenceTransformer(model_path)
    if torch.cuda.is_available():
        model = model.to('cuda')
        print("Modelo cargado en GPU (CUDA)")
    else:
        print("Modelo cargado en CPU")

    monitorear_memoria("Modelo cargado")
    return model

def cargar_dataset_completo(dataset_path, filtro):
    """Carga el dataset completo filtrado con Polars (sin convertir a HF aún)"""
    print(f"\nCargando dataset para filtro: {filtro}")
    monitorear_memoria("Antes de cargar dataset")

    # Cargar y filtrar con Polars
    df_pl = pl.read_ndjson(dataset_path)
    df_pl = df_pl.filter(pl.col("difficulty").is_in({filtro}))

    total_filas = len(df_pl)
    print(f"Filas tras filtrado: {total_filas}")

    monitorear_memoria("Dataset filtrado en Polars")
    return df_pl, total_filas

def generacion_hard_negatives(hf_dataset, model, sampling_strategy):
    """Genera hard negatives con parámetros optimizados para memoria"""
    print(f"Iniciando mining (Estrategia: {sampling_strategy})...")
    monitorear_memoria("Antes de mining")

    # Mining de negativos con configuración optimizada
    dataset_hard_negatives = mine_hard_negatives(
        dataset=hf_dataset,
        model=model,
        output_scores=True,
        range_min=10,
        range_max=50,
        max_score=0.8,
        relative_margin=0.05,
        num_negatives=5,
        sampling_strategy=sampling_strategy,
        batch_size=16,
        use_faiss=True,
        anchor_column_name="query",
        positive_column_name="passage"
    )

    monitorear_memoria("Después de mining")
    return dataset_hard_negatives

def guardar_resultados(resultados_list, nombre):
    """Guarda los resultados combinados de todos los chunks"""
    base_dir = Path(nombre).parent
    nombre_archivo = Path(nombre).name
    base_dir.mkdir(parents=True, exist_ok=True)

    output_path = base_dir / f"hard_negatives_{nombre_archivo}.jsonl"
    print(f"\n🔗 Combinando {len(resultados_list)} chunks y guardando...")
    monitorear_memoria("Antes de combinar chunks")

    # Combinar todos los DataFrames de Polars
    df_final = pl.concat(resultados_list)

    print(f"Total de filas combinadas: {len(df_final)}")
    print(f"Escribiendo a: {output_path}")

    # ESCRITURA SEGURA PARA SISTEMAS DISTRIBUIDOS (Lustre/HPC)
    with open(output_path, "wb") as f:
        df_final.write_ndjson(f)
        f.flush()
        os.fsync(f.fileno())

    file_size = os.path.getsize(output_path) / (1024*1024)
    print(f"✅ Guardado confirmado. Tamaño: {file_size:.2f} MB")

    del df_final
    gc.collect()
    monitorear_memoria("Después de guardar")

def procesar_por_chunks(model, dataset_path, filtro, strategy, nombre_salida, chunk_size=50000):
    """
    Procesa el dataset en chunks para evitar OOM.

    Args:
        chunk_size: Número de filas por chunk. Ajusta según memoria disponible.
                   Valores recomendados: 30000-100000
    """
    print(f"\n{'='*60}")
    print(f"ETAPA: {nombre_salida}")
    print(f"Procesamiento por chunks de {chunk_size} filas")
    print(f"{'='*60}")

    # 1. Cargar dataset completo filtrado (solo en Polars, ligero)
    df_pl, total_filas = cargar_dataset_completo(dataset_path, filtro)

    # 2. Calcular número de chunks
    num_chunks = (total_filas + chunk_size - 1) // chunk_size  # Redondeo hacia arriba
    print(f"\n📦 Se procesarán {num_chunks} chunks")

    # 3. Procesar cada chunk
    resultados_chunks = []
    chunks_exitosos = 0
    chunks_fallidos = 0

    for i in range(num_chunks):
        inicio = i * chunk_size
        fin = min((i + 1) * chunk_size, total_filas)
        filas_chunk = fin - inicio

        print(f"\n{'─'*60}")
        print(f"📦 Chunk {i+1}/{num_chunks} | Filas {inicio:,} - {fin:,} ({filas_chunk:,} filas)")
        print(f"{'─'*60}")

        try:
            # Extraer chunk de Polars
            df_chunk_pl = df_pl.slice(inicio, filas_chunk)

            # Convertir a Pandas y luego a HF Dataset
            df_chunk_pd = df_chunk_pl.to_pandas()
            hf_chunk = Dataset.from_pandas(df_chunk_pd)

            # Limpiar intermedios
            del df_chunk_pl, df_chunk_pd
            gc.collect()

            monitorear_memoria(f"Chunk {i+1} cargado")

            # Generar hard negatives para este chunk
            result_chunk = generacion_hard_negatives(hf_chunk, model, sampling_strategy=strategy)

            # Convertir resultado a Polars y guardar
            result_pl = pl.from_pandas(result_chunk.to_pandas())
            resultados_chunks.append(result_pl)
            chunks_exitosos += 1

            print(f"✅ Chunk {i+1} procesado: {len(result_pl):,} filas generadas")

            # Limpiar memoria agresivamente
            del hf_chunk, result_chunk, result_pl
            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            monitorear_memoria(f"Después de chunk {i+1}")

        except Exception as e:
            chunks_fallidos += 1
            print(f"❌ ERROR en chunk {i+1}: {str(e)}")
            print(f"   Continuando con el siguiente chunk...")

            # Limpiar en caso de error
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            # Si fallan muchos chunks seguidos, mejor abortar
            if chunks_fallidos >= 3 and chunks_exitosos == 0:
                raise Exception("Demasiados chunks fallidos consecutivos. Abortando.")

            continue

    # 4. Limpiar dataset original
    del df_pl
    gc.collect()

    # 5. Verificar que hay resultados
    if not resultados_chunks:
        raise Exception("❌ No se procesó ningún chunk exitosamente")

    print(f"\n📊 Resumen: {chunks_exitosos} chunks exitosos, {chunks_fallidos} fallidos")

    # 6. Guardar resultados combinados
    guardar_resultados(resultados_chunks, nombre_salida)

    # 7. Limpiar todo
    del resultados_chunks
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    monitorear_memoria("Limpieza final")

def parse_args():
    parser = argparse.ArgumentParser(
        description='Generar hard negatives para datasets (con procesamiento por chunks)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:

  # Ejecutar UNA tarea específica:
  python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl --filtro phd --estrategia random --nombre dataset_dificil_random

  # Ejecutar TODAS las tareas por defecto (6 combinaciones):
  python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl

  # Con chunk-size personalizado:
  python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl --chunk-size 30000
        """
    )

    parser.add_argument('--1', dest='filtro', type=str, default=None,
                        help='Filtro de dificultad (ej: phd, university, high_school)')
    parser.add_argument('--filtro', dest='filtro', type=str,
                        help='Alias legible de --1')
    parser.add_argument('--2', dest='estrategia', type=str, default=None,
                        help='Estrategia de sampling (ej: top, random)')
    parser.add_argument('--estrategia', dest='estrategia', type=str,
                        help='Alias legible de --2')
    parser.add_argument('--3', dest='nombre', type=str, default=None,
                        help='Nombre del archivo de salida')
    parser.add_argument('--nombre', dest='nombre', type=str,
                        help='Alias legible de --3')
    parser.add_argument('--model-path', default=os.environ.get("MODEL_PATH"),
                        help='Ruta del modelo SentenceTransformer. También puede definirse con MODEL_PATH.')
    parser.add_argument('--dataset-path', default=os.environ.get("DATASET_PATH"),
                        help='Ruta del dataset JSONL/NDJSON. También puede definirse con DATASET_PATH.')
    parser.add_argument('--output-dir', default="hard_negatives_generados",
                        help='Directorio de salida (default: hard_negatives_generados).')
    parser.add_argument('--chunk-size', type=int, default=50000,
                        help='Tamaño de cada chunk (default: 50000). Reducir si hay OOM.')

    return parser.parse_args()

def ejecutar_tarea(model, dataset_path, output_dir, filtro, estrategia, nombre, chunk_size):
    """Ejecuta una tarea individual"""
    try:
        procesar_por_chunks(
            model=model,
            dataset_path=dataset_path,
            filtro=filtro,
            strategy=estrategia,
            nombre_salida=str(Path(output_dir) / nombre),
            chunk_size=chunk_size
        )
        return True
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR en tarea {nombre}: {str(e)}")
        print(f"{'='*60}")
        import traceback
        traceback.print_exc()
        return False

def main():
    print("\n" + "="*60)
    print("🚀 GENERADOR DE HARD NEGATIVES - VERSIÓN OPTIMIZADA")
    print("="*60)

    # Parsear argumentos
    args = parse_args()

    if not args.model_path or not args.dataset_path:
        print("\n❌ ERROR: Debes indicar --model-path y --dataset-path, o definir MODEL_PATH y DATASET_PATH.")
        print("\nEjemplo:")
        print("  python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl")
        exit(1)

    model_path = args.model_path
    dataset_path = args.dataset_path

    monitorear_memoria("Inicio")

    # Cargar modelo una sola vez
    model = cargar_modelo(model_path)

    # Determinar si ejecutar una tarea o todas
    if args.filtro is not None and args.estrategia is not None and args.nombre is not None:
        # MODO: Una tarea específica
        print(f"\n🎯 MODO: Tarea individual")
        print(f"  Filtro: {args.filtro}")
        print(f"  Estrategia: {args.estrategia}")
        print(f"  Nombre: {args.nombre}")
        print(f"  Chunk size: {args.chunk_size:,}")

        exito = ejecutar_tarea(
            model=model,
            dataset_path=dataset_path,
            output_dir=args.output_dir,
            filtro=args.filtro,
            estrategia=args.estrategia,
            nombre=args.nombre,
            chunk_size=args.chunk_size
        )

        if exito:
            print("\n" + "="*60)
            print("🎉 TAREA FINALIZADA EXITOSAMENTE")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("❌ TAREA FINALIZADA CON ERRORES")
            print("="*60)
            exit(1)

    elif args.filtro is None and args.estrategia is None and args.nombre is None:
        # MODO: Todas las tareas por defecto
        tareas = [
            ("high_school", "random", "dataset_facil_random"),
            ("university", "random", "dataset_medio_random"),
            ("phd", "random", "dataset_dificil_random"),
            ("high_school", "top", "dataset_facil_top"),
            ("university", "top", "dataset_medio_top"),
            ("phd", "top", "dataset_dificil_top"),
        ]

        print(f"\n🔄 MODO: Ejecutar TODAS las tareas por defecto")
        print(f"  Total de tareas: {len(tareas)}")
        print(f"  Chunk size: {args.chunk_size:,}")
        print(f"\nTareas a ejecutar:")
        for i, (filtro, estrategia, nombre) in enumerate(tareas, 1):
            print(f"  {i}. {nombre} (filtro={filtro}, estrategia={estrategia})")

        # Ejecutar todas las tareas
        resultados = []
        for i, (filtro, estrategia, nombre) in enumerate(tareas, 1):
            print(f"\n{'#'*60}")
            print(f"# TAREA {i}/{len(tareas)}: {nombre}")
            print(f"{'#'*60}")

            exito = ejecutar_tarea(
                model=model,
                dataset_path=dataset_path,
                output_dir=args.output_dir,
                filtro=filtro,
                estrategia=estrategia,
                nombre=nombre,
                chunk_size=args.chunk_size
            )

            resultados.append({
                'tarea': nombre,
                'filtro': filtro,
                'estrategia': estrategia,
                'exito': exito
            })

            # Pequeña pausa entre tareas para estabilizar memoria
            if i < len(tareas):
                print(f"\n⏸️  Pausa de 5 segundos antes de la siguiente tarea...")
                import time
                time.sleep(5)

        # Resumen final
        print("\n" + "="*60)
        print("📊 RESUMEN FINAL DE TODAS LAS TAREAS")
        print("="*60)

        exitosas = sum(1 for r in resultados if r['exito'])
        fallidas = sum(1 for r in resultados if not r['exito'])

        print(f"\n✅ Tareas exitosas: {exitosas}/{len(tareas)}")
        print(f"❌ Tareas fallidas: {fallidas}/{len(tareas)}")

        print(f"\nDetalle:")
        for r in resultados:
            estado = "✅" if r['exito'] else "❌"
            print(f"  {estado} {r['tarea']} ({r['filtro']}, {r['estrategia']})")

        if fallidas > 0:
            print("\n⚠️  ALGUNAS TAREAS FALLARON")
            exit(1)
        else:
            print("\n🎉 TODAS LAS TAREAS COMPLETADAS EXITOSAMENTE")

    else:
        # MODO: Error - parámetros incompletos
        print("\n❌ ERROR: Debes proporcionar los tres parámetros de tarea (--1, --2, --3) o ninguno")
        print("\nUso correcto:")
        print("  # Una tarea:")
        print("    python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl --filtro phd --estrategia random --nombre dataset_dificil_random")
        print("\n  # Todas las tareas:")
        print("    python generar_hard_negatives_parametrizado.py --model-path /ruta/modelo --dataset-path /ruta/dataset.jsonl")
        exit(1)

    # Limpieza final
    monitorear_memoria("Estado final")

if __name__ == "__main__":
    main()
