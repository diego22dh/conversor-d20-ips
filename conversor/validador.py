"""Validaciones. Niveles: ERROR (bloquea), ADVERTENCIA (requiere revisión), INFO."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

import pandas as pd

from . import config
from .lector import cuil_valido
from .modelos import Hallazgo, Recibo
from .transformador import Parametros, Registro, calcular_liq, q

CERO = Decimal("0.00")


def validar_parametros(p: Parametros, recibos: list[Recibo], hoy: date | None = None) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    hoy = hoy or date.today()
    if not re.fullmatch(r"E\d{6}", p.codigo_empleador.strip()):
        h.append(Hallazgo("ERROR", "", "Código de empleador", f"'{p.codigo_empleador}' no tiene el formato E + 6 dígitos."))
    if not re.fullmatch(r"\d{4}/(0[1-9]|1[0-2])", p.periodo):
        h.append(Hallazgo("ERROR", "", "Período", f"'{p.periodo}' no tiene el formato AAAA/MM."))
    else:
        y, m = map(int, p.periodo.split("/"))
        if (y, m) > (hoy.year, hoy.month):
            h.append(Hallazgo("ERROR", "", "Período", "El mes de liquidación no puede ser posterior al mes actual."))
    periodos = {r.periodo for r in recibos}
    if len(periodos) > 1:
        h.append(Hallazgo("ERROR", "", "Período", f"El informe mezcla períodos: {sorted(periodos)}."))
    elif periodos and p.periodo not in periodos:
        h.append(Hallazgo("ERROR", "", "Período",
                          f"El período elegido ({p.periodo}) no coincide con el del informe ({next(iter(periodos))})."))
    if p.tipo_liquidacion == "N" and p.tipo_ddjj == "O" and p.nro_liquidacion != "01":
        h.append(Hallazgo("ADVERTENCIA", "", "Nº de liquidación",
                          "El primer envío del mes debe ser una liquidación original (O), normal (N) con número 01."))
    if p.tipo_liquidacion == "A" and p.nro_liquidacion == "01":
        h.append(Hallazgo("ADVERTENCIA", "", "Nº de liquidación",
                          "El 01 corresponde a la liquidación normal original; la adicional (SAC) suele llevar 02 o superior."))
    if p.tipo_ddjj != "O":
        h.append(Hallazgo("INFO", "", "Tipo de DDJJ",
                          "Rectificativa: debe repetir mes, tipo y número de la liquidación que rectifica, y la anterior "
                          "debe estar procesada por el IPS."))
    return h


def validar_recibos(recibos: list[Recibo]) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    for leg, n in Counter(r.legajo for r in recibos).items():
        if n > 1:
            h.append(Hallazgo("ERROR", leg, "Legajo", f"Legajo repetido {n} veces en el informe."))
    for r in recibos:
        if not r.cuil:
            h.append(Hallazgo("ERROR", r.legajo, "CUIL", "CUIL ausente."))
        elif not cuil_valido(r.cuil):
            h.append(Hallazgo("ERROR", r.legajo, "CUIL", f"CUIL inválido: {r.cuil_original}."))
        elif r.cuil != r.cuil_original:
            h.append(Hallazgo("INFO", r.legajo, "CUIL", f"CUIL normalizado sin guiones: {r.cuil_original} → {r.cuil}."))
        if not r.lineas:
            h.append(Hallazgo("ERROR", r.legajo, "Conceptos", "El recibo no tiene conceptos."))
    # CUIL con más de un legajo: informativo; si además los recibos son idénticos, advertir
    por_cuil = defaultdict(list)
    for r in recibos:
        por_cuil[r.cuil].append(r)
    for cuil, rs in por_cuil.items():
        if len(rs) > 1:
            legs = ", ".join(r.legajo for r in rs)
            h.append(Hallazgo("INFO", legs, "CUIL", f"El CUIL {cuil} tiene {len(rs)} legajos (cada uno es un cargo de SAP)."))
            firmas = Counter(tuple((l.concepto, l.importe) for l in r.lineas) for r in rs)
            if any(v > 1 for v in firmas.values()):
                iguales = [r.legajo for r in rs if firmas[tuple((l.concepto, l.importe) for l in r.lineas)] > 1]
                h.append(Hallazgo("ADVERTENCIA", ", ".join(iguales), "Recibos idénticos",
                                  f"Los legajos {', '.join(iguales)} (CUIL {cuil}) tienen exactamente los mismos conceptos e "
                                  "importes. Confirmar que no es un duplicado."))
    return h


def validar_padron(padron: pd.DataFrame, recibos: list[Recibo]) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    por_legajo = {str(r["legajo"]): r for r in padron.to_dict("records")}
    for rec in recibos:
        fila = por_legajo.get(rec.legajo)
        if fila is None:
            h.append(Hallazgo("ERROR", rec.legajo, "Padrón", "El legajo no está en el padrón de agentes."))
            continue
        cargo = str(fila["nro_cargo"]).strip()
        if not re.fullmatch(r"\d{1,4}", cargo):
            h.append(Hallazgo("ERROR", rec.legajo, "Nº de cargo", f"'{cargo}' no es un número de 1 a 4 dígitos."))
        for c in ("antig_admin_anios", "antig_admin_meses", "antig_otras_cajas_anios", "antig_otras_cajas_meses",
                  "antig_docente_anios", "antig_docente_meses"):
            try:
                v = int(fila[c])
                ok = 0 <= v <= 99 and (not c.endswith("meses") or v <= 11)
            except (TypeError, ValueError):
                ok = False
            if not ok:
                h.append(Hallazgo("ERROR", rec.legajo, c, f"Valor inválido: {fila[c]!r} (0-99; meses 0-11)."))
        try:
            d = Decimal(str(fila["dias_inasistencia"]))
            if not (0 <= d <= 99.9):
                raise ValueError
        except Exception:
            h.append(Hallazgo("ERROR", rec.legajo, "dias_inasistencia", f"Valor inválido: {fila['dias_inasistencia']!r}."))
        if str(fila["encuadre"]).strip() not in config.ENCUADRES:
            h.append(Hallazgo("ERROR", rec.legajo, "Encuadre", f"'{fila['encuadre']}' no es 13 ni 2."))
        if str(fila["modalidad"]).strip().upper() not in config.MODALIDADES:
            h.append(Hallazgo("ERROR", rec.legajo, "Modalidad", f"'{fila['modalidad']}' no es P, T ni R."))
    # un cargo no puede repetirse dentro del mismo CUIL
    vistos: dict[tuple, str] = {}
    for rec in recibos:
        fila = por_legajo.get(rec.legajo)
        if fila is None:
            continue
        clave = (rec.cuil, str(fila["nro_cargo"]).strip().lstrip("0") or "0")
        if clave in vistos:
            h.append(Hallazgo("ERROR", rec.legajo, "Nº de cargo",
                              f"El cargo {fila['nro_cargo']} está repetido para el CUIL {rec.cuil} (legajos {vistos[clave]} y {rec.legajo})."))
        vistos[clave] = rec.legajo
    pruebas = [r.legajo for r in recibos if str(por_legajo.get(r.legajo, {}).get("valor_prueba", "")).upper() == "SI"]
    if pruebas:
        h.append(Hallazgo("ADVERTENCIA", "varios" if len(pruebas) > 1 else pruebas[0], "Valores de PRUEBA",
                          f"{len(pruebas)} legajo(s) usan valores de prueba (nº de cargo, antigüedades, encuadre, "
                          "modalidad). SAP los comparará con sus datos y rechazará el archivo si no coinciden."))
    return h


def validar_totales(recibos: list[Recibo], totales_control: dict | None) -> list[Hallazgo]:
    """Control cruzado: suma por concepto del detalle vs bloque de totales del informe."""
    if not totales_control:
        return []
    h: list[Hallazgo] = []
    suma: dict[int, dict[str, Decimal]] = {}
    for r in recibos:
        for l in r.lineas:
            s = suma.setdefault(l.concepto, {"rem": CERO, "norem": CERO, "desc": CERO})
            s[l.columna] += l.importe
    for c in sorted(set(suma) | set(totales_control)):
        a = suma.get(c, {"rem": CERO, "norem": CERO, "desc": CERO})
        b = totales_control.get(c, {"rem": CERO, "norem": CERO, "desc": CERO})
        if a != b:
            h.append(Hallazgo("ERROR", "", f"Concepto {c}", f"El detalle suma {a} y el total del informe dice {b}."))
    if not h:
        h.append(Hallazgo("INFO", "", "Totales", "El detalle coincide con los totales por concepto del informe."))
    return h


def validar_resultado(registros: list[Registro], lineas_txt: list[str], largo: int, control: list[dict],
                      p: Parametros) -> list[Hallazgo]:
    h: list[Hallazgo] = []
    for r, linea in zip(registros, lineas_txt):
        if len(linea) != largo:
            h.append(Hallazgo("ERROR", r.legajo, "Longitud", f"La línea mide {len(linea)} y debe medir {largo}."))
        if r.tipo != "LIQ" and r.importe <= 0:
            h.append(Hallazgo("ERROR", r.legajo, f"Concepto {r.concepto_empleador}", f"Importe no positivo: {r.importe}."))
        if r.tipo == "LIQ" and r.importe < 0:
            h.append(Hallazgo("ERROR", r.legajo, "LIQ", f"LIQ negativo: {r.importe}."))
    # fórmula LIQ con tolerancia 0,50
    por_legajo: dict[str, list[Registro]] = defaultdict(list)
    for r in registros:
        por_legajo[r.legajo].append(r)
    for leg, rs in por_legajo.items():
        liq = next((x.importe for x in rs if x.tipo == "LIQ"), None)
        calc = CERO
        for x in rs:
            if x.tipo in ("RCA", "RSA") or (x.tipo == "AFA" and p.incluir_afa_en_liq):
                calc += x.importe
            elif x.tipo in ("DES", "DPS", "DAS"):
                calc -= x.importe
        if liq is None or abs(liq - calc) > Decimal(str(config.TOLERANCIA_LIQ)):
            h.append(Hallazgo("ERROR", leg, "LIQ", f"LIQ ({liq}) no responde a RCA+RSA-DES-DPS-DAS ({q(calc)})."))
    # control contra el neto de Nacional (ambas liquidaciones)
    for c in control:
        if abs(c["Diferencia"]) > Decimal("0.01"):
            h.append(Hallazgo("ERROR", c["Legajo"], "Control vs Nacional",
                              f"El neto de Nacional ({c['Neto Nacional']}) no coincide con LIQ normal + LIQ SAC "
                              f"+ AFA ({c['LIQ normal']} + {c['LIQ SAC']} + {c['AFA fuera de LIQ']}); diferencia {c['Diferencia']}."))
    if not registros:
        h.append(Hallazgo("ERROR", "", "Registros", "La liquidación elegida no tiene ningún registro para informar."))
    return h
