import pandas as pd
import os


def init_csv(path: str, df: pd.DataFrame):
    """Crea un CSV vacio con la columna actual_output inicializada."""
    df_out = df.copy()
    df_out["actual_output"] = ""
    df_out.to_csv(path, index=False)


def resume_csv(path: str) -> int:
    """
    Reanuda un CSV parcial.

    Devuelve el indice desde el que continuar, o -1 si ya esta completo.
    """
    if not os.path.exists(path):
        return 0

    existing = pd.read_csv(path)
    if "actual_output" not in existing.columns:
        return 0

    completed = existing["actual_output"].notna() & (existing["actual_output"].astype(str).str.strip() != "")
    start_idx = int(completed.sum())
    total = len(existing)

    if start_idx >= total:
        return -1
    return start_idx


def append_row(path: str, row: dict):
    """Anade una fila al CSV en modo append."""
    row_df = pd.DataFrame([row])
    row_df.to_csv(path, mode="a", header=False, index=False)
