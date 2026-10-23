"""Armado del SALARIO.TXT (ancho fijo) y del ZIP que se sube a SAP.

Diseño (instructivo IPS, formato de 108 columnas = 107 caracteres por línea):
  1-7 código empleador | 8-14 período AAAA/MM | 15-16 nº liquidación | 17 tipo liquidación |
  18 tipo DDJJ | 19-29 CUIL | 30-33 cargo | 34-39 concepto IPS | 40-47 concepto empleador |
  48-50 tipo | 51-75 descripción | 76-85 importe | 86-97 antigüedades (6x2) | 98 'M' |
  99-101 días inasistencia | 102-104 días licencia s/goce | 105-106 encuadre | 107 modalidad.
Si algún importe necesita 12 posiciones (positivo de 12 dígitos o negativo de 11), TODAS las
líneas pasan al formato de 110 columnas (109 caracteres): el importe ocupa 76-87 y el resto
se corre dos posiciones.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from decimal import Decimal

import pandas as pd

from .transformador import Parametros, Registro

ANCHO_108, ANCHO_110 = 10, 12
LARGO_108, LARGO_110 = 107, 109


class DesbordeImporte(ValueError):
    pass


def ascii_mayus(texto: str, largo: int = 25) -> tuple[str, bool, bool]:
    """(texto normalizado y rellenado, fue_recortado, tenía_caracteres_no_ASCII)."""
    original = texto or ""
    sin_tildes = unicodedata.normalize("NFKD", original)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    cambio = sin_tildes != original
    limpio = re.sub(r"[^\x20-\x7E]", " ", sin_tildes).upper()
    limpio = re.sub(r"\s+", " ", limpio).strip()
    recortado = len(limpio) > largo
    return limpio[:largo].ljust(largo), recortado, cambio


def formatear_importe(valor: Decimal, ancho: int) -> str:
    s = format(valor, f"0{ancho}.2f")
    if len(s) > ancho:
        raise DesbordeImporte(f"El importe {valor} no entra en {ancho} posiciones")
    return s


def elegir_formato(registros: list[Registro]) -> int:
    """Ancho del campo importe: 10 (formato 108) o 12 (formato 110)."""
    try:
        for r in registros:
            formatear_importe(r.importe, ANCHO_108)
    except DesbordeImporte:
        return ANCHO_110
    return ANCHO_108


def codigo_dias(dias: Decimal) -> str:
    """Días con un decimal en 3 posiciones: 3 días = '030', 13,5 días = '135'."""
    return f"{min(int((Decimal(dias) * 10).to_integral_value()), 999):03d}"


def _dos(v) -> str:
    return f"{int(v):02d}"


def construir_linea(reg: Registro, p: Parametros, pad: dict, ancho: int) -> str:
    desc, _, _ = ascii_mayus(reg.descripcion)
    encuadre = str(pad["encuadre"]).strip()
    encuadre = "2 " if encuadre == "2" else encuadre.ljust(2)
    inasist = pad.get("dias_inasistencia", 0)
    inasist = Decimal(str(0 if pd.isna(inasist) else inasist))
    partes = [
        p.codigo_empleador.ljust(7)[:7],
        p.periodo,
        p.nro_liquidacion,
        p.tipo_liquidacion,
        p.tipo_ddjj,
        reg.cuil,
        f"{int(pad['nro_cargo']):04d}",
        f"{reg.concepto_ips:06d}",
        f"{reg.concepto_empleador:08d}",
        reg.tipo,
        desc,
        formatear_importe(reg.importe, ancho),
        _dos(pad["antig_admin_anios"]), _dos(pad["antig_admin_meses"]),
        _dos(pad["antig_otras_cajas_anios"]), _dos(pad["antig_otras_cajas_meses"]),
        _dos(pad["antig_docente_anios"]), _dos(pad["antig_docente_meses"]),
        "M",
        codigo_dias(inasist),
        codigo_dias(reg.dias_licencia),
        encuadre,
        str(pad["modalidad"]).strip().upper(),
    ]
    return "".join(partes)


def construir_txt(registros: list[Registro], p: Parametros, padron: pd.DataFrame) -> tuple[list[str], int]:
    """Devuelve (líneas, largo_esperado)."""
    ancho = elegir_formato(registros)
    por_legajo = {str(r["legajo"]): r for r in padron.to_dict("records")}
    lineas = [construir_linea(r, p, por_legajo[r.legajo], ancho) for r in registros]
    return lineas, (LARGO_108 if ancho == ANCHO_108 else LARGO_110)


def txt_bytes(lineas: list[str]) -> bytes:
    """Líneas separadas por CRLF, sin línea vacía final (como el ejemplo del instructivo)."""
    return "\r\n".join(lineas).encode("ascii")


def nombre_zip(p: Parametros) -> str:
    """Código_MMAAAA_<DDJJ><tipo liquidación>_<nº>.zip  (ej.: E060906_092026_ON_01.zip)."""
    anio, mes = p.periodo.split("/")
    return f"{p.codigo_empleador.strip()}_{mes}{anio}_{p.tipo_ddjj}{p.tipo_liquidacion}_{p.nro_liquidacion}.zip"


def crear_zip(lineas: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SALARIO.TXT", txt_bytes(lineas))
    return buf.getvalue()
