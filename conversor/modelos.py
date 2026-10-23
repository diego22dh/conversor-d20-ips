"""Estructuras de datos compartidas."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Linea:
    """Un concepto de un recibo (legajo)."""
    concepto: int
    descripcion: str
    unidad: str | None
    columna: str            # "rem" | "norem" | "desc" (columna del informe de origen)
    importe: Decimal
    # se completan al cruzar con el listado de conceptos
    tipo: str | None = None
    concepto_ips: int | None = None
    origen: str = "export"  # "export" | "neteo" | "sac" | "liq"


@dataclass
class Recibo:
    legajo: str
    nombre: str
    cuil_original: str
    cuil: str
    periodo: str            # AAAA/MM
    rem: Decimal
    norem: Decimal
    bruto: Decimal
    descuento: Decimal
    neto: Decimal
    lineas: list[Linea] = field(default_factory=list)


@dataclass
class Hallazgo:
    nivel: str              # "ERROR" | "ADVERTENCIA" | "INFO"
    legajo: str
    campo: str
    mensaje: str

    def fila(self) -> dict:
        return {"Nivel": self.nivel, "Legajo": self.legajo, "Campo": self.campo, "Detalle": self.mensaje}


@dataclass
class ResultadoLectura:
    recibos: list[Recibo]
    totales_control: dict[int, dict[str, Decimal]] | None
    hallazgos: list[Hallazgo]
