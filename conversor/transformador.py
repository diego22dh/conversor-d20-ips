"""Reglas de transformación Nacional -> D20 (confirmadas con el usuario).

1. Licencia sin sueldo: se NETEA. Los importes negativos se descuentan de los conceptos
   positivos del mismo tipo (RCA con RCA, RSA con RSA), en forma proporcional, y los días
   de licencia se informan en el campo "días de licencia sin goce de haberes".
2. Los conceptos en cero se omiten (el instructivo exige importes > 0, salvo LIQ).
3. SAC: va en una liquidación aparte (tipo A). Los descuentos que el informe calcula sobre
   el total (sueldo + SAC) se separan usando la tasa de cada descuento (columna "unidad").
4. LIQ = RCA + RSA - DES - DPS - DAS (fórmula del instructivo, tolerancia +/- 0,50).
"""
from __future__ import annotations

from copy import copy
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import config
from .modelos import Hallazgo, Linea, Recibo

CENT = Decimal("0.01")
CERO = Decimal("0.00")
DEDUCCIONES = ("DPS", "DES", "DAS")


@dataclass
class Parametros:
    codigo_empleador: str
    periodo: str                     # AAAA/MM
    tipo_liquidacion: str = "N"      # N | A
    tipo_ddjj: str = "O"
    nro_liquidacion: str = "01"
    concepto_liq_empleador: int = config.LIQ_CONCEPTO_EMPLEADOR_DEFAULT
    incluir_afa_en_liq: bool = False
    conceptos_sac: list[int] = field(default_factory=lambda: list(config.CONCEPTOS_SAC_DEFAULT))
    conceptos_licencia: list[int] = field(default_factory=lambda: list(config.CONCEPTOS_LICENCIA_DEFAULT))


@dataclass
class Registro:
    """Una línea del SALARIO.TXT, antes de darle formato."""
    legajo: str
    cuil: str
    concepto_ips: int
    concepto_empleador: int
    tipo: str
    descripcion: str
    importe: Decimal
    dias_licencia: Decimal = CERO


