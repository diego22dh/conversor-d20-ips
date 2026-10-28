"""Lectura del informe "Recibos Agrupados" exportado desde Nacional Software.

Formato real observado (15 columnas, sin encabezados repetidos):
  - Una fila de cabecera por recibo con legajo, apellido y nombre, CUIL, período y
    totales (remunerativo, no remunerativo, bruto, descuento, neto) + el primer concepto.
  - Filas siguientes: un concepto por fila (columnas 9 a 14) sin datos de cabecera.
  - Al final, un bloque de totales por concepto (sin legajo) que NO es un recibo.
"""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .modelos import Hallazgo, Linea, Recibo, ResultadoLectura

COLUMNAS = ["legajo", "nombre", "cuil", "periodo", "rem", "norem", "bruto", "desc", "neto",
            "concepto", "descripcion", "unidad", "c_rem", "c_norem", "c_desc"]
CERO = Decimal("0.00")


def _dec(valor) -> Decimal | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, str):
        valor = valor.strip().replace(",", ".")
        if valor == "":
            return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"importe no numérico: {valor!r}")


def _vacio(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


def normalizar_cuil(valor) -> str:
    return re.sub(r"\D", "", str(valor)) if not _vacio(valor) else ""


def cuil_valido(cuil: str) -> bool:
    """Valida largo y dígito verificador (módulo 11)."""
    if len(cuil) != 11 or not cuil.isdigit():
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(a) * b for a, b in zip(cuil[:10], pesos))
    v = 11 - s % 11
    v = {11: 0, 10: 9}.get(v, v)
    return v == int(cuil[10])


def _legajo(v) -> str:
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def _periodo(valor) -> str:
    """'09/2026' -> '2026/09'."""
    s = str(valor).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(2)}/{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d{4})/(\d{1,2})", s)
    if m:
        return f"{m.group(1)}/{int(m.group(2)):02d}"
    raise ValueError(f"período con formato no reconocido: {s!r}")


def leer_excel(origen: str | Path | BinaryIO) -> pd.DataFrame:
    df = pd.read_excel(origen, header=None, dtype=object)
    if df.shape[1] < 15:
        raise ValueError(f"El archivo tiene {df.shape[1]} columnas y se esperaban 15. "
                         "¿Es el informe 'Recibos Agrupados por Empleado' de Nacional Software?")
    df = df.iloc[:, :15]
    df.columns = COLUMNAS
    enc = [str(x).strip().lower() for x in df.iloc[0, [0, 2, 3, 9, 10]]]
    if enc != ["legajo", "cuil", "período", "concepto", "descripción"]:
        raise ValueError("Los encabezados no coinciden con el informe 'Recibos Agrupados por Empleado' "
                         f"(se leyó {enc}).")
    return df.iloc[1:].reset_index(drop=True)


def _buscar_corte_totales(df: pd.DataFrame, ultimo_header: int) -> int | None:
    """Índice donde empieza el bloque de totales (o None).

    Se prueba cada fila posterior a la última cabecera: el bloque correcto es el que, al
    sumarlo por concepto, coincide exactamente con el detalle anterior.
    """
    n = len(df)

    def sumas(sub: pd.DataFrame) -> dict:
        acc: dict = defaultdict(lambda: [CERO, CERO, CERO])
        for r in sub.itertuples():
            try:
                c = int(float(r.concepto))
            except (TypeError, ValueError):
                return {}
            for i, col in enumerate(("c_rem", "c_norem", "c_desc")):
                v = _dec(getattr(r, col))
                if v is not None:
                    acc[c][i] += v
        return {k: tuple(v) for k, v in acc.items()}

    for i in range(ultimo_header + 2, n):
        cola = df.iloc[i:]
        if cola.legajo.notna().any():
            continue
        # El bloque de totales trae cada concepto una sola vez y en orden ascendente. Esto evita
        # adelantar el corte cuando el último recibo termina con líneas en cero (suman igual).
        try:
            codigos = [int(float(c)) for c in cola.concepto]
        except (TypeError, ValueError):
            continue
        if any(b <= a for a, b in zip(codigos, codigos[1:])):
            continue
        if sumas(df.iloc[:i]) == sumas(cola) and sumas(cola):
            return i
    return None


