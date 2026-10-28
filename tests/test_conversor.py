import io
import os
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from conversor import config, escritor
from conversor.conceptos import cargar_conceptos
from conversor.lector import cuil_valido, leer_nacional
from conversor.pipeline import procesar
from conversor.transformador import Parametros, Registro, _repartir

from conftest import CUIL_A, CUIL_B, armar_informe

HOY = date(2026, 10, 23)
D = Decimal


def params(**kw):
    base = dict(codigo_empleador="E060906", periodo="2026/09")
    base.update(kw)
    return Parametros(**base)


# ------------------------------------------------------------------ formato de línea
def test_linea_coincide_con_ejemplo_del_instructivo():
    """Línea de la hoja SALARIO de excelSalarial (con un CUIL ficticio)."""
    esperado = ("E0609062026/0901NO" + "20111111112" + "1002" + "100000" + "00001000" + "RCA"
                + "PRUEBA CONCEPTO 1        " + "0384662.30" + "000000002203" + "M" + "000" + "000" + "13" + "P")
    assert len(esperado) == 107
    reg = Registro("1", "20111111112", 100000, 1000, "RCA", "PRUEBA CONCEPTO 1", D("384662.30"))
    pad = {"nro_cargo": "1002", "antig_admin_anios": 0, "antig_admin_meses": 0, "antig_otras_cajas_anios": 0,
           "antig_otras_cajas_meses": 0, "antig_docente_anios": 22, "antig_docente_meses": 3,
           "dias_inasistencia": 0, "encuadre": "13", "modalidad": "P"}
    assert escritor.construir_linea(reg, params(), pad, 10) == esperado


def test_encuadre_2_lleva_espacio_y_dias_con_decimal():
    reg = Registro("1", "20111111112", 100000, 1, "RCA", "X", D("1.00"), dias_licencia=D("13.5"))
    pad = {"nro_cargo": "1", "antig_admin_anios": 0, "antig_admin_meses": 0, "antig_otras_cajas_anios": 0,
           "antig_otras_cajas_meses": 0, "antig_docente_anios": 0, "antig_docente_meses": 0,
           "dias_inasistencia": 1, "encuadre": "2", "modalidad": "T"}
    ln = escritor.construir_linea(reg, params(), pad, 10)
    assert ln.endswith("M" + "010" + "135" + "2 " + "T")
    assert ln[29:33] == "0001"


def test_importes_negativos_y_formato_110():
    assert escritor.formatear_importe(D("-98775.65"), 10) == "-098775.65"
    assert escritor.formatear_importe(D("98775.65"), 10) == "0098775.65"
    regs = [Registro("1", "x", 1, 1, "RCA", "A", D("1.00")), Registro("1", "x", 1, 1, "RCA", "A", D("-1324237.71"))]
    assert escritor.elegir_formato(regs) == escritor.ANCHO_110
    assert escritor.formatear_importe(D("-1324237.71"), 12) == "-01324237.71"
    assert escritor.formatear_importe(D("10000000.00"), 12) == "001000000.00".replace("001000000", "010000000")


def test_descripcion_ascii_mayusculas_y_recorte():
    txt, recortado, cambio = escritor.ascii_mayus("Antigüedad años")
    assert txt == "ANTIGUEDAD ANOS".ljust(25) and cambio and not recortado
    txt, recortado, _ = escritor.ascii_mayus("BONIF.REM.DOC.NO BONIF (PRF)")
    assert len(txt) == 25 and recortado


def test_nombre_zip_y_contenido():
    assert escritor.nombre_zip(params(tipo_ddjj="O", tipo_liquidacion="N", nro_liquidacion="01")) == "E060906_092026_ON_01.zip"
    assert escritor.nombre_zip(params(tipo_liquidacion="A", nro_liquidacion="02")) == "E060906_092026_OA_02.zip"
    z = zipfile.ZipFile(io.BytesIO(escritor.crear_zip(["A" * 107, "B" * 107])))
    assert z.namelist() == ["SALARIO.TXT"]
    assert z.read("SALARIO.TXT") == b"A" * 107 + b"\r\n" + b"B" * 107  # sin línea vacía al final


# ------------------------------------------------------------------ utilidades
def test_cuil_valido():
    assert cuil_valido(CUIL_A) and not cuil_valido(CUIL_A[:-1] + "0" if CUIL_A[-1] != "0" else CUIL_A[:-1] + "1")
    assert not cuil_valido("123") and not cuil_valido("2711111111a")


def test_repartir_en_centavos_exactos():
    partes = _repartir(D("100.00"), [D("1.00"), D("1.00"), D("1.00")])
    assert sum(partes) == D("100.00") and sorted(partes) == [D("33.33"), D("33.33"), D("33.34")]


