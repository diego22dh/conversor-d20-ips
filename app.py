"""Conversor de Remuneraciones — Nacional Software a IPS D20 Digital.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import hashlib
import io
from datetime import date

import pandas as pd
import streamlit as st

from conversor import config, escritor
from conversor.acceso import requerir_login
from conversor.antiguedad import aplicar_antiguedad, cargar_antiguedad, plantilla_antiguedad
from conversor.conceptos import (cargar_conceptos, conceptos_sin_correspondencia, guardar_conceptos_empleador,
                                 origen_para_empleador, plantilla_correspondencia)
from conversor.informe import informe_excel, totales_por_tipo
from conversor.lector import leer_nacional
from conversor.padron import NUMERICAS, cargar_padron, completar_padron, guardar_padron
from conversor.pipeline import procesar
from conversor.transformador import Parametros

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Conversor Nacional → IPS D20", page_icon="📄", layout="wide")
requerir_login()

st.title("Conversor de Remuneraciones — Nacional Software a IPS D20 Digital")
st.caption("Genera el SALARIO.TXT (dentro del ZIP) que se sube manualmente a SAP – Información salarial – Enviar salarios. "
           "La aplicación no se conecta con el IPS.")


@st.cache_data(show_spinner=False)
def _leer(datos: bytes):
    return leer_nacional(io.BytesIO(datos))


def _enteros(texto: str, defecto: list[int]) -> list[int]:
    try:
        return [int(x) for x in texto.replace(";", ",").split(",") if x.strip()]
    except ValueError:
        return defecto


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    b = io.BytesIO()
    df.to_excel(b, index=False)
    return b.getvalue()


# ---------------------------------------------------------------- archivo de remuneraciones
st.subheader("1. Archivo de remuneraciones")
subido = st.file_uploader("Informe «Recibos Agrupados por Empleado» exportado desde Nacional Software (.xls / .xlsx)",
                          type=["xls", "xlsx"])
ant_subido = st.file_uploader("Listado de empleados con antigüedad (opcional, .xls / .xlsx)", type=["xls", "xlsx"],
                              key="antiguedad_up",
                              help="Con legajo o CUIL y la antigüedad docente (años y meses). Opcionalmente antigüedad IPS y de otras "
                                   "cajas, o fecha de ingreso docente. El instructivo exige estos campos en cada línea del TXT.")
st.download_button("Descargar planilla de ejemplo del listado de antigüedad", _xlsx_bytes(plantilla_antiguedad()),
                   "listado_antiguedad_ejemplo.xlsx", XLSX)
lectura, datos, error_lectura = None, None, None
if subido is not None:
    datos = subido.getvalue()
    try:
        lectura = _leer(datos)
    except Exception as e:  # noqa: BLE001 - mostrar el motivo al usuario
        error_lectura = str(e)
if lectura is not None:
    periodos_informe = sorted({r.periodo for r in lectura.recibos})
    if len(periodos_informe) == 1 and st.session_state.get("_periodo_detectado") != (subido.name, periodos_informe[0]):
        st.session_state["_periodo_detectado"] = (subido.name, periodos_informe[0])
        if periodos_informe[0] in config.periodos_disponibles():
            st.session_state["periodo"] = periodos_informe[0]  # antes de crear el desplegable

# ---------------------------------------------------------------- barra lateral
par = config.cargar_parametros()
with st.sidebar:
    st.header("Parámetros de la liquidación")
    codigo = st.selectbox("Código de empleador", par["codigos_empleador"])
    with st.expander("Agregar un código de empleador"):
        nuevo = st.text_input("Código (E + 6 dígitos)", max_chars=7, key="nuevo_codigo").strip().upper()
        if st.button("Agregar") and nuevo:
            if len(nuevo) == 7 and nuevo[0] == "E" and nuevo[1:].isdigit():
                if nuevo not in par["codigos_empleador"]:
                    par["codigos_empleador"].append(nuevo)
                    config.guardar_parametros(par)
                st.rerun()
            else:
                st.error("Formato inválido. Ejemplo: E060906")
    periodos = config.periodos_disponibles()
    periodo = st.selectbox("Período de liquidación (AAAA/MM)", periodos, key="periodo")
    tipo_liq = st.selectbox("Tipo de liquidación", list(config.TIPOS_LIQUIDACION),
                            format_func=config.TIPOS_LIQUIDACION.get, key="tipo_liq")
    tipo_ddjj = st.selectbox("Tipo de declaración jurada", list(config.TIPOS_DDJJ),
                             format_func=config.TIPOS_DDJJ.get)
    sugerido = "01" if tipo_liq == "N" else "02"
    nro_liq = st.selectbox("Número de liquidación", config.NUMEROS_LIQUIDACION,
                           index=config.NUMEROS_LIQUIDACION.index(sugerido), key=f"nro_{tipo_liq}")
    guardado = config.config_empleador(par, codigo)
    with st.expander("Parámetros del colegio (avanzados)"):
        liq_emp = st.number_input("Concepto empleador para LIQ (8 dígitos)", 1, 99999999,
                                  guardado["liq_empleador"], key=f"liq_{codigo}")
        sac_txt = st.text_input("Códigos de liquidación del SAC", ", ".join(map(str, guardado["conceptos_sac"])),
                                key=f"sac_{codigo}")
        lic_txt = st.text_input("Códigos de licencia sin goce (unidad = días)",
                                ", ".join(map(str, guardado["conceptos_licencia"])), key=f"lic_{codigo}")
        incluir_afa = st.checkbox("Incluir asignaciones familiares (AFA) en LIQ", value=False,
                                  help="El instructivo define LIQ = RCA + RSA − DES − DPS − DAS, sin AFA.")
        if st.button("Guardar parámetros de este colegio"):
            par.setdefault("empleadores", {})[codigo] = {
                "liq_empleador": int(liq_emp),
                "conceptos_sac": _enteros(sac_txt, config.CONCEPTOS_SAC_DEFAULT),
                "conceptos_licencia": _enteros(lic_txt, config.CONCEPTOS_LICENCIA_DEFAULT)}
            config.guardar_parametros(par)
            st.success(f"Guardado para {codigo}.")

p = Parametros(codigo, periodo, tipo_liq, tipo_ddjj, nro_liq, int(liq_emp), incluir_afa,
               _enteros(sac_txt, config.CONCEPTOS_SAC_DEFAULT), _enteros(lic_txt, config.CONCEPTOS_LICENCIA_DEFAULT))

if subido is None:
    st.info("Subí el informe de Nacional Software para empezar.")
    st.stop()
if error_lectura:
    st.error(f"No pude leer el archivo: {error_lectura}")
    st.stop()
st.success(f"Se leyeron {len(lectura.recibos)} recibos (legajos) del período {', '.join(periodos_informe)}.")

# ---------------------------------------------------------------- correspondencia de conceptos
st.subheader("2. Correspondencia de conceptos del colegio")
st.caption("Relaciona los códigos de liquidación del colegio (Nacional Software) con el tipo de concepto y el código "
           "IPS/SAP. Cada colegio tiene los suyos: se guarda un listado por código de empleador.")
ver = st.session_state.setdefault("conc_ver", 0)
col_a, col_b = st.columns([3, 1])
conc_subido = col_a.file_uploader(
    f"Cargar la correspondencia de conceptos de {codigo} (.xls / .xlsx)", type=["xls", "xlsx"],
    key=f"conc_{codigo}_{ver}",
    help="Columnas: código de liquidación, tipo de concepto IPS (RCA/RSA/AFA/DPS/DAS/DES) y concepto IPS (código SAP). "
         "Descripción y Columna son opcionales.")
col_b.download_button("Descargar planilla de ejemplo", _xlsx_bytes(plantilla_correspondencia()),
                      "correspondencia_conceptos_ejemplo.xlsx", XLSX)

ruta_guardada, es_propio = origen_para_empleador(codigo)
conceptos_origen, conceptos_huella = ruta_guardada, f"{ruta_guardada}:{ruta_guardada.stat().st_mtime}"
try:
    if conc_subido is not None:
        bytes_conc = conc_subido.getvalue()
        conceptos_origen, conceptos_huella = io.BytesIO(bytes_conc), hashlib.md5(bytes_conc).hexdigest()
        conceptos_df, hall_conc = cargar_conceptos(io.BytesIO(bytes_conc))
        etiqueta = f"Usando el archivo cargado «{conc_subido.name}» (todavía sin guardar)."
    else:
        conceptos_df, hall_conc = cargar_conceptos(ruta_guardada)
        etiqueta = (f"Usando el listado guardado de {codigo}." if es_propio else
                    f"{codigo} no tiene un listado propio: se usa el listado predeterminado, que puede no coincidir con "
                    "los códigos de este colegio. Cargá y guardá el suyo.")
except ValueError as e:
    st.error(f"No pude usar el listado: {e}")
    st.stop()

(st.success if (es_propio or conc_subido is not None) else st.warning)(f"{etiqueta} {len(conceptos_df)} conceptos.")
for h in hall_conc:
    if h.nivel == "ERROR":
        st.error(f"{h.campo}: {h.mensaje}")
    elif h.nivel == "ADVERTENCIA":
        st.warning(f"{h.campo}: {h.mensaje}")
if conc_subido is not None and not any(h.nivel == "ERROR" for h in hall_conc):
    if st.button(f"Guardar como listado de {codigo}", type="primary"):
        destino = guardar_conceptos_empleador(codigo, conceptos_df)
        st.session_state["conc_ver"] += 1
        st.session_state["_msg_guardado"] = f"Listado guardado para {codigo} ({len(conceptos_df)} conceptos) en {destino}"
        st.rerun()
if "_msg_guardado" in st.session_state:
    st.success(st.session_state.pop("_msg_guardado"))

faltantes = conceptos_sin_correspondencia(lectura.recibos, conceptos_df)
if len(faltantes):
    st.error(f"El informe usa {len(faltantes)} concepto(s) que el listado no cubre. Agregalos al listado y volvé a cargarlo; "
             "mientras tanto no se puede procesar.")
    st.dataframe(faltantes, hide_index=True, width="stretch")
else:
    st.caption("✔ Todos los conceptos del informe tienen correspondencia en el listado.")
with st.expander("Ver el listado en uso"):
    st.dataframe(conceptos_df.rename(columns={"codigo": "Código liquidación", "descripcion": "Descripción", "columna": "Columna",
                                              "tipo": "Tipo IPS (aplicado)", "tipo_original": "Tipo en el archivo",
                                              "ips": "Concepto IPS (SAP)"}),
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------- padrón
st.subheader("3. Padrón de agentes (datos de SAP que no están en Nacional)")
st.caption("Cada legajo equivale a un cargo de SAP. Los legajos nuevos se cargan con valores de PRUEBA "
           "(marcados con valor_prueba = SI) hasta que cargues los reales.")
if "padron_base" not in st.session_state:
    st.session_state["padron_base"] = cargar_padron()
cargado = st.file_uploader("Cargar un padrón guardado (.xlsx)", type=["xlsx"], key="padron_up")
if cargado is not None:
    huella = hashlib.md5(cargado.getvalue()).hexdigest()
    if st.session_state.get("_padron_huella") != huella:
        st.session_state["_padron_huella"] = huella
        st.session_state["padron_base"] = cargar_padron(io.BytesIO(cargado.getvalue()))
        st.rerun()

padron = completar_padron(lectura.recibos, st.session_state["padron_base"])
hall_ant, ant_huella = [], ""
if ant_subido is not None:
    try:
        ant_bytes = ant_subido.getvalue()
        ant_huella = hashlib.md5(ant_bytes).hexdigest()
        listado_ant, hall_ant = cargar_antiguedad(io.BytesIO(ant_bytes), periodo)
        if not any(h.nivel == "ERROR" for h in hall_ant):
            padron, h2, n_ant = aplicar_antiguedad(padron, listado_ant, lectura.recibos)
            hall_ant += h2
            st.success(f"Antigüedad del listado aplicada a {n_ant} de {len(lectura.recibos)} legajos.")
    except ValueError as e:
        hall_ant = []
        st.error(f"No pude usar el listado de antigüedad: {e}")
    for h in hall_ant:
        {"ERROR": st.error, "ADVERTENCIA": st.warning}.get(h.nivel, st.info)(f"{h.legajo} · {h.campo}: {h.mensaje}")
for c in NUMERICAS + ["dias_inasistencia"]:
    padron[c] = pd.to_numeric(padron[c], errors="coerce")
padron["valor_prueba"] = padron["valor_prueba"].map(lambda v: "SI" if str(v).upper() == "SI" else "NO")
for c in ("nro_cargo", "encuadre", "modalidad"):
    padron[c] = padron[c].astype(str)
cfg_num = lambda t, mx, paso=1: st.column_config.NumberColumn(t, min_value=0, max_value=mx, step=paso)  # noqa: E731
padron_edit = st.data_editor(
    padron, hide_index=True, width="stretch", key="editor_padron",
    disabled=["legajo", "cuil", "nombre"],
    column_config={
        "legajo": "Legajo", "cuil": "CUIL", "nombre": "Apellido y nombre",
        "nro_cargo": st.column_config.TextColumn("Nº cargo SAP", max_chars=4),
        "antig_admin_anios": cfg_num("Antig. admin. (años)", 99),
        "antig_admin_meses": cfg_num("Antig. admin. (meses)", 11),
        "antig_otras_cajas_anios": cfg_num("Otras cajas (años)", 99),
        "antig_otras_cajas_meses": cfg_num("Otras cajas (meses)", 11),
        "antig_docente_anios": cfg_num("Antig. docente (años)", 99),
        "antig_docente_meses": cfg_num("Antig. docente (meses)", 11),
        "dias_inasistencia": cfg_num("Días inasist. c/desc.", 99.9, 0.5),
        "encuadre": st.column_config.SelectboxColumn("Encuadre", options=list(config.ENCUADRES), required=True),
        "modalidad": st.column_config.SelectboxColumn("Modalidad", options=list(config.MODALIDADES), required=True),
        "valor_prueba": st.column_config.SelectboxColumn("Valor de prueba", options=["SI", "NO"], required=True),
    },
)
c1, c2, _ = st.columns([1, 1, 3])
if c1.button("Guardar padrón"):
    st.session_state["padron_base"] = padron_edit.copy()
    st.success(f"Padrón guardado en {guardar_padron(padron_edit)}")
c2.download_button("Descargar padrón", _xlsx_bytes(padron_edit), "padron_agentes.xlsx", XLSX)

# ---------------------------------------------------------------- procesar
st.subheader("4. Procesar")
firma = hashlib.md5(repr((datos, p, padron_edit.to_csv(), conceptos_huella, ant_huella)).encode()).hexdigest()
if st.button("Procesar archivo", type="primary", disabled=len(faltantes) > 0):
    with st.spinner("Procesando…"):
        try:
            origen = io.BytesIO(conceptos_origen.getvalue()) if isinstance(conceptos_origen, io.BytesIO) else conceptos_origen
            st.session_state["res"] = procesar(io.BytesIO(datos), p, padron_edit, conceptos_origen=origen, hoy=date.today())
            st.session_state["res_firma"] = firma
            st.session_state["res_params"] = p
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("res", None)
            st.error(f"No se pudo procesar: {e}")

res = st.session_state.get("res")
if res is None:
    st.stop()
if st.session_state.get("res_firma") != firma:
    st.warning("Cambiaron los parámetros, el padrón, el listado de conceptos o el archivo desde el último procesamiento. "
               "Volvé a procesar para actualizar el resultado.")
pr: Parametros = st.session_state["res_params"]

# ---------------------------------------------------------------- resultados
st.subheader("Resultado")
rs = res.resumen
m = st.columns(6)
m[0].metric("Recibos leídos", rs["recibos_leidos"])
m[1].metric("Legajos válidos", rs["legajos_validos"])
m[2].metric("Legajos con errores", rs["legajos_con_errores"])
m[3].metric("Errores", rs["errores"])
m[4].metric("Advertencias", rs["advertencias"])
m[5].metric("Registros del TXT", rs["registros_generados"])
st.caption(f"Liquidación {pr.tipo_liquidacion} · DDJJ {pr.tipo_ddjj} · Nº {pr.nro_liquidacion} · período {pr.periodo} · "
           f"{rs['legajos_en_liquidacion']} cargos · LIQ total ${rs['total_liq']:,.2f} · formato {rs['formato']}")

if res.errores:
    st.error(f"Hay {len(res.errores)} error(es) bloqueante(s): no se puede generar el archivo hasta corregirlos.")
elif res.advertencias:
    st.warning(f"Hay {len(res.advertencias)} advertencia(s) para revisar antes de generar el archivo.")
else:
    st.success("Sin errores ni advertencias.")

t1, t2, t3, t4, t5 = st.tabs(["Vista previa", "Validación", "Ajustes (neteo y SAC)", "Control vs Nacional", "Totales de control"])
with t1:
    if len(res.vista):
        st.dataframe(res.vista.drop(columns=["Línea"]), hide_index=True, width="stretch")
        with st.expander("Ver las líneas tal como quedan en el TXT"):
            st.code("\n".join(res.lineas_txt), language=None)
    else:
        st.info("No se generaron líneas: corregí primero los errores bloqueantes.")
with t2:
    tabla = res.tabla_hallazgos()
    niveles = st.multiselect("Niveles", ["ERROR", "ADVERTENCIA", "INFO"], default=["ERROR", "ADVERTENCIA", "INFO"])
    st.dataframe(tabla[tabla["Nivel"].isin(niveles)], hide_index=True, width="stretch")
    st.download_button("Descargar validación (CSV)", tabla.to_csv(index=False).encode("utf-8-sig"),
                       "validacion.csv", "text/csv")
with t3:
    if len(res.ajustes):
        st.dataframe(res.ajustes, hide_index=True, width="stretch")
    else:
        st.info("No hubo ajustes por neteo de licencia ni separación de SAC.")
with t4:
    st.caption("Neto de Nacional = LIQ liquidación normal + LIQ SAC + asignaciones familiares que no integran LIQ.")
    st.dataframe(res.control, hide_index=True, width="stretch")
with t5:
    st.dataframe(totales_por_tipo(res), hide_index=True, width="stretch")

# ---------------------------------------------------------------- descarga
st.subheader("5. Generar archivo")
confirmo = True
if res.advertencias:
    confirmo = st.checkbox("Revisé las advertencias y quiero generar el archivo igualmente")
habilitado = res.puede_generar and confirmo and st.session_state.get("res_firma") == firma
d1, d2, d3 = st.columns(3)
zip_nombre = escritor.nombre_zip(pr)
d1.download_button(f"Descargar {zip_nombre}", escritor.crear_zip(res.lineas_txt) if res.lineas_txt else b"",
                   zip_nombre, "application/zip", disabled=not habilitado, type="primary")
d2.download_button("Descargar SALARIO.TXT", escritor.txt_bytes(res.lineas_txt) if res.lineas_txt else b"",
                   "SALARIO.TXT", "text/plain", disabled=not habilitado)
d3.download_button("Descargar informe de validación (Excel)", informe_excel(res, pr),
                   f"informe_validacion_{pr.periodo.replace('/', '')}_{pr.tipo_ddjj}{pr.tipo_liquidacion}_{pr.nro_liquidacion}.xlsx",
                   XLSX)
if not habilitado:
    st.caption("El ZIP y el TXT se habilitan cuando no hay errores bloqueantes, se confirmaron las advertencias y el "
               "resultado corresponde a los parámetros actuales.")
