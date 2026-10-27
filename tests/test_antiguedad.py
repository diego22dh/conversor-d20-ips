import pandas as pd
import pytest

from conversor.antiguedad import aplicar_antiguedad, cargar_antiguedad, meses_entre
from conversor.lector import leer_nacional
from conversor.padron import completar_padron
from tests.conftest import CUIL_A, armar_informe


def _x(tmp_path, filas, cols):
    p = tmp_path / "ant.xlsx"
    pd.DataFrame(filas, columns=cols).to_excel(p, index=False)
    return p


def test_anios_meses_por_legajo(tmp_path):
    p = _x(tmp_path, [["1001", 12, 3, 5, 1]], ["Legajo", "Años antigüedad docente", "Meses antigüedad docente",
                                               "Años antigüedad IPS", "Meses antigüedad IPS"])
    df, hall = cargar_antiguedad(p)
    assert not hall
    lect = leer_nacional(armar_informe(tmp_path / "i.xlsx"))
    pad, h, n = aplicar_antiguedad(completar_padron(lect.recibos, None), df, lect.recibos)
    fila = pad[pad.legajo == "1001"].iloc[0]
    assert (fila.antig_docente_anios, fila.antig_docente_meses, fila.antig_admin_anios, fila.antig_admin_meses) == (12, 3, 5, 1)
    assert n == 1 and any(x.nivel == "ADVERTENCIA" for x in h)  # los otros legajos no están


def test_por_cuil_y_valor_invalido(tmp_path):
    p = _x(tmp_path, [[CUIL_A, 2, 14]], ["CUIL", "Antigüedad docente años", "Antigüedad docente meses"])
    _, hall = cargar_antiguedad(p)
    assert any(h.nivel == "ERROR" for h in hall)


def test_fecha_de_ingreso(tmp_path):
    p = _x(tmp_path, [["1001", "15/03/2014"]], ["Legajo", "Fecha ingreso docente"])
    df, hall = cargar_antiguedad(p, "2026/09")
    assert (df.antig_docente_anios[0], df.antig_docente_meses[0]) == (12, 6)
    assert any(h.nivel == "ADVERTENCIA" for h in hall)
    assert meses_entre(pd.Timestamp("2014-03-15").date(), pd.Timestamp("2026-09-14").date()) == 12 * 12 + 5


def test_sin_columnas_de_antiguedad(tmp_path):
    with pytest.raises(ValueError):
        cargar_antiguedad(_x(tmp_path, [["1001"]], ["Legajo"]))


def test_listado_de_empleados_de_nacional(tmp_path):
    cols = ["Empleado", "Apellido", "Nombre", "C.U.I.L.", "Grupo", "Antiguedad", "Tarea", "Sueldo", "Edad", "Orden"]
    filas = [[1001, "A", "B", CUIL_A, None, 10, None, None, 0, 1], [1002, "A", "B", CUIL_A, None, 2, None, None, 0, 2]]
    df, hall = cargar_antiguedad(_x(tmp_path, filas, cols))
    assert not [h for h in hall if h.nivel == "ERROR"]          # CUIL repetido con legajos distintos: válido
    assert list(df.antig_docente_anios) == [10, 2] and list(df.antig_docente_meses) == [0, 0]
    assert any("sin meses" in h.mensaje for h in hall)


def test_listado_nacional_con_fecha_antiguedad(tmp_path):
    cols = ["Empleado", "Descripción", "legajo", "Apellido", "Nombre", "Fecha Ingreso", "Fecha Egreso", "Fecha Antiguedad "]
    filas = [[1001, "X", 1001, "A", "B", "03/08/2020", None, "04/02/2019"], [None] * 8,
             [1002, "Y", 1002, "A", "B", "15/02/2016", None, "15/02/2016"]]
    df, hall = cargar_antiguedad(_x(tmp_path, filas, cols), "2026/09")
    # 04/02/2019 -> 30/09/2026: 7 años 7 meses (se usa Fecha Antigüedad, no Fecha Ingreso); 15/02/2016 -> 10 años 7 meses
    assert list(df.legajo) == ["1001", "1002"]
    assert list(zip(df.antig_docente_anios, df.antig_docente_meses)) == [(7, 7), (10, 7)]
    assert not [h for h in hall if h.nivel == "ERROR"]


def test_guardar_listado_por_colegio(tmp_path, monkeypatch):
    from conversor import config
    from conversor.antiguedad import guardar_listado, ruta_guardada
    monkeypatch.setattr(config, "ANTIGUEDAD_DIR", tmp_path / "ant")
    assert ruta_guardada("E1") is None
    guardar_listado("E1", "Listado.xls", b"abc")
    assert ruta_guardada("E1").suffix == ".xls"
    guardar_listado("E1", "otro.xlsx", b"def")
    assert ruta_guardada("E1").suffix == ".xlsx" and not (tmp_path / "ant" / "E1.xls").exists()


def test_modelo_se_puede_cargar(tmp_path):
    from conversor.antiguedad import plantilla_antiguedad
    p = tmp_path / "m.xlsx"; plantilla_antiguedad().to_excel(p, index=False)
    df, hall = cargar_antiguedad(p, "2026/09")
    assert list(df.legajo) == ["1001", "1002"] and not [h for h in hall if h.nivel == "ERROR"]


def test_antiguedad_ips_replica_la_docente(tmp_path):
    p = _x(tmp_path, [["1001", "15/03/2014"]], ["Legajo", "Fecha Antiguedad"])
    df, _ = cargar_antiguedad(p, "2026/09")
    lect = leer_nacional(armar_informe(tmp_path / "i.xlsx"))
    pad, _, _ = aplicar_antiguedad(completar_padron(lect.recibos, None), df, lect.recibos)
    f = pad[pad.legajo == "1001"].iloc[0]
    assert (f.antig_admin_anios, f.antig_admin_meses) == (f.antig_docente_anios, f.antig_docente_meses) == (12, 6)
    assert (f.antig_otras_cajas_anios, f.antig_otras_cajas_meses) == (0, 0)
    # el TXT lleva los dos pares iguales
    from conversor.escritor import construir_linea  # noqa: F401
