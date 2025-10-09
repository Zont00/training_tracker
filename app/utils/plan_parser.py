import pandas as pd
import re

REQUIRED = {"Allenamento", "Esercizio", "Serie", "Ripetizioni", "Recupero"}

def _to_int_safe(x):
    try:
        return int(str(x).strip())
    except Exception:
        m = re.search(r"\d+", str(x))
        return int(m.group(0)) if m else 1

def parse_plan_from_df(df: pd.DataFrame) -> dict:
    cols = set(df.columns.astype(str))
    if not REQUIRED.issubset(cols):
        missing = ", ".join(REQUIRED - cols)
        raise ValueError(f"Mancano colonne richieste: {missing}")

    df["Allenamento"] = df["Allenamento"].astype(str).str.strip()
    df["Esercizio"] = df["Esercizio"].astype(str).str.strip()
    df["Ripetizioni"] = df["Ripetizioni"].astype(str).str.strip()
    df["Recupero"] = df["Recupero"].astype(str).str.strip()
    df["Serie"] = df["Serie"].apply(_to_int_safe)

    plan: dict[str, list] = {}
    for _, row in df.iterrows():
        day = row["Allenamento"]
        plan.setdefault(day, []).append({
            "name": row["Esercizio"],
            "sets": int(row["Serie"]),
            "reps": row["Ripetizioni"],
            "rest": row["Recupero"],
        })
    return plan
