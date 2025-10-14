import pdfplumber
import pandas as pd
import re
import io

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de estado de cuenta Ripley.
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general y movimientos
    """
    pdf_stream = io.BytesIO(pdf_bytes)

    # INFORMACIÓN GENERAL-
    full_text = ""
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += "\n" + text

    # Extraer el nombre del cliente
    cliente_match = re.search(
        r"^\s*([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+){1,2})", full_text, re.MULTILINE)
    cliente = cliente_match.group(1).strip() if cliente_match else None

    # Extraer periodo de facturación y pago total del mes
    periodo_pago_match = re.search(
        r"(\d{2}/[A-Z]{3}/\d{4})-(\d{2}/[A-Z]{3}/\d{4})\s+S/\s*([\d,]+\.\d{2})", full_text)
    if periodo_pago_match:
        periodo_fact = f"{periodo_pago_match.group(1)} - {periodo_pago_match.group(2)}"
        pago_total = periodo_pago_match.group(3).replace(",", "")
    else:
        periodo_fact = None
        pago_total = None

    # Extraer último día de pago y monto mínimo del mes juntos en línea que contiene ambos
    pago_minimo = None
    ultimo_pago = None
    match_minimo = re.search(
        r"(\d{2}/[A-Z]{3}/\d{4})\s+S/\s*([\d,]+\.\d{2})", full_text)
    if match_minimo:
        ultimo_pago = match_minimo.group(1)
        pago_minimo = match_minimo.group(2).replace(",", "")

    df_general = pd.DataFrame({
        "Cliente": [cliente],
        "Periodo de Facturación": [periodo_fact],
        "Último Día de Pago": [ultimo_pago],
        "Pago Mínimo": [pago_minimo],
        "Pago Total": [pago_total],
    })

    # MOVIMIENTOS
    def extraer_movimientos_final(texto_lineas):
        regex = re.compile(
            r"(?P<fecha_consumo>\d{2}/[A-Z]{3}/\d{4})\s+"
            r"(?P<fecha_proceso>\d{2}/[A-Z]{3}/\d{4})\s+"
            r"(?P<ticket>\d{6})\s+"
            r"(?P<descripcion>.+?)\s+T\s+"
            r"(?P<monto>\d+\.\d{2})\s+"
            r"(?P<tea_tna>\d+\.\d{2}%)\s+"
            r"(?P<cuotas>\d{2}/\d{2})\s+"
            r"(?P<post_cuotas>\d+\.\d{2}(?:\s+\d+\.\d{2}){0,2})?",
            re.IGNORECASE
        )
        movimientos = []
        for linea, pagina in texto_lineas:
            match = regex.search(linea)
            if match:
                datos = match.groupdict()
                valores = datos.get("post_cuotas", "").split()
                valor_cuota = interes = total = None
                if len(valores) == 3:
                    valor_cuota, interes, total = valores
                elif len(valores) == 2:
                    valor_cuota, interes = valores
                elif len(valores) == 1:
                    if datos["cuotas"] == "01/01":
                        total = valores[0]
                    else:
                        valor_cuota = valores[0]
                movimientos.append([
                    pagina,  # Agregar página
                    datos.get("fecha_consumo"),
                    datos.get("fecha_proceso"),
                    datos.get("ticket"),
                    datos.get("descripcion"),
                    datos.get("monto"),
                    datos.get("tea_tna"),
                    datos.get("cuotas"),
                    valor_cuota,
                    interes,
                    total
                ])
        columnas = [
            "Página", "Fecha de consumo", "Fecha de proceso", "N° Ticket", "Descripción", "Monto",
            "TEA/TNA", "N° de cuotas", "Valor Cuota - Capital", "Valor Cuota - Interés", "Total"
        ]
        return pd.DataFrame(movimientos, columns=columnas)

    # Extraer líneas con estructura de movimientos y página
    texto_lineas = []
    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split("\n"):
                    if re.search(r"\d{2}/[A-Z]{3}/\d{4}", line) and " T " in line:
                        texto_lineas.append((line.strip(), str(page.page_number)))
    df_movimientos = extraer_movimientos_final(texto_lineas)

    # Unir df_general y df_movimientos en una sola hoja tipo Excel
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    movimientos_rows = [df_movimientos.columns.tolist()] + df_movimientos.astype(str).values.tolist()
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + movimientos_rows
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo.reset_index(drop=True)
    }
    return output