def leer_nacional(origen: str | Path | BinaryIO) -> ResultadoLectura:
    df = leer_excel(origen)
    hallazgos: list[Hallazgo] = []

    idx_headers = df.index[df.legajo.map(lambda v: not _vacio(v))].tolist()
    if not idx_headers:
        raise ValueError("No se encontraron recibos (filas con legajo) en el archivo.")
    corte = _buscar_corte_totales(df, idx_headers[-1])
    totales_control = None
    if corte is None:
        # No se corta nada "por las dudas": un corte equivocado descarta líneas reales del último recibo.
        hallazgos.append(Hallazgo("ADVERTENCIA", "", "Totales",
                                  "El informe no trae un bloque de totales por concepto que coincida con el detalle: "
                                  "no se hace el control cruzado contra ese bloque (sí se controla cada recibo contra "
                                  "sus propios totales)."))
    detalle = df.iloc[:corte] if corte is not None else df
    if corte is not None:
        cola = df.iloc[corte:]
        totales_control = {}
        for r in cola.itertuples():
            try:
                c = int(float(r.concepto))
            except (TypeError, ValueError):
                continue
            t = totales_control.setdefault(c, {"rem": CERO, "norem": CERO, "desc": CERO})
            for k, col in (("rem", "c_rem"), ("norem", "c_norem"), ("desc", "c_desc")):
                v = _dec(getattr(r, col))
                if v is not None:
                    t[k] += v
        hallazgos.append(Hallazgo("INFO", "", "Totales",
                                  f"Se excluyó el bloque final de totales por concepto ({len(cola)} filas) y se lo "
                                  "usa como control cruzado."))

    recibos: list[Recibo] = []
    actual: Recibo | None = None
    for fila in detalle.itertuples():
        if not _vacio(fila.legajo):
            try:
                actual = Recibo(
                    legajo=_legajo(fila.legajo),
                    nombre=str(fila.nombre).strip() if not _vacio(fila.nombre) else "",
                    cuil_original=str(fila.cuil).strip() if not _vacio(fila.cuil) else "",
                    cuil=normalizar_cuil(fila.cuil),
                    periodo=_periodo(fila.periodo),
                    rem=_dec(fila.rem) or CERO, norem=_dec(fila.norem) or CERO,
                    bruto=_dec(fila.bruto) or CERO, descuento=_dec(fila.desc) or CERO,
                    neto=_dec(fila.neto) or CERO,
                )
            except ValueError as e:
                hallazgos.append(Hallazgo("ERROR", _legajo(fila.legajo), "Cabecera", str(e)))
                actual = None
                continue
            recibos.append(actual)
        if actual is None or _vacio(fila.concepto):
            continue
        try:
            codigo = int(float(fila.concepto))
            importes = {k: _dec(getattr(fila, k)) for k in ("c_rem", "c_norem", "c_desc")}
        except ValueError as e:
            hallazgos.append(Hallazgo("ERROR", actual.legajo, f"Concepto {fila.concepto}", str(e)))
            continue
        con_valor = {k: v for k, v in importes.items() if v is not None}
        if len(con_valor) != 1:
            hallazgos.append(Hallazgo("ERROR", actual.legajo, f"Concepto {codigo}",
                                      f"La línea trae {len(con_valor)} importes (se espera exactamente 1)."))
            continue
        col, imp = next(iter(con_valor.items()))
        actual.lineas.append(Linea(
            concepto=codigo,
            descripcion="" if _vacio(fila.descripcion) else str(fila.descripcion).strip(),
            unidad=None if _vacio(fila.unidad) else str(fila.unidad).strip(),
            columna={"c_rem": "rem", "c_norem": "norem", "c_desc": "desc"}[col],
            importe=imp,
        ))
    return ResultadoLectura(recibos, totales_control, hallazgos)
