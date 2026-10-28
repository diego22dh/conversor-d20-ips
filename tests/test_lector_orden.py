"""Regresión: conceptos del último recibo en orden NO ascendente no deben descartarse (caso legajo 3681)."""
from datetime import date

import pandas as pd

from conversor.lector import leer_nacional
from conversor.pipeline import procesar
from conversor.transformador import Parametros
from tests.conftest import ENCABEZADO, _cuil, fila_cab, fila_det


def _informe(path, con_total_general=True):
    f = [ENCABEZADO, fila_cab("3681", "MIGUEZ", _cuil("2024498869"), 1407419.97, 30709, 267409.8, 1001,
                              "SUELDO BASICO HS", 10, 349693, None, None)]
    for c, ds, u, r, n, d in [(1020, "ANTIGUEDAD", 105, 367177.65, None, None), (1031, "BONIF", 10, 141881, None, None),
                              (1051, "BONIF 2014", 10, 148619.53, None, None), (1531, "COMP FONID", 10, None, 30709, None),
                              (1080, "DIFERENCIAS", None, 293742.12, None, None), (5400, "IPS 16%", 16, None, None, 225187.2),
                              (5521, "OBRA SOCIAL 3%", 3, None, None, 42222.6), (1244, "BONIF LINCOLN", 21, 73435.53, None, None),
                              (1245, "PRESENTISMO", 9.4, 32871.14, None, None)]:
        f.append(fila_det(c, ds, u, r, n, d))
    if con_total_general:
        f.append([None] * 9 + [None, None, None, 1407419.97, 30709, 267409.8])
    pd.DataFrame(f).to_excel(path, header=False, index=False)
    return path


def test_no_se_descartan_lineas_por_orden_de_conceptos(tmp_path):
    lect = leer_nacional(_informe(tmp_path / "i.xlsx"))
    assert [l.concepto for l in lect.recibos[0].lineas] == [1001, 1020, 1031, 1051, 1531, 1080, 5400, 5521, 1244, 1245]


def test_liq_igual_a_nacional(tmp_path):
    conc = tmp_path / "conc.xlsx"
    pd.DataFrame([[1001, "SUELDO", "RCA", 100000], [1020, "ANTIG", "RCA", 100001], [1031, "B", "RCA", 100004],
                  [1051, "B", "RCA", 100004], [1080, "D", "RCA", 100004], [1244, "B", "RCA", 100004],
                  [1245, "P", "RCA", 100004], [1531, "FONID", "RSA", 100000], [5400, "IPS", "DPS", 500001],
                  [5521, "OS", "DAS", 700000]], columns=["codigo", "descripcion", "tipo", "ips"]).to_excel(conc, index=False)
    r = procesar(_informe(tmp_path / "i.xlsx"),
                 Parametros("E060906", "2026/09", "N", "O", "01", 9999, False, [100, 101, 103, 860], [141, 143, 144]),
                 None, conceptos_origen=conc, hoy=date(2026, 10, 28))
    assert not r.errores or all("Padrón" not in str(e) and "Concepto" not in str(e) for e in r.errores)
    assert abs(float(r.control["Diferencia"].iloc[0])) < 0.01
    assert float(r.control["LIQ normal"].iloc[0]) == 1170719.17


def test_recibo_que_no_cierra_con_su_cabecera_es_error(tmp_path):
    from conversor.validador import validar_recibos
    lect = leer_nacional(_informe(tmp_path / "i.xlsx"))
    lect.recibos[0].lineas.pop()          # falta el presentismo
    assert any(h.nivel == "ERROR" and h.campo == "Totales del recibo" for h in validar_recibos(lect.recibos))
