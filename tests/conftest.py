"""Fixtures: un informe de Nacional sintético (datos ficticios) con el mismo formato que el real."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ENCABEZADO = ["Legajo", "Apellido y Nombre", "CUIL", "Período", "Remunerativo", "No Remunerativo", "Sueldo Bruto",
              "Descuento", "Sueldo Neto", "Concepto", "Descripción", "Unidad", "Remunerativo", "No Remunerativo",
              "Descuento"]


def _cuil(base10: str) -> str:
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    v = 11 - sum(int(a) * b for a, b in zip(base10, pesos)) % 11
    return base10 + str({11: 0, 10: 9}.get(v, v))


CUIL_A = _cuil("2711111111")
CUIL_B = _cuil("2722222222")
CUIL_C = _cuil("2733333333")


def fila_cab(leg, nombre, cuil, rem, norem, desc, concepto, descr, unidad, c_rem, c_norem, c_desc):
    return [leg, nombre, cuil, "09/2026", rem, norem, rem + norem, desc, rem + norem - desc,
            concepto, descr, unidad, c_rem, c_norem, c_desc]


def fila_det(concepto, descr, unidad=None, c_rem=None, c_norem=None, c_desc=None):
    return [None] * 9 + [concepto, descr, unidad, c_rem, c_norem, c_desc]


def armar_informe(path: Path, con_totales: bool = True) -> Path:
    """Tres recibos:
       1001 (CUIL A): sueldo + SAC (con IPS 16% y OS 3% calculados sobre el total).
       1002 (CUIL B): licencia sin sueldo parcial (proporcional) y asignación familiar.
       1003 (CUIL C): licencia que compensa todo (neto 0), con descuentos en 0.
    """
    f = [ENCABEZADO]
    # 1001: base 100000 + SAC 10000 = 110000 -> IPS 17600.00, OS 3300.00
    f.append(fila_cab("1001", "PEREZ ANA", CUIL_A, 110000, 0, 20900, 11, "SUELDO BASICO", None, 100000, None, None))
    f.append(fila_det(101, "SAC DOC", None, 10000))
    f.append(fila_det(400, "IPS 16%", 16, None, None, 17600))
    f.append(fila_det(521, "OBRA SOCIAL 3%", 3, None, None, 3300))
    # 1002: 60000 + 40000 - licencia 20000 (de 100000) -> rem 80000; NR 5000; AFA 3000
    f.append(fila_cab("1002", "GOMEZ LUIS", "27-22222222-" + CUIL_B[-1], 80000, 8000, 15200,
                      11, "SUELDO BASICO", None, 60000, None, None))
    f.append(fila_det(14, "ANTIGUEDAD", 40, 40000))
    f.append(fila_det(35, "BONIF. NO REM COMP", None, None, 5000))
    f.append(fila_det(40, "SALARIO FAMILIAR", None, None, 3000))
    f.append(fila_det(141, "LICENCIA SIN SUELDO", 6, -20000))
    f.append(fila_det(400, "IPS 16%", 16, None, None, 12800))
    f.append(fila_det(521, "OBRA SOCIAL 3%", 3, None, None, 2400))
    # 1003: licencia total
    f.append(fila_cab("1003", "DIAZ SOL", CUIL_C, 0, 0, 0, 11, "SUELDO BASICO", None, 50000, None, None))
    f.append(fila_det(35, "BONIF. NO REM COMP", None, None, 5000))
    f.append(fila_det(141, "LICENCIA SIN SUELDO", 30, -50000))
    f.append(fila_det(142, "LICENCIA SIN SUELDO NR", None, None, -5000))
    f.append(fila_det(400, "IPS 16%", 16, None, None, 0))
    f.append(fila_det(521, "OBRA SOCIAL 3%", 3, None, None, 0))
    if con_totales:
        tot: dict = {}
        for r in f[1:]:
            if r[9] is None:
                continue
            t = tot.setdefault(r[9], [r[10], r[11], 0, 0, 0])
            for i, v in zip((2, 3, 4), (r[12], r[13], r[14])):
                if v is not None:
                    t[i] += v
        for c in sorted(tot):
            d, u, a, b, e = tot[c]
            f.append(fila_det(c, d, u, a or None, b or None, e or None))
    pd.DataFrame(f).to_excel(path, header=False, index=False)
    return path


@pytest.fixture
def informe(tmp_path):
    return armar_informe(tmp_path / "informe.xlsx")
