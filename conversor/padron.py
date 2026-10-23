"""Padrón de agentes: datos por legajo que NO están en el informe de Nacional.

Cada legajo equivale a un cargo de SAP. Mientras no se carguen los datos reales se usan
valores de PRUEBA (marcados en la columna `valor_prueba`), que el validador informa.
"""
from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import pandas as pd

from . import config
from .modelos import Recibo

COLUMNAS = [
    "legajo", "cuil", "nombre", "nro_cargo",
    "antig_admin_anios", "antig_admin_meses",
    "antig_otras_cajas_anios", "antig_otras_cajas_meses",
    "antig_docente_anios", "antig_docente_meses",
    "dias_inasistencia", "encuadre", "modalidad", "valor_prueba",
]
NUMERICAS = ["antig_admin_anios", "antig_admin_meses", "antig_otras_cajas_anios",
             "antig_otras_cajas_meses", "antig_docente_anios", "antig_docente_meses"]


def padron_vacio() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNAS})


def cargar_padron(origen: str | Path | BinaryIO | None = None) -> pd.DataFrame:
    origen = origen or config.PADRON_XLSX
    if isinstance(origen, (str, Path)) and not Path(origen).exists():
        return padron_vacio()
    df = pd.read_excel(origen, dtype=object)
    for c in COLUMNAS:
        if c not in df.columns:
            df[c] = None
    df = df[COLUMNAS].copy()
    df["legajo"] = df["legajo"].map(lambda v: str(v).strip()[:-2] if str(v).strip().endswith(".0") else str(v).strip())
    return df


def guardar_padron(df: pd.DataFrame, destino: str | Path | None = None) -> Path:
    destino = Path(destino or config.PADRON_XLSX)
    destino.parent.mkdir(parents=True, exist_ok=True)
    df[COLUMNAS].to_excel(destino, index=False)
    return destino


def completar_padron(recibos: list[Recibo], padron: pd.DataFrame | None) -> pd.DataFrame:
    """Devuelve el padrón con una fila por cada legajo del informe.

    Los legajos que no estaban reciben valores de PRUEBA (cargo único, antigüedades en 00,
    encuadre 13, modalidad P, sin inasistencias).
    """
    padron = padron if padron is not None else padron_vacio()
    padron = padron.copy()
    existentes = {str(x) for x in padron["legajo"]}
    usados = set()
    for v in padron["nro_cargo"]:
        try:
            usados.add(int(v))
        except (TypeError, ValueError):
            pass
    sig = config.CARGO_PRUEBA_INICIAL
    nuevas = []
    for rec in recibos:
        if rec.legajo in existentes:
            continue
        while sig in usados:
            sig += 1
        usados.add(sig)
        nuevas.append({
            "legajo": rec.legajo, "cuil": rec.cuil, "nombre": rec.nombre,
            "nro_cargo": f"{sig:04d}",
            **{c: 0 for c in NUMERICAS},
            "dias_inasistencia": 0,
            "encuadre": config.ENCUADRE_PRUEBA,
            "modalidad": config.MODALIDAD_PRUEBA,
            "valor_prueba": "SI",
        })
        existentes.add(rec.legajo)
    if nuevas:
        padron = pd.concat([padron, pd.DataFrame(nuevas)], ignore_index=True)
    # refrescar CUIL y nombre desde el informe (son informativos)
    info = {r.legajo: (r.cuil, r.nombre) for r in recibos}
    for i, leg in padron["legajo"].items():
        if leg in info:
            padron.at[i, "cuil"], padron.at[i, "nombre"] = info[leg]
    orden = {r.legajo: n for n, r in enumerate(recibos)}
    padron["_o"] = padron["legajo"].map(lambda x: orden.get(x, 10**6))
    padron = padron.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return padron