@dataclass
class Liquidacion:
    registros: list[Registro]
    ajustes: list[dict]
    control: list[dict]
    hallazgos: list[Hallazgo]


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _repartir(total: Decimal, pesos: list[Decimal]) -> list[Decimal]:
    """Reparte `total` proporcionalmente a `pesos` en centavos exactos (mayor resto)."""
    tc = int((total * 100).to_integral_value())
    pc = [int((p * 100).to_integral_value()) for p in pesos]
    suma = sum(pc)
    base = [tc * p // suma for p in pc]
    resto = tc - sum(base)
    orden = sorted(range(len(pc)), key=lambda i: (tc * pc[i]) % suma, reverse=True)
    for i in orden[:resto]:
        base[i] += 1
    return [Decimal(b) / 100 for b in base]


def _tasa(unidad: str | None) -> Decimal | None:
    try:
        return Decimal(str(unidad).replace(",", ".")) if unidad not in (None, "") else None
    except Exception:
        return None


def netear_licencia(rec: Recibo, p: Parametros, hall: list[Hallazgo], ajustes: list[dict]) -> tuple[list[Linea], Decimal]:
    """Devuelve (líneas ya neteadas, días de licencia sin goce)."""
    lineas = [copy(l) for l in rec.lineas]
    dias = CERO
    for l in lineas:
        if l.concepto in p.conceptos_licencia:
            t = _tasa(l.unidad)
            if t is None:
                hall.append(Hallazgo("ADVERTENCIA", rec.legajo, f"Concepto {l.concepto}",
                                     "Licencia sin goce sin cantidad de días en 'unidad': se informa 000 días."))
            else:
                dias += t
    resultado = list(lineas)
    for neg in [l for l in lineas if l.importe < 0]:
        if neg.tipo not in ("RCA", "RSA"):
            hall.append(Hallazgo("ERROR", rec.legajo, f"Concepto {neg.concepto}",
                                 f"Importe negativo ({neg.importe}) en un concepto {neg.tipo}: no se puede netear."))
            continue
        a_restar = -neg.importe
        objetivo = [l for l in resultado if l.tipo == neg.tipo and l.importe > 0 and l.concepto not in p.conceptos_sac]
        total = sum((l.importe for l in objetivo), CERO)
        if a_restar > total:
            hall.append(Hallazgo("ERROR", rec.legajo, f"Concepto {neg.concepto}",
                                 f"El descuento de {a_restar} supera los conceptos {neg.tipo} positivos ({total}): no se puede netear."))
            continue
        partes = _repartir(a_restar, [l.importe for l in objetivo])
        for l, parte in zip(objetivo, partes):
            if parte:
                ajustes.append({"Legajo": rec.legajo, "Nombre": rec.nombre, "Concepto": l.concepto,
                                "Descripción": l.descripcion, "Motivo": f"Neteo de {neg.concepto} {neg.descripcion}",
                                "Importe original": l.importe, "Ajuste": -parte, "Importe final": l.importe - parte})
            l.importe -= parte
            l.origen = "neteo"
        resultado.remove(neg)
        if a_restar == total:
            hall.append(Hallazgo("INFO", rec.legajo, f"Concepto {neg.concepto}",
                                 f"Licencia sin sueldo neteada: compensa exactamente los conceptos {neg.tipo} "
                                 f"({a_restar}); {int(dias)} días informados como licencia."))
        else:
            hall.append(Hallazgo("ADVERTENCIA", rec.legajo, f"Concepto {neg.concepto}",
                                 f"Licencia sin sueldo ({a_restar}) neteada en forma PROPORCIONAL contra {len(objetivo)} "
                                 f"conceptos {neg.tipo} (suman {total}). Revisar la distribución en la hoja de ajustes."))
    return resultado, dias


def separar_sac(rec: Recibo, lineas: list[Linea], p: Parametros, hall: list[Hallazgo], ajustes: list[dict]
                ) -> tuple[list[Linea], list[Linea]]:
    """Separa las líneas en (liquidación normal, liquidación SAC)."""
    sac = [l for l in lineas if l.concepto in p.conceptos_sac]
    if not sac:
        return lineas, []
    sac_rem = sum((l.importe for l in sac if l.tipo == "RCA"), CERO)
    base = sum((l.importe for l in lineas if l.tipo == "RCA"), CERO)
    normal: list[Linea] = []
    adicional: list[Linea] = [copy(l) for l in sac]
    for l in lineas:
        if l.concepto in p.conceptos_sac:
            continue
        if l.tipo not in DEDUCCIONES:
            normal.append(l)
            continue
        tasa = _tasa(l.unidad)
        if tasa is not None and base and abs(q(base * tasa / 100) - l.importe) <= Decimal("0.05"):
            parte_sac = q(sac_rem * tasa / 100)
            metodo = f"tasa {tasa}% sobre el SAC"
        else:
            parte_sac = q(l.importe * sac_rem / base) if base else CERO
            metodo = "proporción de la base remunerativa"
            hall.append(Hallazgo("ADVERTENCIA", rec.legajo, f"Concepto {l.concepto}",
                                 f"El descuento {l.descripcion} no responde exactamente a su tasa; se separó el SAC "
                                 "en proporción a la base remunerativa. Revisar."))
        parte_sac = min(max(parte_sac, CERO), l.importe)
        n = copy(l)
        n.importe = l.importe - parte_sac
        s = copy(l)
        s.importe, s.origen = parte_sac, "sac"
        normal.append(n)
        adicional.append(s)
        ajustes.append({"Legajo": rec.legajo, "Nombre": rec.nombre, "Concepto": l.concepto,
                        "Descripción": l.descripcion, "Motivo": f"Separación SAC ({metodo})",
                        "Importe original": l.importe, "Ajuste": -parte_sac, "Importe final": n.importe})
    return normal, adicional


def _quitar_ceros(rec: Recibo, lineas: list[Linea], hall: list[Hallazgo]) -> list[Linea]:
    ceros = [l for l in lineas if l.importe == 0]
    if ceros:
        hall.append(Hallazgo("INFO", rec.legajo, "Importes en cero",
                             "Se omitieron conceptos en cero (el instructivo exige importes > 0): "
                             + ", ".join(f"{l.concepto} {l.descripcion}" for l in ceros)))
    return [l for l in lineas if l.importe != 0]


def calcular_liq(lineas: list[Linea], incluir_afa: bool) -> Decimal:
    liq = CERO
    for l in lineas:
        if l.tipo in ("RCA", "RSA"):
            liq += l.importe
        elif l.tipo == "AFA" and incluir_afa:
            liq += l.importe
        elif l.tipo in DEDUCCIONES:
            liq -= l.importe
    return q(liq)


def _es_normal(l: Linea, p: Parametros) -> bool:
    return l.concepto not in p.conceptos_sac and l.tipo not in DEDUCCIONES


def transformar(recibos: list[Recibo], p: Parametros) -> Liquidacion:
    """Arma los registros de la liquidación pedida (N o A) y el control contra Nacional."""
    hall: list[Hallazgo] = []
    ajustes: list[dict] = []
    registros: list[Registro] = []
    control: list[dict] = []
    for rec in recibos:
        if any(l.tipo is None for l in rec.lineas):
            continue  # concepto desconocido: ya informado como error
        lineas, dias = netear_licencia(rec, p, hall, ajustes)
        normal, adicional = separar_sac(rec, lineas, p, hall, ajustes)

        en_n = any(_es_normal(l, p) for l in normal)
        en_a = bool(adicional)
        # LIQ de ambas liquidaciones (para el control cruzado)
        liq_n = calcular_liq(_quitar_ceros_silencioso(normal), p.incluir_afa_en_liq) if en_n else CERO
        liq_a = calcular_liq(_quitar_ceros_silencioso(adicional), p.incluir_afa_en_liq) if en_a else CERO
        afa_fuera = CERO if p.incluir_afa_en_liq else sum((l.importe for l in normal if l.tipo == "AFA"), CERO)
        control.append({
            "Legajo": rec.legajo, "Nombre": rec.nombre,
            "Neto Nacional": rec.neto, "LIQ normal": liq_n, "LIQ SAC": liq_a,
            "AFA fuera de LIQ": afa_fuera,
            "Diferencia": q(rec.neto - (liq_n + liq_a + afa_fuera)),
        })

        if p.tipo_liquidacion == "N":
            lineas_sel, incluido = normal, en_n
            if en_a:
                hall.append(Hallazgo("INFO", rec.legajo, "SAC",
                                     "Los conceptos de SAC y sus descuentos van en la liquidación tipo A (aparte)."))
        else:
            lineas_sel, incluido = adicional, en_a
        if not incluido:
            continue
        lineas_sel = _quitar_ceros(rec, lineas_sel, hall)
        afa = [l for l in lineas_sel if l.tipo == "AFA"]
        if afa and not p.incluir_afa_en_liq:
            hall.append(Hallazgo("ADVERTENCIA", rec.legajo, "Asignaciones familiares",
                                 "Las asignaciones familiares (AFA) se informan pero no integran LIQ, según la "
                                 "fórmula del instructivo."))
        for l in lineas_sel:
            registros.append(Registro(rec.legajo, rec.cuil, l.concepto_ips, l.concepto, l.tipo, l.descripcion,
                                      l.importe, dias))
        liq = calcular_liq(lineas_sel, p.incluir_afa_en_liq)
        if liq < 0:
            hall.append(Hallazgo("ERROR", rec.legajo, "LIQ", f"El líquido calculado es negativo ({liq})."))
        if not lineas_sel:
            hall.append(Hallazgo("ADVERTENCIA", rec.legajo, "LIQ",
                                 "El cargo queda solo con la línea LIQ en 0,00 (sin conceptos). Verificar con SAP."))
        registros.append(Registro(rec.legajo, rec.cuil, config.LIQ_CONCEPTO_IPS, p.concepto_liq_empleador, "LIQ",
                                  config.LIQ_DESCRIPCION, liq, dias))
    return Liquidacion(registros, ajustes, control, hall)


def _quitar_ceros_silencioso(lineas: list[Linea]) -> list[Linea]:
    return [l for l in lineas if l.importe != 0]