def test_obra_social_se_informa_como_das():
    df, hall = cargar_conceptos()
    assert set(df[df.codigo.isin([520, 521, 522, 523])].tipo) == {"DAS"}
    assert df[df.codigo == 400].tipo.iloc[0] == "DPS"


# ------------------------------------------------------------------ lectura
def test_lectura_excluye_bloque_de_totales(informe):
    lec = leer_nacional(informe)
    assert [r.legajo for r in lec.recibos] == ["1001", "1002", "1003"]
    assert lec.totales_control and lec.totales_control[11]["rem"] == D("210000.00")
    assert sum(len(r.lineas) for r in lec.recibos) == 4 + 7 + 6
    assert lec.recibos[1].cuil == CUIL_B  # sin guiones


def test_lectura_sin_totales(tmp_path):
    lec = leer_nacional(armar_informe(tmp_path / "x.xlsx", con_totales=False))
    assert lec.totales_control is None and len(lec.recibos) == 3
    assert any("bloque de totales" in h.mensaje for h in lec.hallazgos)


def test_lectura_rechaza_archivo_ajeno(tmp_path):
    pd.DataFrame([["a", "b"]]).to_excel(tmp_path / "m.xlsx", header=False, index=False)
    with pytest.raises(ValueError):
        leer_nacional(tmp_path / "m.xlsx")


# ------------------------------------------------------------------ liquidación normal
def test_liquidacion_normal_neteo_sac_y_liq(informe):
    r = procesar(informe, params(), None, hoy=HOY)
    assert not r.errores, [h.mensaje for h in r.errores]
    regs = {(x.legajo, x.concepto_empleador): x for x in r.registros}
    # 1001: SAC y su parte de descuentos salen de la normal (IPS 17600 - 1600 = 16000; OS 3300 - 300 = 3000)
    assert (("1001", 101) not in regs) and regs[("1001", 400)].importe == D("16000.00")
    assert regs[("1001", 521)].importe == D("3000.00") and regs[("1001", 521)].tipo == "DAS"
    assert regs[("1001", 9999)].importe == D("81000.00")           # 100000 - 16000 - 3000
    # 1002: licencia 20000 repartida 60/40 -> 12000 / 8000; el concepto 141 desaparece
    assert regs[("1002", 11)].importe == D("48000.00") and regs[("1002", 14)].importe == D("32000.00")
    assert ("1002", 141) not in regs
    assert regs[("1002", 9999)].importe == D("80000.00") - D("12800.00") - D("2400.00") + D("5000.00")
    assert regs[("1002", 40)].tipo == "AFA" and regs[("1002", 9999)].dias_licencia == D("6")
    # 1003: todo compensado -> solo LIQ en 0,00 con 30 días de licencia
    assert [x.tipo for x in r.registros if x.legajo == "1003"] == ["LIQ"]
    assert r.registros[-1].importe == D("0.00") and r.registros[-1].dias_licencia == D("30")
    assert r.largo_linea == 107 and all(len(x) == 107 for x in r.lineas_txt)
    # LIQ es siempre la última línea de cada cargo
    for leg in ("1001", "1002", "1003"):
        assert [x for x in r.registros if x.legajo == leg][-1].tipo == "LIQ"


def test_control_contra_neto_de_nacional(informe):
    r = procesar(informe, params(), None, hoy=HOY)
    assert (r.control["Diferencia"].abs() < 0.01).all()
    fila = r.control[r.control.Legajo == "1001"].iloc[0]
    assert fila["LIQ normal"] + fila["LIQ SAC"] == pytest.approx(fila["Neto Nacional"])


def test_afa_se_puede_incluir_en_liq(informe):
    r = procesar(informe, params(incluir_afa_en_liq=True), None, hoy=HOY)
    assert not r.errores
    liq = next(x for x in r.registros if x.legajo == "1002" and x.tipo == "LIQ")
    assert liq.importe == D("80000.00") - D("12800.00") - D("2400.00") + D("5000.00") + D("3000.00")


# ------------------------------------------------------------------ liquidación SAC (tipo A)
def test_liquidacion_sac_aparte(informe):
    r = procesar(informe, params(tipo_liquidacion="A", nro_liquidacion="02"), None, hoy=HOY)
    assert not r.errores, [h.mensaje for h in r.errores]
    assert {x.legajo for x in r.registros} == {"1001"}
    assert [(x.tipo, x.importe) for x in r.registros] == [
        ("RCA", D("10000.00")), ("DPS", D("1600.00")), ("DAS", D("300.00")), ("LIQ", D("8100.00"))]
    assert all(l[16] == "A" and l[14:16] == "02" for l in r.lineas_txt)


