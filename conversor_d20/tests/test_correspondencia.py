"""Correspondencia de conceptos por colegio."""
import pandas as pd
import pytest

from conversor import config, conceptos as cz
from conversor.conceptos import (cargar_conceptos, conceptos_sin_correspondencia, guardar_conceptos_empleador,
                                 origen_para_empleador, plantilla_correspondencia)
from conversor.lector import leer_nacional
from tests.conftest import armar_informe


def _xlsx(tmp_path, filas, columnas, nombre="corr.xlsx"):
    p = tmp_path / nombre
    pd.DataFrame(filas, columns=columnas).to_excel(p, index=False)
    return p


def test_encabezados_flexibles(tmp_path):
    p = _xlsx(tmp_path, [[100, "Sueldo", "RCA", 100001], [700, "Obra social", "DES", 700000]],
              ["Cód. Liquidación", "Concepto", "Tipo de concepto", "Código SAP"])
    df, hall = cargar_conceptos(p)
    assert set(df["codigo"]) == {100, 700}
    assert not [h for h in hall if h.nivel == "ERROR"]


def test_obra_social_se_corrige_por_codigo_ips(tmp_path):
    p = _xlsx(tmp_path, [[555, "OSPE", "DES", 700000]], ["codigo", "descripcion", "tipo", "ips"])
    df, _ = cargar_conceptos(p)
    assert df.loc[df.codigo == 555, "tipo"].iloc[0] == "DAS"


def test_faltan_columnas_obligatorias(tmp_path):
    p = _xlsx(tmp_path, [[1, "x"]], ["codigo", "descripcion"])
    with pytest.raises(ValueError):
        cargar_conceptos(p)


def test_ips_desconocido_advierte(tmp_path):
    p = _xlsx(tmp_path, [[1, "x", "RCA", 123456]], ["codigo", "descripcion", "tipo", "ips"])
    _, hall = cargar_conceptos(p)
    assert any(h.nivel == "ADVERTENCIA" for h in hall)


def test_guardar_y_usar_por_colegio(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONCEPTOS_DIR", tmp_path / "conc")
    monkeypatch.setattr(cz, "CONCEPTOS_DIR", tmp_path / "conc", raising=False)
    ruta, propio = origen_para_empleador("E999999")
    assert not propio
    df, _ = cargar_conceptos()
    guardar_conceptos_empleador("E999999", df)
    ruta, propio = origen_para_empleador("E999999")
    assert propio and ruta.exists()
    df2, _ = cargar_conceptos(ruta)
    assert len(df2) == len(df)


def test_plantilla_se_puede_cargar(tmp_path):
    p = tmp_path / "plantilla.xlsx"
    plantilla_correspondencia().to_excel(p, index=False)
    df, hall = cargar_conceptos(p)
    assert len(df) > 0 and not [h for h in hall if h.nivel == "ERROR"]


def test_sin_correspondencia(tmp_path):
    inf = armar_informe(tmp_path / "inf.xlsx")
    lect = leer_nacional(inf)
    df, _ = cargar_conceptos()
    df = df[df.codigo != df.codigo.iloc[0]]
    usados = {l.concepto for r in lect.recibos for l in r.lineas}
    falt = conceptos_sin_correspondencia(lect.recibos, df)
    assert len(falt) == len(usados - set(df.codigo))


def test_login_falla_cerrado_y_valida_clave(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("APP_SIN_LOGIN", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    at = AppTest.from_file(str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30).run()
    assert any("contraseña configurada" in e.value for e in at.error)
    monkeypatch.setenv("APP_PASSWORD", "clave123")
    at = AppTest.from_file(str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30).run()
    assert not at.file_uploader
    at.text_input[0].set_value("mala"); at.button[0].click().run()
    assert not at.file_uploader and at.error
    at.text_input[0].set_value("clave123"); at.button[0].click().run()
    assert at.file_uploader
