import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de préstamo Interbank.
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general y detalle de cuotas
    """
    pdf_stream = io.BytesIO(pdf_bytes)
    datos = []
    # INFORMACIÓN GENERAL
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if not text:
                continue
            full_text = ' '.join(text.split('\n'))
            cliente_match = re.search(r'(\d{10}\s*-\s*[A-ZÁÉÍÓÚÑ]+\s+[A-ZÁÉÍÓÚÑ\s]+)', full_text)
            fecha_match = re.search(r'Fecha Desembolso\s*:\s*(\d{2}/\d{2}/\d{4})', full_text)
            monto_match = re.search(r'Monto Crédito\s*:\s*([\d,\.]+)', full_text)
            saldo_match = re.search(r'Saldo Crédito\s*:\s*([\d,\.]+)', full_text)
            tasa_match = re.search(r'Tasa Interés\s*:\s*([\d\.]+)', full_text)
            tce_match = re.search(r'T\.C\.E\.\s*:\s*([\d\.]+)', full_text)
            plazo_match = re.search(r'Plazo\s*:\s*(\d+)', full_text)
            if all([cliente_match, fecha_match, monto_match, saldo_match, tasa_match, tce_match, plazo_match]):
                fecha = datetime.strptime(fecha_match.group(1), "%d/%m/%Y").date()
                cliente = cliente_match.group(1).strip()
                monto = float(monto_match.group(1).replace(',', ''))
                saldo = float(saldo_match.group(1).replace(',', ''))
                tasa = float(tasa_match.group(1))
                tce = float(tce_match.group(1))
                plazo = int(plazo_match.group(1))
                datos.append([fecha, cliente, monto, saldo, tasa, tce, plazo])
                break
    df_general = pd.DataFrame(datos, columns=[
        'FECHA DESEMBOLSO', 'Cliente', 'Monto Crédito', 'Saldo Crédito', 'Tasa Interés', 'T.C.E.', 'Plazo'
    ])

    # DETALLE DE CUOTAS
    pattern = re.compile(
        r'(\d+)\s+'                              # Nro cuota
        r'(\d{2}/\d{2}/\d{4})\s+'                # Fecha Vencimiento
        r'(\d{2}/\d{2}/\d{4})\s+'                # Fecha Pago
        r'(\d{2}/\d{2}/\d{4})\s+'                # Fecha Proceso
        r'([\d.,]+)\s+'                          # Amortización
        r'([\d.,]+)\s+'                          # Interés
        r'([\d.,]+)\s+'                          # Seguro Desgravamen
        r'([\d.,]+)\s+'                          # Seguro Bien
        r'([\d.,]+)\s+'                          # Comisión
        r'([\d.,]+)\s+'                          # Portes
        r'([\d.,]+)\s+'                          # Penalidad Incumplimiento
        r'([\d.,]+)\s+'                          # Compensatorio
        r'([\d.,]+)\s+'                          # Pen. Mora
        r'([\d.,]+)\s+'                          # Gastos Tramitación
        r'([\d.,]+)\s+'                          # Total
        r'([A-Z\s]+?)\s+'                        # Estado
        r'([A-Z\s]+)'                            # Tipo de pago
    )
    data = []
    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            pg = str(page.page_number)
            if not text:
                continue
            lines = text.split('\n')
            for line in lines:
                match1 = re.match(pattern, line)
                if match1:
                    numero_cuota = int(match1.group(1))
                    fecha_vencimiento = datetime.strptime(match1.group(2), "%d/%m/%Y").date()
                    fecha_pago = datetime.strptime(match1.group(3), "%d/%m/%Y").date()
                    fecha_proceso = datetime.strptime(match1.group(4), "%d/%m/%Y").date()
                    amortizacion = float(match1.group(5).replace(',', ''))
                    interes = float(match1.group(6).replace(',', ''))
                    segurodes = float(match1.group(7).replace(',', ''))
                    segurobien = float(match1.group(8).replace(',', ''))
                    comisiones = float(match1.group(9).replace(',', ''))
                    portes = float(match1.group(10).replace(',', ''))
                    Pen_Incu_Pago = float(match1.group(11).replace(',', ''))
                    I_compensatorio = float(match1.group(12).replace(',', ''))
                    pen_mora = float(match1.group(13).replace(',', ''))
                    Gastos_tramitacion = float(match1.group(14).replace(',', ''))
                    Total = float(match1.group(15).replace(',', ''))
                    Estado = match1.group(16)
                    Tipo_pago = match1.group(17)
                    data.append([
                        pg, numero_cuota, fecha_vencimiento, fecha_pago, fecha_proceso,
                        amortizacion, interes, segurodes, segurobien, comisiones, portes,
                        Pen_Incu_Pago, I_compensatorio, pen_mora, Gastos_tramitacion,
                        Total, Estado, Tipo_pago
                    ])
    columns = [
        'Página', 'Cuota', 'Fecha Vcto', 'Fecha Pago', 'Fecha Proceso', 'Amortización', 'Interés',
        'Seguro Desgravamen', 'Seguro Bien', 'Comision', 'Portes', 'Pen. Incu.Pago',
        'I. Compensatorio', 'Pen.Mora', 'Gastos Tramitación', 'Total', 'Estado', 'Tipo Pago'
    ]
    df_detalle = pd.DataFrame(data, columns=columns)

    # Calcular totales de columnas numéricas y agregar fila de totales
    columnas_numericas = [
        'Amortización', 'Interés', 'Seguro Desgravamen', 'Seguro Bien',
        'Comision', 'Portes', 'Pen. Incu.Pago', 'I. Compensatorio',
        'Pen.Mora', 'Gastos Tramitación'
    ]
    total = df_detalle[columnas_numericas].sum()
    fila_total = []
    for col in df_detalle.columns:
        if col == 'Fecha Proceso':
            fila_total.append('Totales')
        elif col in columnas_numericas:
            fila_total.append(total[col])
        else:
            fila_total.append('')
    total_row = pd.DataFrame([fila_total], columns=df_detalle.columns)
    df_detalle = pd.concat([df_detalle, total_row], ignore_index=True)

    # Unir df_general y df_detalle en una sola página tipo Excel
    # Convertir ambos DataFrames a listas de filas
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    detalle_rows = [df_detalle.columns.tolist()] + df_detalle.astype(str).values.tolist()
    
    # Insertar una fila vacía entre ambos bloques
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + detalle_rows

    # Crear un DataFrame combinado (rellenando columnas si es necesario)
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo.reset_index(drop=True)
    }

    return output
