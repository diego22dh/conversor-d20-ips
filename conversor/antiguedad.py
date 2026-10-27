"""Listado de empleados con antigüedad (el instructivo exige 6 campos de 2 dígitos por línea:
años/meses de antigüedad IPS, de otras cajas y docente).

Se reconoce por nombre de encabezado (sin tildes ni mayúsculas). Clave: LEGAJO y/o CUIL. Antigüedad: columnas de
años y meses (docente, IPS/administrativa, otras cajas) o, solo para la docente, una fecha de ingreso (se calcula
hasta el último día del período, con una ADVERTENCIA porque el criterio de cómputo lo define el colegio/IPS).
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .conceptos import _norm
from .lector import normalizar_cuil
from .modelos import Hallazgo, Recibo
from .padron import NUMERICAS

ALIAS = {
    "legajo": {"EMPLEADO", "LEGAJO", "NRO LEGAJO", "N LEGAJO", "NUMERO DE LEGAJO", "LEG"},
    "cuil": {"CUIL", "CUIT", "CUIL CUIT", "C U I L"},
    "antig_docente_anios": {"ANTIGUEDAD DOCENTE ANOS", "ANOS ANTIGUEDAD DOCENTE", "ANOS ANTIGUEDAD DOCENTES",
                            "ANOS DOCENTE", "ANTIG DOCENTE ANOS", "ANOS ANTIG DOCENTE", "ANTIGUEDAD DOCENTE ANIOS"},
    "antig_docente_meses": {"ANTIGUEDAD DOCENTE MESES", "MESES ANTIGUEDAD DOCENTE", "MESES ANTIGUEDAD DOCENTES",
                            "MESES DOCENTE", "ANTIG DOCENTE MESES", "MESES ANTIG DOCENTE"},
    "antig_admin_anios": {"ANTIGUEDAD IPS ANOS", "ANOS ANTIGUEDAD IPS", "ANOS IPS", "ANTIGUEDAD ADMINISTRATIVA ANOS",
                          "ANOS ANTIGUEDAD ADMINISTRATIVA", "ANTIG IPS ANOS", "ANOS ANTIG IPS"},
    "antig_admin_meses": {"ANTIGUEDAD IPS MESES", "MESES ANTIGUEDAD IPS", "MESES IPS", "ANTIGUEDAD ADMINISTRATIVA MESES",
                          "MESES ANTIGUEDAD ADMINISTRATIVA", "ANTIG IPS MESES", "MESES ANTIG IPS"},
    "antig_otras_cajas_anios": {"ANTIGUEDAD OTRAS CAJAS ANOS", "ANOS ANTIGUEDAD OTRAS CAJAS", "ANOS OTRAS CAJAS",
                                "ANTIG OTRAS CAJAS ANOS"},
    "antig_otras_cajas_meses": {"ANTIGUEDAD OTRAS CAJAS MESES", "MESES ANTIGUEDAD OTRAS CAJAS", "MESES OTRAS CAJAS",
                                "ANTIG OTRAS CAJAS MESES"},
    # Listado de Empleados de Nacional: una sola columna "Antiguedad" con años enteros (sin meses)
    "antig_simple": {"ANTIGUEDAD", "ANTIG", "ANTIGUEDAD ANOS", "ANOS ANTIGUEDAD"},
    "fecha_antiguedad": {"FECHA ANTIGUEDAD", "FECHA DE ANTIGUEDAD", "FEC ANTIGUEDAD"},
    "fecha_ingreso_docente": {"FECHA INGRESO DOCENTE", "FECHA DE INGRESO DOCENTE", "INGRESO DOCENTE",
                              "FECHA INGRESO", "FECHA DE INGRESO", "FECHA ALTA DOCENTE", "FECHA ALTA"},
}


def plantilla_antiguedad() -> pd.DataFrame:
    return pd.DataFrame([
        {"Legajo": "1001", "CUIL": "20-12345678-6", "Antigüedad docente años": 12, "Antigüedad docente meses": 3,
         "Antigüedad IPS años": 12, "Antigüedad IPS meses": 3, "Antigüedad otras cajas años": 0,
         "Antigüedad otras cajas meses": 0}])


def _entero(v):
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f == int(f) else None
    except (TypeError, ValueError):
        return None


def _a_fecha(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    f = pd.to_datetime(v, dayfirst=True, errors="coerce")
    return None if pd.isna(f) else f.date()


def meses_entre(desde: date, hasta: date) -> int:
    """Meses completos entre dos fechas (el día de `hasta` cuenta si alcanza el día de `desde`)."""
    m = (hasta.year - desde.year) * 12 + hasta.month - desde.month
    return m - (1 if hasta.day < desde.day else 0)


def cargar_antiguedad(origen: str | Path | BinaryIO, periodo: str | None = None) -> tuple[pd.DataFrame, list[Hallazgo]]:
    """Lee el listado. Devuelve (df con legajo, cuil y las columnas de antigüedad halladas, hallazgos).
    `periodo` 'AAAA/MM' se usa solo si el listado trae fecha de ingreso en vez de años/meses."""
    crudo = pd.read_excel(origen, header=None, dtype=object)
    fila_enc, mapa = None, {}
    for i in range(min(10, len(crudo))):
        m: dict[str, int] = {}
        for pos, valor in enumerate(crudo.iloc[i].tolist()):
            n = _norm(valor)
            for clave, alias in ALIAS.items():
                if n in alias and clave not in m:
                    m[clave] = pos
        if ("legajo" in m or "cuil" in m) and len(m) > len(mapa):
            fila_enc, mapa = i, m
    if fila_enc is None:
        raise ValueError("No encontré columnas de LEGAJO o CUIL en el listado. Usá la planilla de ejemplo.")
    con_antig = [c for c in NUMERICAS if c in mapa]
    if "fecha_antiguedad" in mapa:                      # tiene prioridad sobre "Fecha Ingreso"
        mapa["fecha_ingreso_docente"] = mapa["fecha_antiguedad"]
    simple = "antig_simple" in mapa and "antig_docente_anios" not in mapa
    if not con_antig and not simple and "fecha_ingreso_docente" not in mapa:
        raise ValueError("El listado no tiene columnas de antigüedad (años/meses) ni fecha de ingreso docente.")

    hall: list[Hallazgo] = []
    filas = []
    for idx in range(fila_enc + 1, len(crudo)):
        r = crudo.iloc[idx].tolist()
        leg = str(r[mapa["legajo"]]).strip() if "legajo" in mapa and not pd.isna(r[mapa["legajo"]]) else ""
        if leg.endswith(".0"):
            leg = leg[:-2]
        cuil = normalizar_cuil(r[mapa["cuil"]]) if "cuil" in mapa and not pd.isna(r[mapa["cuil"]]) else ""
        if not leg and not cuil:
            continue
        reg = {"legajo": leg, "cuil": cuil}
        ref = leg or cuil
        for c in con_antig:
            v = _entero(r[mapa[c]])
            if v is None or v < 0 or (c.endswith("meses") and v > 11) or v > 99:
                hall.append(Hallazgo("ERROR", ref, c, f"Valor inválido en el listado: {r[mapa[c]]!r} (años 0-99; meses 0-11)."))
            else:
                reg[c] = v
        if simple:
            v = _entero(r[mapa["antig_simple"]])
            if v is None or not 0 <= v <= 99:
                hall.append(Hallazgo("ERROR", ref, "Antigüedad", f"Valor inválido en el listado: {r[mapa['antig_simple']]!r} (años 0-99)."))
            else:
                reg["antig_docente_anios"], reg["antig_docente_meses"] = v, 0
        if not con_antig and not simple:
            f = _a_fecha(r[mapa["fecha_ingreso_docente"]])
            if f is None:
                hall.append(Hallazgo("ERROR", ref, "fecha_ingreso_docente", f"Fecha inválida: {r[mapa['fecha_ingreso_docente']]!r}."))
            elif periodo is None:
                hall.append(Hallazgo("ERROR", ref, "fecha_ingreso_docente", "Falta el período para calcular la antigüedad."))
            else:
                y, m = int(periodo[:4]), int(periodo[5:7])
                fin = date(y, m, calendar.monthrange(y, m)[1])
                tot = meses_entre(f, fin)
                if tot < 0:
                    hall.append(Hallazgo("ERROR", ref, "fecha_ingreso_docente", "La fecha de ingreso es posterior al período."))
                else:
                    reg["antig_docente_anios"], reg["antig_docente_meses"] = tot // 12, tot % 12
        filas.append(reg)
    df = pd.DataFrame(filas)
    if df.empty:
        raise ValueError("El listado no tiene filas con legajo o CUIL.")
    if simple:
        hall.append(Hallazgo("ADVERTENCIA", "varios", "Antigüedad docente",
                             "El listado trae la antigüedad en años enteros (sin meses): se informa como antigüedad "
                             "docente con 00 meses. La antigüedad IPS y de otras cajas no se modifica."))
    if not con_antig and not simple:
        hall.append(Hallazgo("ADVERTENCIA", "varios", "Antigüedad docente",
                             "La antigüedad docente se calculó desde la fecha de antigüedad (o de ingreso) hasta el "
                             "último día del período (años y meses completos). Confirmá que coincida con SAP/IPS."))
    d = df[df["legajo"] != ""]["legajo"]
    for v in d[d.duplicated()].unique():
        hall.append(Hallazgo("ERROR", v, "legajo", "Aparece repetido en el listado de antigüedad."))
    d = df[df["legajo"] == ""]["cuil"]
    for v in d[d.duplicated()].unique():
        hall.append(Hallazgo("ERROR", v, "cuil", "CUIL repetido en el listado sin legajo: no se puede saber a cuál corresponde."))
    return df, hall


def aplicar_antiguedad(padron: pd.DataFrame, listado: pd.DataFrame, recibos: list[Recibo]) -> tuple[pd.DataFrame, list[Hallazgo], int]:
    """Pisa las antigüedades del padrón con las del listado (por legajo; si el listado no trae legajo, por CUIL,
    y entonces todos los legajos de esa persona reciben la misma antigüedad). Devuelve (padrón, hallazgos, nº de legajos)."""
    padron = padron.copy()
    cols = [c for c in NUMERICAS if c in listado.columns]
    por_leg = {r["legajo"]: r for r in listado.to_dict("records") if r["legajo"]}
    por_cuil = {r["cuil"]: r for r in listado.to_dict("records") if r["cuil"] and not r["legajo"]}
    hall, aplicados = [], 0
    sin = []
    for rec in recibos:
        fila = por_leg.get(rec.legajo) or por_cuil.get(rec.cuil)
        if fila is None:
            sin.append(rec.legajo)
            continue
        idx = padron.index[padron["legajo"] == rec.legajo]
        for c in cols:
            if c in fila and not pd.isna(fila[c]):
                padron.loc[idx, c] = fila[c]
        aplicados += 1
    if sin:
        hall.append(Hallazgo("ADVERTENCIA", "varios" if len(sin) > 1 else sin[0], "Antigüedad",
                             f"{len(sin)} legajo(s) del informe no están en el listado de antigüedad "
                             f"({', '.join(sin[:10])}{'…' if len(sin) > 10 else ''}); conservan los valores del padrón."))
    en_informe = {r.legajo for r in recibos}
    cuils = {r.cuil for r in recibos}
    extra = [l for l in por_leg if l not in en_informe] + [c for c in por_cuil if c not in cuils]
    if extra:
        hall.append(Hallazgo("INFO", "varios", "Antigüedad", f"{len(extra)} fila(s) del listado no corresponden a este informe."))
    return padron, hall, aplicados