def test_sac_pedido_sin_sac_en_el_informe(tmp_path):
    f = armar_informe(tmp_path / "s.xlsx")
    df = pd.read_excel(f, header=None)
    df = df[df[9] != 101].reset_index(drop=True)
    df.to_excel(f, header=False, index=False)
    r = procesar(f, params(tipo_liquidacion="A", nro_liquidacion="02"), None, hoy=HOY)
    assert any("no tiene conceptos de SAC" in h.mensaje for h in r.errores)


# ------------------------------------------------------------------ validaciones
def test_valores_de_prueba_generan_advertencia(informe):
    r = procesar(informe, params(), None, hoy=HOY)
    assert any(h.campo == "Valores de PRUEBA" for h in r.advertencias)
    assert set(r.padron["nro_cargo"]) == {"9001", "9002", "9003"}


def test_periodo_distinto_posterior_o_mal_formado(informe):
    assert any("no coincide" in h.mensaje for h in procesar(informe, params(periodo="2026/08"), None, hoy=HOY).errores)
    assert any("posterior" in h.mensaje for h in procesar(informe, params(periodo="2026/09"), None, hoy=date(2026, 8, 1)).errores)
    assert any("AAAA/MM" in h.mensaje for h in procesar(informe, params(periodo="09/2026"), None, hoy=HOY).errores)


def test_error_bloqueante_impide_generar_txt(informe):
    r = procesar(informe, params(codigo_empleador="X123"), None, hoy=HOY)
    assert r.errores and not r.puede_generar and r.lineas_txt == []


def test_padron_invalido_bloquea(informe):
    base = procesar(informe, params(), None, hoy=HOY).padron.copy()
    base.loc[0, "modalidad"] = "Z"
    base.loc[1, "nro_cargo"] = "12345"
    base.loc[2, "antig_docente_meses"] = 15
    r = procesar(informe, params(), base, hoy=HOY)
    campos = {h.campo for h in r.errores}
    assert {"Modalidad", "Nº de cargo", "antig_docente_meses"} <= campos


def test_cargo_repetido_en_mismo_cuil(tmp_path):
    f = armar_informe(tmp_path / "c.xlsx")
    df = pd.read_excel(f, header=None, dtype=object)
    df.loc[df[0] == "1002", 2] = CUIL_A   # 1002 pasa a tener el mismo CUIL que 1001
    df.to_excel(f, header=False, index=False)
    base = procesar(f, params(), None, hoy=HOY).padron.copy()
    base["nro_cargo"] = "0100"
    r = procesar(f, params(), base, hoy=HOY)
    assert any("repetido para el CUIL" in h.mensaje for h in r.errores)


def test_concepto_desconocido_y_columna_inconsistente(tmp_path):
    f = armar_informe(tmp_path / "d.xlsx", con_totales=False)
    df = pd.read_excel(f, header=None, dtype=object)
    df.loc[1, 9] = 99999                      # concepto que no está en el listado
    df.loc[2, [12, 13]] = [None, 10000]       # SAC (RCA) informado en la columna no remunerativa
    df.to_excel(f, header=False, index=False)
    r = procesar(f, params(), None, hoy=HOY)
    msgs = " | ".join(h.mensaje for h in r.errores)
    assert "no figura en el listado" in msgs and "columna" in msgs


def test_control_cruzado_con_totales_detecta_diferencia(tmp_path):
    f = armar_informe(tmp_path / "t.xlsx")
    df = pd.read_excel(f, header=None, dtype=object)
    df.loc[df.index[-1], 12] = 1  # altera un total
    df.loc[df.index[-1], 14] = df.loc[df.index[-1], 14]
    df.to_excel(f, header=False, index=False)
    r = procesar(f, params(), None, hoy=HOY)
    assert r.errores or any("Totales" in h.campo for h in r.hallazgos)


# ------------------------------------------------------------------ informe real (opcional)
REAL = Path("/mnt/user-data/attachments/e140ed2c-b442-59cb-8ec8-407c0843c12b/47e82a73-Informe_Recibos_Agrupados_1.xls")


@pytest.mark.skipif(not (REAL.exists() or os.environ.get("INFORME_REAL")), reason="informe real no disponible")
def test_informe_real_septiembre_2026():
    origen = os.environ.get("INFORME_REAL") or REAL
    n = procesar(origen, params(), None, hoy=HOY)
    a = procesar(origen, params(tipo_liquidacion="A", nro_liquidacion="02"), None, hoy=HOY)
    assert not n.errores and not a.errores
    assert n.resumen["recibos_leidos"] == 25
    assert (n.control["Diferencia"].abs() < 0.01).all()
    # N + A + AFA excluida == neto total de Nacional
    neto = n.control["Neto Nacional"].sum()
    assert round(n.resumen["total_liq"] + a.resumen["total_liq"] + n.control["AFA fuera de LIQ"].sum(), 2) == pytest.approx(neto)
    assert {len(x) for x in n.lineas_txt} == {107} and {len(x) for x in a.lineas_txt} == {107}
