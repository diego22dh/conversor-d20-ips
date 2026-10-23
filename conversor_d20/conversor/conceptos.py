"""Correspondencia entre los códigos de liquidación del colegio (Nacional Software) y los
códigos del IPS/SAP (tipo de concepto y concepto IPS).

Cada colegio tiene sus propios códigos de liquidación, por eso el listado se guarda POR CÓDIGO
DE EMPLEADOR (data/conceptos/E060906.xlsx). Si el colegio no tiene uno guardado se usa el
listado predeterminado (data/conceptos_d20.xlsx) y la app lo avisa.

Columnas aceptadas (los encabezados se reconocen sin importar mayúsculas, tildes ni guiones):
  - Código de liquidación (obligatoria)   p. ej. "CONCEPTO EMPLEADOR", "CODIGO"
  - Tipo de concepto IPS (obligatoria)    RCA, RSA, AFA, DPS, DAS, DES
  - Concepto IPS / código SAP (obligatoria)  6 dígitos, p. ej. 100000
  - Descripción y Columna (opcionales)
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from . import config
from .modelos import Hallazgo, Recibo

ALIAS = {
    "codigo": {"CONCEPTO EMPLEADOR", "CODIGO", "CODIGO LIQUIDACION", "COD LIQUIDACION", "CODIGO CONCEPTO",
               "CODIGO NACIONAL", "CONCEPTO", "COD CONCEPTO", "CODIGO EMPLEADOR", "CODIGO DE LIQUIDACION"},
    "descripcion": {"DESCRIPCION DEL CONCEPTO", "DESCRIPCION", "DETALLE", "NOMBRE"},
    "columna": {"COLUMNA"},
    "tipo": {"TIPO DE CONCEPTO IPS", "TIPO CONCEPTO IPS", "TIPO DE CONCEPTO", "TIPO", "TIPO IPS", "TIPO CONCEPTO"},
    "ips": {"IPS", "SAP", "CONCEPTO IPS", "CODIGO IPS", "CODIGO SAP", "COD SAP", "COD IPS", "CONCEPTO SAP", "CODIGO IPS SAP",
            "CODIGO DE CONCEPTO IPS"},
}
OBLIGATORIAS = ("codigo", "tipo", "ips")
TIPOS_VALIDOS = {"RCA", "RSA", "AFA", "DAS", "DES", "DPS"}
ENCABEZADOS_ESTANDAR = {"codigo": "CONCEPTO EMPLEADOR", "descripcion": "DESCRIPCIÓN DEL CONCEPTO",
                        "columna": "Columna", "tipo": "TIPO DE CONCEPTO IPS", "ips": "CONCEPTO_IPS"}
COLUMNA_TEXTO = {"rem": "Remunerativo", "norem": "No Remunerativo", "desc": "Descuento"}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def _mapear_encabezados(fila) -> dict[str, int]:
    """Posición de cada columna lógica en una fila de encabezados."""
    mapa: dict[str, int] = {}
    for pos, valor in enumerate(fila):
        n = _norm(valor)
        for clave, alias in ALIAS.items():
            if n in alias and clave not in mapa:
                mapa[clave] = pos
    return mapa


def _entero(v) -> int | None:
    try:
        s = str(v).strip()
        if s == "" or s.lower() == "nan":
            return None
        return int(float(s))
    except ValueError:
        return None


def plantilla_correspondencia() -> pd.DataFrame:
    """Planilla de ejemplo para completar con los códigos de liquidación del colegio."""
    return pd.DataFrame([
        {"CONCEPTO EMPLEADOR": 11, "DESCRIPCIÓN DEL CONCEPTO": "SUELDO BASICO", "TIPO DE CONCEPTO IPS": "RCA", "CONCEPTO_IPS": 100000},
        {"CONCEPTO EMPLEADOR": 14, "DESCRIPCIÓN DEL CONCEPTO": "ANTIGUEDAD", "TIPO DE CONCEPTO IPS": "RCA", "CONCEPTO_IPS": 100001},
        {"CONCEPTO EMPLEADOR": 35, "DESCRIPCIÓN DEL CONCEPTO": "BONIF. NO REMUNERATIVA", "TIPO DE CONCEPTO IPS": "RSA", "CONCEPTO_IPS": 100000},
        {"CONCEPTO EMPLEADOR": 400, "DESCRIPCIÓN DEL CONCEPTO": "IPS 16%", "TIPO DE CONCEPTO IPS": "DPS", "CONCEPTO_IPS": 500001},
        {"CONCEPTO EMPLEADOR": 521, "DESCRIPCIÓN DEL CONCEPTO": "OBRA SOCIAL 3%", "TIPO DE CONCEPTO IPS": "DAS", "CONCEPTO_IPS": 700000},
    ])


def cargar_conceptos(origen: str | Path | BinaryIO | None = None) -> tuple[pd.DataFrame, list[Hallazgo]]:
    """Lee una correspondencia de conceptos. Lanza ValueError si falta una columna obligatoria.

    Devuelve (tabla, hallazgos). La tabla tiene: codigo, descripcion, columna, tipo, tipo_original, ips.
    """
    origen = origen or config.CONCEPTOS_XLSX
    crudo = pd.read_excel(origen, header=None, dtype=object)
    fila_enc, mapa = None, {}
    for i in range(min(10, len(crudo))):
        m = _mapear_encabezados(crudo.iloc[i].tolist())
        if all(k in m for k in OBLIGATORIAS):
            fila_enc, mapa = i, m
            break
    if fila_enc is None:
        mejor = max((_mapear_encabezados(crudo.iloc[i].tolist()) for i in range(min(10, len(crudo)))),
                    key=len, default={})
        faltan = {"codigo": "código de liquidación", "tipo": "tipo de concepto IPS", "ips": "concepto IPS / código SAP"}
        raise ValueError("Al listado le faltan columnas obligatorias: "
                         + ", ".join(faltan[k] for k in OBLIGATORIAS if k not in mejor)
                         + ". Usá la planilla de ejemplo (botón «Descargar planilla de ejemplo»).")

    hall: list[Hallazgo] = []
    filas = []
    for n, fila in enumerate(crudo.iloc[fila_enc + 1:].itertuples(index=False), start=fila_enc + 2):
        v = list(fila)
        if all(pd.isna(x) for x in v):
            continue
        codigo, ips = _entero(v[mapa["codigo"]]), _entero(v[mapa["ips"]])
        tipo = str(v[mapa["tipo"]]).strip().upper()
        if codigo is None:
            hall.append(Hallazgo("ERROR", "", f"Listado fila {n}", "El código de liquidación no es numérico."))
            continue
        if ips is None:
            hall.append(Hallazgo("ERROR", "", f"Concepto {codigo}", "El concepto IPS / código SAP no es numérico."))
            continue
        filas.append({
            "codigo": codigo,
            "descripcion": "" if "descripcion" not in mapa or pd.isna(v[mapa["descripcion"]]) else str(v[mapa["descripcion"]]).strip(),
            "columna": "" if "columna" not in mapa or pd.isna(v[mapa["columna"]]) else str(v[mapa["columna"]]).strip(),
            "tipo": tipo, "tipo_original": tipo, "ips": ips,
        })
    if not filas:
        raise ValueError("El listado no tiene ninguna fila de conceptos.")
    df = pd.DataFrame(filas)

    # Obra social: por código IPS, no por código de liquidación (cambia según el colegio)
    m = (df["tipo"] == "DES") & (df["ips"] == config.IPS_OBRA_SOCIAL)
    if m.any():
        df.loc[m, "tipo"] = "DAS"
        hall.append(Hallazgo("INFO", "", "Conceptos",
                             "Obra social (códigos " + ", ".join(str(c) for c in df.loc[m, "codigo"])
                             + f", IPS {config.IPS_OBRA_SOCIAL}) informada como DAS según el instructivo "
                             "(el listado la trae como DES)."))
    # Repetidos
    for cod, g in df[df.duplicated("codigo", keep=False)].groupby("codigo"):
        if g[["tipo", "ips"]].drop_duplicates().shape[0] > 1:
            hall.append(Hallazgo("ERROR", "", f"Concepto {cod}",
                                 "Código repetido en el listado con tipo o concepto IPS distintos."))
    df = df.drop_duplicates("codigo", keep="first").reset_index(drop=True)

    for r in df[~df["tipo"].isin(TIPOS_VALIDOS)].itertuples():
        hall.append(Hallazgo("ERROR", "", f"Concepto {r.codigo}",
                             f"Tipo de concepto inválido: {r.tipo!r} (válidos: {', '.join(sorted(TIPOS_VALIDOS))})."))
    # Códigos IPS fuera del instructivo y tipos incoherentes con el código IPS (advertencias agrupadas)
    raros = df[~df["ips"].isin(config.CODIGOS_IPS_VALIDOS)]
    if len(raros):
        hall.append(Hallazgo("ADVERTENCIA", "", "Concepto IPS",
                             "Códigos IPS que no figuran en el instructivo: "
                             + ", ".join(f"{r.codigo}→{r.ips}" for r in raros.itertuples())))
    esperado = {"RCA": "1", "RSA": "1", "AFA": "2", "DPS": "5"}
    incoh = [f"{r.codigo} ({r.tipo}→{r.ips})" for r in df.itertuples()
             if r.tipo in esperado and r.ips in config.CODIGOS_IPS_VALIDOS and str(r.ips)[0] != esperado[r.tipo]]
    if incoh:
        hall.append(Hallazgo("ADVERTENCIA", "", "Tipo vs concepto IPS",
                             "El tipo no es coherente con el concepto IPS en: " + ", ".join(incoh)))
    return df, hall


def ruta_empleador(codigo: str) -> Path:
    return config.CONCEPTOS_DIR / f"{codigo.strip().upper()}.xlsx"


def origen_para_empleador(codigo: str) -> tuple[Path, bool]:
    """(ruta del listado a usar, ¿es propio del colegio?)."""
    propio = ruta_empleador(codigo)
    return (propio, True) if propio.exists() else (config.CONCEPTOS_XLSX, False)


def guardar_conceptos_empleador(codigo: str, df: pd.DataFrame) -> Path:
    """Guarda el listado del colegio con encabezados estándar (con el tipo ORIGINAL del archivo)."""
    destino = ruta_empleador(codigo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame({
        ENCABEZADOS_ESTANDAR["codigo"]: df["codigo"],
        ENCABEZADOS_ESTANDAR["descripcion"]: df["descripcion"],
        ENCABEZADOS_ESTANDAR["columna"]: df["columna"],
        ENCABEZADOS_ESTANDAR["tipo"]: df["tipo_original"],
        ENCABEZADOS_ESTANDAR["ips"]: df["ips"],
    })
    out.to_excel(destino, index=False)
    return destino


def aplicar_conceptos(recibos: list[Recibo], conceptos: pd.DataFrame) -> list[Hallazgo]:
    """Completa tipo y código IPS de cada línea; marca conceptos desconocidos o inconsistentes."""
    mapa = {r.codigo: r for r in conceptos.itertuples()}
    hall: list[Hallazgo] = []
    for rec in recibos:
        for ln in rec.lineas:
            c = mapa.get(ln.concepto)
            if c is None:
                hall.append(Hallazgo("ERROR", rec.legajo, f"Concepto {ln.concepto}",
                                     f"'{ln.descripcion}' no figura en el listado de conceptos del colegio."))
                continue
            ln.tipo, ln.concepto_ips = c.tipo, c.ips
            esperada = config.COLUMNA_POR_TIPO.get(c.tipo)
            if esperada and ln.columna != esperada:
                hall.append(Hallazgo("ERROR", rec.legajo, f"Concepto {ln.concepto}",
                                     f"El informe lo trae en la columna '{ln.columna}' pero el listado lo define "
                                     f"como {c.tipo} (columna '{esperada}')."))
    return hall


def conceptos_sin_correspondencia(recibos: list[Recibo], conceptos: pd.DataFrame) -> pd.DataFrame:
    """Conceptos usados en el informe que el listado no cubre (para avisar antes de procesar)."""
    conocidos = set(conceptos["codigo"])
    filas: dict[int, dict] = {}
    for r in recibos:
        for l in r.lineas:
            if l.concepto not in conocidos:
                f = filas.setdefault(l.concepto, {"Código": l.concepto, "Descripción en el informe": l.descripcion, "Legajos": set()})
                f["Legajos"].add(r.legajo)
    return pd.DataFrame([{**f, "Legajos": len(f["Legajos"])} for f in filas.values()],
                        columns=["Código", "Descripción en el informe", "Legajos"])
