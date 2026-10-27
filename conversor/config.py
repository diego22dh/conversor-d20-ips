"""Configuración y constantes del conversor Nacional Software -> D20 Digital IPS."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PARAMETROS_JSON = DATA_DIR / "parametros.json"
PADRON_XLSX = DATA_DIR / "padron_agentes.xlsx"
CONCEPTOS_XLSX = DATA_DIR / "conceptos_d20.xlsx"

# ---------------------------------------------------------------------------
# Opciones de los desplegables (instructivo IPS, sección "Proceso de armado")
# ---------------------------------------------------------------------------
CODIGOS_EMPLEADOR_DEFAULT = ["E060906"]
TIPOS_LIQUIDACION = {
    "N": "N – Normal",
    "A": "A – Adicional (solo SAC)",
}
TIPOS_DDJJ = {
    "O": "O – Original",
    "R": "R – Rectificativa",
    "S": "S – Rectificativa",
    "T": "T – Rectificativa",
    "U": "U – Rectificativa",
    "V": "V – Rectificativa",
    "W": "W – Rectificativa",
    "X": "X – Rectificativa",
    "Y": "Y – Rectificativa",
    "Z": "Z – Rectificativa",
}
NUMEROS_LIQUIDACION = [f"{n:02d}" for n in range(1, 21)]

# ---------------------------------------------------------------------------
# Reglas confirmadas con el usuario
# ---------------------------------------------------------------------------
# Obra social (3%): según el instructivo es tipo DAS. Algunos listados la traen como DES con
# concepto IPS 700000. La regla se aplica por CÓDIGO IPS (no por código de liquidación), porque
# los códigos de liquidación cambian de un colegio a otro.
IPS_OBRA_SOCIAL = 700000
ANTIGUEDAD_DIR = DATA_DIR / "antiguedad"        # listado de fechas de antigüedad por colegio
CONCEPTOS_DIR = DATA_DIR / "conceptos"          # un listado por colegio: <código de empleador>.xlsx

# Códigos IPS válidos según el instructivo (para advertir sobre códigos desconocidos).
CODIGOS_IPS_VALIDOS = (set(range(100000, 100049)) | set(range(200000, 200009)) | {500000, 500001}
                       | {600000, 700000} | set(range(800000, 800007)))

# Concepto LIQ: según el instructivo, concepto IPS 100047.
LIQ_CONCEPTO_IPS = 100047
LIQ_CONCEPTO_EMPLEADOR_DEFAULT = 9999  # código propio del empleador, editable en la app
LIQ_DESCRIPCION = "LIQUIDO"

# SAC: va en una liquidación aparte (tipo A). Códigos de concepto de Nacional.
CONCEPTOS_SAC_DEFAULT = [100, 101, 103, 860]
# Licencia sin goce de haberes: conceptos cuya "unidad" son los días.
CONCEPTOS_LICENCIA_DEFAULT = [141, 143, 144]

# Valores de prueba para el padrón (hasta que se carguen los reales).
CARGO_PRUEBA_INICIAL = 9001
ENCUADRE_PRUEBA = "13"
MODALIDAD_PRUEBA = "P"

ENCUADRES = {"13": "13 – Docente frente a grado", "2": "2 – Docente (cargos jerárquicos)"}
MODALIDADES = {"P": "P – Titular", "T": "T – Provisional", "R": "R – Suplente"}

# Tolerancia del instructivo: LIQ = RCA+RSA-DES-DPS-DAS con +/- 0,50
TOLERANCIA_LIQ = 0.50

# Mapa tipo de concepto -> columna del informe de Nacional que debe traer el importe
COLUMNA_POR_TIPO = {
    "RCA": "rem",
    "RSA": "norem",
    "AFA": "norem",
    "DPS": "desc",
    "DES": "desc",
    "DAS": "desc",
}


def periodos_disponibles(hoy: date | None = None, meses: int = 36) -> list[str]:
    """Períodos AAAA/MM desde hace `meses` hasta el mes actual (no puede ser posterior)."""
    hoy = hoy or date.today()
    y, m = hoy.year, hoy.month
    out = []
    for _ in range(meses):
        out.append(f"{y:04d}/{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out


def cargar_parametros() -> dict:
    base = {"codigos_empleador": list(CODIGOS_EMPLEADOR_DEFAULT), "empleadores": {}}
    try:
        if PARAMETROS_JSON.exists():
            base.update(json.loads(PARAMETROS_JSON.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return base


def guardar_parametros(par: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PARAMETROS_JSON.write_text(json.dumps(par, ensure_ascii=False, indent=2), encoding="utf-8")


def config_empleador(par: dict, codigo: str) -> dict:
    """Parámetros guardados para un colegio (concepto LIQ, conceptos de SAC y de licencia)."""
    e = par.get("empleadores", {}).get(codigo, {})
    return {
        "liq_empleador": int(e.get("liq_empleador", LIQ_CONCEPTO_EMPLEADOR_DEFAULT)),
        "conceptos_sac": list(e.get("conceptos_sac", CONCEPTOS_SAC_DEFAULT)),
        "conceptos_licencia": list(e.get("conceptos_licencia", CONCEPTOS_LICENCIA_DEFAULT)),
    }
