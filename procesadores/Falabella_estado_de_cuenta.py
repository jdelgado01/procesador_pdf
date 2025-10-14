import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

def procesar_documento(pdf_bytes):
   
    pdf_stream = io.BytesIO(pdf_bytes)
    full_text = ""
    page_texts = []
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += "\n" + text
                page_texts.append((page.page_number, text))

    # INFORMACIÓN GENERAL
    pattern_montos = r"S/ ([\d,]+\.\d{2})\s+Pago mínimo del mes\s+.*?S/ ([\d,]+\.\d{2})\s+Pago total del mes"
    pattern_periodo = r"Periodo de facturación\s+(\d{2}/\d{2} al \d{2}/\d{2})"
    pattern_pago = r"Último día de pago\s+(\d{2}/\d{2}/\d{4})"
    pattern_cliente = r"Estado de Cuenta\s+([A-ZÁÉÍÓÚÑ ]+)"

    match_montos = re.search(pattern_montos, full_text, re.DOTALL)
    match_periodo = re.search(pattern_periodo, full_text)
    match_pago = re.search(pattern_pago, full_text)
    cliente_match = re.search(pattern_cliente, full_text)

    pago_minimo = match_montos.group(1) if match_montos else None
    pago_total = match_montos.group(2) if match_montos else None
    periodo_fact = match_periodo.group(1) if match_periodo else None
    ultimo_pago = match_pago.group(1) if match_pago else None
    cliente = cliente_match.group(1).strip() if cliente_match else None

    df_general = pd.DataFrame([{
        "Cliente": cliente,
        "Periodo de Facturación": periodo_fact,
        "Último Día de Pago": ultimo_pago,
        "Pago Mínimo": pago_minimo,
        "Pago Total": pago_total
    }])

    # MOVIMIENTOS
    pat_simple = re.compile(
        r"""(?m)^
            (\d{2}/\d{2}/\d{4})\s+          # fecha de transacción
            (\d{2}/\d{2}/\d{4})\s+          # fecha de proceso
            (                               # detalle
                (?:(?!\b\d{2}/\d{2}\b).)+?  # NO debe contener NN/NN
            )\s+
            (-?\d{1,3}(?:,\d{3})*\.\d{2})   # monto
            \s*$
        """,
        re.VERBOSE,
    )

    movimientos = []
    for page_num, text in page_texts:
        for trans_date, proc_date, detalle, monto in pat_simple.findall(text):
            try:
                fecha_trans = datetime.strptime(trans_date, "%d/%m/%Y").date()
                fecha_proc  = datetime.strptime(proc_date,  "%d/%m/%Y").date()
            except ValueError:
                continue
            monto_float = float(monto.replace(",", ""))
            movimientos.append([
                page_num,
                fecha_trans,
                fecha_proc,
                detalle.strip(),
                monto_float
            ])

    df_movimientos = pd.DataFrame(movimientos, columns=[
        "Página",
        "Fecha Transacción",
        "Fecha Proceso",
        "Detalle",
        "Monto (S/)"
    ])

    # CUOTAS
    date_line_pattern = re.compile(
        r"""^
            (\d{2}/\d{2}/\d{4})\s+            # FECHA DE TRANSACCIÓN
            (\d{2}/\d{2}/\d{4})\s+            # FECHA DE PROCESO
            (.*?)\s+                          # resto del detalle en la misma línea
            (-?\d{1,3}(?:,\d{3})*\.\d{2})\s+  # MONTO (S/)
            (\d{2}/\d{2})\s+                  # Nº CUOTA CARGADA
            ([\d.,]+)%?\s+                    # %TEA (*)
            (-?\d{1,3}(?:,\d{3})*\.\d{2})\s+  # CAPITAL (S/)
            (-?\d{1,3}(?:,\d{3})*\.\d{2})\s+  # INTERÉS (S/)
            (-?\d{1,3}(?:,\d{3})*\.\d{2})\s*  # TOTAL
            $""",
        re.VERBOSE,
    )

    records = []
    for page_num, text in page_texts:
        prev_line = ""
        for line in text.splitlines():
            m = date_line_pattern.match(line)
            if m:
                (f_trans, f_proc, middle, monto, ncuota,
                 tea, capital, interes, total) = m.groups()
                detail = (prev_line + " " + middle).strip()
                try:
                    tea_val = float(tea.replace(",", ".").replace("%", ""))
                except Exception:
                    tea_val = None
                records.append([
                    page_num,
                    f_trans,
                    f_proc,
                    detail,
                    float(monto.replace(",", "")),
                    ncuota,
                    tea_val,
                    float(capital.replace(",", "")),
                    float(interes.replace(",", "")),
                    float(total.replace(",", ""))
                ])
            prev_line = line

    df_cuotas = pd.DataFrame(records, columns=[
        "Página",
        "Fecha Transacción",
        "Fecha Proceso",
        "Detalle Transacción",
        "Monto (S/)",
        "Nº Cuota Cargada",
        "%TEA (*)",
        "Capital (S/)",
        "Interés (S/)",
        "Total"
    ])

    # Unir df_general y df_movimientos en una sola hoja tipo Excel
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    movimientos_rows = [df_movimientos.columns.tolist()] + df_movimientos.astype(str).values.tolist()
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + movimientos_rows
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        "Resumen": df_resumen_completo.reset_index(drop=True),
        "Cuotas": df_cuotas.reset_index(drop=True)
    }
    return output

if __name__ == "__main__":
    pdf_path = r'C:\Users\jdelgado\Desktop\python\ocr\PDF\FALABELLA\Estado de cuenta.pdf'
    output_excel = r'C:\Users\jdelgado\Desktop\python\Falabella_estado_de_cuenta.xlsx'

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    resultado = procesar_documento(pdf_bytes)

    with pd.ExcelWriter(output_excel) as writer:
        resultado["Resumen"].to_excel(writer, sheet_name="Resumen", index=False, header=False)
        resultado["Cuotas"].to_excel(writer, sheet_name="Cuotas", index=False)
    print(f"Exportado a {output_excel}")
