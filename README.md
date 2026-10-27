# Conversor de Remuneraciones — Nacional Software a IPS D20 Digital

Aplicación Streamlit que toma el informe **«Recibos Agrupados por Empleado»** de Nacional Software y genera el
`SALARIO.TXT` (dentro del ZIP) que se sube **manualmente** a SAP › Información salarial › Enviar salarios.
No se conecta con el IPS.

## Cómo ejecutarla (Windows)
1. Instalar Python 3.11 o superior.
2. Doble clic en `iniciar.bat` (la primera vez crea el entorno e instala las dependencias).
3. Se abre el navegador. Alternativa manual: `pip install -r requirements.txt` y `streamlit run app.py`.

Pruebas: `python -m pytest`

## Flujo de uso
1. En la barra lateral elegí con desplegables: código de empleador, período (AAAA/MM), tipo de liquidación
   (N normal / A adicional-SAC), tipo de DDJJ y número de liquidación.
2. Subí el informe de Nacional (.xls o .xlsx). El período del informe se preselecciona.
   Opcionalmente subí también el **listado de empleados con antigüedad** (.xls/.xlsx): columnas Legajo y/o CUIL y
   Antigüedad docente (años y meses); opcionales antigüedad IPS y de otras cajas (años/meses), o fecha de ingreso
   docente (se calcula hasta fin de período, con advertencia). Se aplica sobre el padrón; los legajos que no estén
   en el listado conservan lo que tenga el padrón. Si el listado trae solo CUIL, todos los legajos de esa persona
   reciben la misma antigüedad.
   Se reconoce el **Listado de Empleados de Nacional**: con la columna *Fecha Antiguedad* (preferida sobre *Fecha
   Ingreso*) la antigüedad docente se calcula hasta el último día del período elegido (años y meses completos); si
   trae solo *Antiguedad* en años enteros, se informa con 00 meses. IPS y otras cajas no se modifican.
3. **Correspondencia de conceptos del colegio** (paso 2 en pantalla): cada colegio tiene sus propios códigos de
   liquidación. Cargá el archivo (.xls/.xlsx) con las columnas *código de liquidación*, *tipo de concepto IPS*
   (RCA/RSA/AFA/DPS/DAS/DES) y *concepto IPS (código SAP)*; descripción y columna son opcionales. Los
   encabezados se reconocen por nombre (hay un botón para bajar una planilla de ejemplo). «Guardar como listado
   de este colegio» lo deja en `data/conceptos/<código de empleador>.xlsx` y se usa automáticamente la próxima vez.
   Sin listado propio se usa el predeterminado (`data/conceptos_d20.xlsx`) con una advertencia. Si el informe trae
   conceptos que el listado no cubre, no se puede procesar y se muestra cuáles faltan.
4. Revisá/completá el **padrón de agentes** (cargo SAP, antigüedades, encuadre, modalidad, inasistencias).
   Los legajos nuevos entran con **valores de PRUEBA** (cargo 9001, 9002…, antigüedades 00, encuadre 13,
   modalidad P) hasta que cargues los reales. «Guardar padrón» lo deja en `data/padron_agentes.xlsx`.
5. **Procesar archivo** → métricas, validaciones, ajustes, control contra Nacional y totales.
6. Descargá `E060906_092026_ON_01.zip` (o el `SALARIO.TXT` solo) y el informe de validación en Excel.
   Con errores bloqueantes la descarga queda deshabilitada; con advertencias hay que confirmarlas.

Para el SAC: procesá de nuevo eligiendo tipo **A** (sugiere número 02).

## Reglas de conversión (confirmadas)
| Tema | Regla |
|---|---|
| Un legajo | = un cargo de SAP. Una persona con varios legajos informa cada uno por separado. |
| Concepto IPS / tipo | Del listado de correspondencia del colegio (uno por código de empleador). |
| Obra social 3% | Tipo **DAS**: todo concepto DES con código IPS **700000** se aplica como DAS, sea cual sea el código de liquidación del colegio. |
| Concepto empleador | Código de Nacional con ceros a la izquierda a 8 dígitos (`400` → `00000400`). |
| LIQ | Concepto IPS **100047**, concepto empleador configurable (por defecto `00009999`). |
| LIQ — fórmula | `RCA + RSA − DES − DPS − DAS` (AFA no integra LIQ salvo que se tilde la opción). |
| Licencia sin sueldo | Se **netea**: el importe negativo se descuenta de los conceptos positivos del mismo tipo, en proporción; los días van al campo «licencia sin goce» (`30` días → `300`). |
| Importes en cero | Se omiten (el instructivo pide > 0, salvo LIQ). Un cargo sin conceptos queda solo con LIQ 0,00 (advertencia). |
| SAC | Liquidación aparte (tipo A). Los descuentos que el informe calcula sobre sueldo + SAC se separan con la tasa de cada descuento (columna «unidad»). Códigos SAC editables (por defecto 100, 101, 103, 860). |
| Formato | 107 caracteres por línea (108 columnas). Si algún importe necesita 12 posiciones, **todas** las líneas pasan al formato de 110 columnas (109 caracteres). |
| Archivo | `SALARIO.TXT`, CRLF, sin línea vacía final, ASCII en mayúsculas (sin tildes ni ñ). |
| Nombre del ZIP | `Código_MMAAAA_<DDJJ><tipo>_<nº>.zip`. |

## Controles
- El bloque final de totales del informe de Nacional se excluye del detalle y se usa como control cruzado.
- Neto de Nacional = LIQ normal + LIQ SAC + AFA que no integra LIQ (por legajo, tolerancia de 1 centavo).
- CUIL con dígito verificador; período del informe vs. elegido; período no posterior al mes actual;
  concepto inexistente en el listado; columna del informe vs. tipo del listado; cargos repetidos dentro
  de un mismo CUIL; padrón (cargo, antigüedades, encuadre, modalidad); longitud de cada línea.
- Niveles: **ERROR** (bloquea), **ADVERTENCIA** (se confirma), **INFO**.

## Estructura
```
app.py                  interfaz Streamlit
conversor/lector.py     lectura del informe de Nacional
conversor/conceptos.py  listado de conceptos -> tipo / código IPS
conversor/padron.py     padrón de agentes (datos de SAP que no están en Nacional)
conversor/transformador.py  neteo, SAC, LIQ
conversor/validador.py  validaciones
conversor/escritor.py   ancho fijo, TXT y ZIP
conversor/pipeline.py   orquestación
conversor/informe.py    informe de validación en Excel
data/                   conceptos_d20.xlsx (predeterminado), conceptos/<colegio>.xlsx, parametros.json, padron_agentes.xlsx (se crea al guardar)
tests/                  pruebas con pytest (datos ficticios)
```

## Pendiente / a verificar con SAP
- Reemplazar los valores de prueba del padrón por los reales (SAP compara cargo, antigüedades,
  encuadre y modalidad contra lo que tiene cargado).
- Confirmar con un archivo aceptado por SAP: concepto empleador de LIQ y formato del concepto empleador.
- Las inasistencias con descuento se toman del padrón (el informe de Nacional no las trae).
