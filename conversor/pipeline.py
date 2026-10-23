"""Orquesta lectura -> conceptos -> padrón -> transformación -> validación -> TXT."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from . import config, escritor
from .conceptos import aplicar_conceptos, cargar_conceptos
from .lector import leer_nacional
from .modelos import Hallazgo, Recibo
from .padron import completar_padron
from .transformador import Parametros, Registro, transformar
from .validador import (validar_padron, validar_parametros, validar_recibos, validar_resultado,
                        validar_totales)


@dataclass
class Resultado:
    recibos: list[Recibo]
    padron: pd.DataFrame
    registros: list[Registro]
    lineas_txt: list[str]
    largo_linea: int
    hallazgos: list[Hallazgo]
    ajustes: pd.DataFrame
    control: pd.DataFrame
    vista: pd.DataFrame
    resumen: dict = field(default_factory=dict)

    @property
    def errores(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.nivel == "ERROR"]

    @property
    def advertencias(self) -> list[Hallazgo]:
        return [h for h in self.hallazgos if h.nivel == "ADVERTENCIA"]

    @property
    def puede_generar(self) -> bool:
        return not self.errores and bool(self.lineas_txt)

    def tabla_hallazgos(self) -> pd.DataFrame:
        orden = {"ERROR": 0, "ADVERTENCIA": 1, "INFO": 2}
        df = pd.DataFrame([h.fila() for h in self.hallazgos], columns=["Nivel", "Legajo", "Campo", "Detalle"])
        return df.sort_values("Nivel", key=lambda s: s.map(orden), kind="stable").reset_index(drop=True)


def _vista(registros: list[Registro], lineas: list[str], recibos: list[Recibo]) -> pd.DataFrame:
    nombres = {r.legajo: r.nombre for r in recibos}
    filas = []
    for r, ln in zip(registros, lineas):
        filas.append({
            "Legajo": r.legajo, "Apellido y nombre": nombres.get(r.legajo, ""), "CUIL": r.cuil,
            "Cargo": ln[29:33], "Concepto IPS": ln[33:39], "Concepto empleador": ln[39:47], "Tipo": ln[47:50],
            "Descripción": ln[50:75].rstrip(), "Importe": float(r.importe),
            "Inasist.": ln[-9:-6], "Lic. s/goce": ln[-6:-3], "Línea": ln,
        })
    return pd.DataFrame(filas)


def procesar(origen: str | Path | BinaryIO, p: Parametros, padron: pd.DataFrame | None = None,
             conceptos_origen=None, hoy: date | None = None) -> Resultado:
    lectura = leer_nacional(origen)
    hall: list[Hallazgo] = list(lectura.hallazgos)
    conceptos, h_conc = cargar_conceptos(conceptos_origen)
    hall += h_conc
    hall += aplicar_conceptos(lectura.recibos, conceptos)
    padron_ok = completar_padron(lectura.recibos, padron)

    hall += validar_parametros(p, lectura.recibos, hoy)
    hall += validar_recibos(lectura.recibos)
    hall += validar_padron(padron_ok, lectura.recibos)
    hall += validar_totales(lectura.recibos, lectura.totales_control)

    if p.tipo_liquidacion == "A" and not any(l.concepto in p.conceptos_sac for r in lectura.recibos for l in r.lineas):
        hall.append(Hallazgo("ERROR", "", "SAC", "Se pidió una liquidación adicional (SAC) pero el informe no tiene conceptos de SAC."))

    liq = transformar(lectura.recibos, p)
    hall += liq.hallazgos

    lineas: list[str] = []
    largo = escritor.LARGO_108
    errores_previos = any(h.nivel == "ERROR" for h in hall)
    if liq.registros and not errores_previos:
        try:
            lineas, largo = escritor.construir_txt(liq.registros, p, padron_ok)
        except Exception as e:  # defensa: nunca generar un archivo a medias
            hall.append(Hallazgo("ERROR", "", "Armado del TXT", str(e)))
            lineas = []
        if lineas:
            if largo == escritor.LARGO_110:
                hall.append(Hallazgo("INFO", "", "Formato",
                                     "Algún importe necesita 12 posiciones: se usa el formato de 110 columnas "
                                     "(109 caracteres) en todas las líneas."))
            else:
                hall.append(Hallazgo("INFO", "", "Formato", "Formato de 108 columnas (107 caracteres por línea)."))
            recortes: dict[int, tuple[str, set]] = {}
            for r in liq.registros:
                _, recortado, _ = escritor.ascii_mayus(r.descripcion)
                if recortado:
                    recortes.setdefault(r.concepto_empleador, (r.descripcion, set()))[1].add(r.legajo)
            for cod, (desc, legs) in sorted(recortes.items()):
                recortada = escritor.ascii_mayus(desc)[0].rstrip()
                hall.append(Hallazgo("ADVERTENCIA", "varios" if len(legs) > 1 else next(iter(legs)),
                                     f"Concepto {cod}",
                                     f"La descripción '{desc}' supera 25 posiciones y se informa como '{recortada}' "
                                     f"({len(legs)} legajo(s))."))
            hall += validar_resultado(liq.registros, lineas, largo, liq.control, p)
    elif liq.registros:
        # igual validamos lo que se pueda (fórmula LIQ y control) para informar todo junto
        hall += validar_resultado(liq.registros, ["x" * largo] * len(liq.registros), largo, liq.control, p)

    ajustes = pd.DataFrame(liq.ajustes, columns=["Legajo", "Nombre", "Concepto", "Descripción", "Motivo",
                                                 "Importe original", "Ajuste", "Importe final"])
    control = pd.DataFrame(liq.control)
    for df in (ajustes, control):
        for c in df.columns:
            if df[c].map(lambda v: isinstance(v, Decimal)).any():
                df[c] = df[c].map(lambda v: float(v) if isinstance(v, Decimal) else v)

    res = Resultado(lectura.recibos, padron_ok, liq.registros, lineas, largo, hall, ajustes, control,
                    _vista(liq.registros, lineas, lectura.recibos) if lineas else pd.DataFrame())
    legajos_con_error = {h.legajo for h in hall if h.nivel == "ERROR" and h.legajo}
    legajos_en_salida = {r.legajo for r in liq.registros}
    # los errores de legajos múltiples ("1511, 1004") cuentan para cada uno
    con_error = set()
    for texto in legajos_con_error:
        con_error |= {x.strip() for x in texto.split(",")}
    res.resumen = {
        "recibos_leidos": len(lectura.recibos),
        "registros_generados": len(liq.registros),
        "legajos_en_liquidacion": len(legajos_en_salida),
        "legajos_con_errores": len(con_error & {r.legajo for r in lectura.recibos}),
        "legajos_validos": len({r.legajo for r in lectura.recibos} - con_error),
        "errores": len(res.errores),
        "advertencias": len(res.advertencias),
        "total_liq": float(sum((r.importe for r in liq.registros if r.tipo == "LIQ"), Decimal("0"))),
        "formato": "110 columnas" if largo == escritor.LARGO_110 else "108 columnas",
    }
    return res
