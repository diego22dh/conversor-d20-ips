"""Informe de validación descargable (Excel)."""
from __future__ import annotations

import io

import pandas as pd

from .pipeline import Resultado
from .transformador import Parametros


def totales_por_tipo(res: Resultado) -> pd.DataFrame:
    """Totales de control del archivo a generar, por tipo de concepto."""
    filas = []
    for tipo, nombre in (("RCA", "Remuneraciones con aportes"), ("RSA", "Remuneraciones sin aportes"),
                         ("AFA", "Asignaciones familiares"), ("DPS", "Descuento previsional (IPS)"),
                         ("DAS", "Descuento asistencial (obra social)"), ("DES", "Otros descuentos"),
                         ("LIQ", "Líquido")):
        rs = [r for r in res.registros if r.tipo == tipo]
        filas.append({"Tipo": tipo, "Descripción": nombre, "Registros": len(rs),
                      "Importe total": float(sum(r.importe for r in rs))})
    return pd.DataFrame(filas)


def informe_excel(res: Resultado, p: Parametros) -> bytes:
    resumen = pd.DataFrame([
        ("Código de empleador", p.codigo_empleador), ("Período", p.periodo),
        ("Tipo de liquidación", p.tipo_liquidacion), ("Tipo de DDJJ", p.tipo_ddjj),
        ("Número de liquidación", p.nro_liquidacion),
        *[(k.replace("_", " ").capitalize(), v) for k, v in res.resumen.items()],
        ("Se puede generar el TXT", "SI" if res.puede_generar else "NO"),
    ], columns=["Dato", "Valor"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        resumen.to_excel(xw, sheet_name="Resumen", index=False)
        totales_por_tipo(res).to_excel(xw, sheet_name="Totales de control", index=False)
        res.tabla_hallazgos().to_excel(xw, sheet_name="Validación", index=False)
        res.ajustes.to_excel(xw, sheet_name="Ajustes (neteo y SAC)", index=False)
        res.control.to_excel(xw, sheet_name="Control vs Nacional", index=False)
        if len(res.vista):
            res.vista.drop(columns=["Línea"]).to_excel(xw, sheet_name="Vista previa", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ancho = max(len(str(c.value)) if c.value is not None else 0 for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(ancho + 2, 10), 70)
    return buf.getvalue()
