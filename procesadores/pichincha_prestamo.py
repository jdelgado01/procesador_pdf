import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de préstamo Pichincha.
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general y detalle de cuotas
    """
    pdf_stream = io.BytesIO(pdf_bytes)

    # INFORMACIÓN GENERAL
    datos = []
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if not text:
                continue

            full_text = ' '.join(text.split('\n'))

            cliente_match = re.search(r"Cliente\s*:\s*(.+?)\s*(?=Direccion\s*:|\n|$)", full_text)
            fecha_generacion_match = re.search(r"Fecha de Generacion\s*:\s*(\d{2}/\d{2}/\d{2})", full_text)
            monto_prestamo_match = re.search(r"Monto del Prestamo\s*:\s*PEN\s*([\d,]+\.\d{2})", full_text)
            tasa_interes_compensatorio_match = re.search(r"Tasa Interes Compensatorio Efectiva Anual:\s*([\d.,]+)\s*%", full_text)
            tasa_interes_moratorio_match = re.search(r"Tasa Interes Moratorio Nominal Anual\.?:\s*([\d.,]+)\s*%", full_text)
            tasa_seguro_desgravamen_match = re.search(r"Tasa Seguro Desgravamen\s*:\s*([\d.,]+)\s*%", full_text)
            numero_cuotas_match = re.search(r"Numero de Cuotas\s*:\s*(\d+)", full_text)

            if all([cliente_match, fecha_generacion_match, monto_prestamo_match, tasa_interes_compensatorio_match, tasa_interes_moratorio_match, tasa_seguro_desgravamen_match, numero_cuotas_match]):
                fecha = datetime.strptime(fecha_generacion_match.group(1), "%d/%m/%y").date()
                cliente = cliente_match.group(1).strip()
                monto = float(monto_prestamo_match.group(1).replace(',', ''))
                tasa = float(tasa_interes_compensatorio_match.group(1).replace(',', ''))
                mora = float(tasa_interes_moratorio_match.group(1).replace(',', ''))
                des = float(tasa_seguro_desgravamen_match.group(1).replace(',', ''))
                nro = int(numero_cuotas_match.group(1))

                datos.append([fecha, cliente, monto, tasa, mora, des, nro])
                break

    df_tasas = pd.DataFrame(datos, columns=[
        'Fecha de Generacion', 'Cliente', 'Monto del Prestamo',
        'Tasa Interes Compensatorio Efectiva Anual',
        'Tasa Interes Moratorio Nominal Anual',
        'Tasa Seguro Desgravamen', 'Numero de Cuotas'
    ])

    # DETALLE DE CUOTAS
    pattern = re.compile(
        r'(\d+)\s+'                                # Nº de cuota
        r'(\d{2}/\d{2}/\d{2})\s+'                  # Fecha de pago
        r'([\d.,]+)\s+'                            # Amortización
        r'([\d.,]+)\s+'                            # Intereses
        r'([\d.,]+)\s+'                            # Cuota de gracia
        r'([\d.,]+)\s+'                            # Envío físico estado de cuenta
        r'([\d.,]+)\s+'                            # Seguro de desgravamen
        r'([\d.,]+)\s+'                            # Seguro todo riesgo
        r'([\d.,]+)'                               # Valor de cuota
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
                line = re.sub(r'[^\S\r\n]{2,}', ' ', line.strip())
                match1 = pattern.search(line)
                if match1:
                    numero_cuota = int(match1.group(1))
                    fecha_de_pago = datetime.strptime(match1.group(2), "%d/%m/%y").date()
                    amortizacion = float(match1.group(3).replace(',', ''))
                    interes = float(match1.group(4).replace(',', ''))
                    gracia = float(match1.group(5).replace(',', ''))
                    envio_fisico = float(match1.group(6).replace(',', ''))
                    seguro_desgravamen = float(match1.group(7).replace(',', ''))
                    seguro_riesgo = float(match1.group(8).replace(',', ''))
                    valor_cuota = float(match1.group(9).replace(',', ''))
                    data.append([
                        pg, numero_cuota, fecha_de_pago, amortizacion, interes, gracia,
                        envio_fisico, seguro_desgravamen, seguro_riesgo, valor_cuota
                    ])

    columns = [
        'Página', 'N° de cuota', 'Fecha de Pago', 'Importe de Amortización', 'Importe de Intereses',
        'Cuota de Gracia', 'Envio Físico Est.de CTA.', 'Seguro Desgravamen', 'Seguro Riesgo',
        'Valor de Cuota'
    ]
    df_detalle = pd.DataFrame(data, columns=columns)

    # Agregar fila resumen
    columnas_numericas = [
        'Importe de Amortización', 'Importe de Intereses', 'Cuota de Gracia',
        'Envio Físico Est.de CTA.', 'Seguro Desgravamen', 'Seguro Riesgo', 'Valor de Cuota'
    ]
    total = df_detalle[columnas_numericas].sum()
    fila_total = []
    for col in df_detalle.columns:
        if col == 'Fecha de Pago':
            fila_total.append('Resumen')
        elif col in columnas_numericas:
            fila_total.append(total[col])
        else:
            fila_total.append('')
    total_row = pd.DataFrame([fila_total], columns=df_detalle.columns)
    df_detalle = pd.concat([df_detalle, total_row], ignore_index=True)

    # Crear DataFrame combinado para la hoja de resumen
    resumen_rows = [df_tasas.columns.tolist()] + df_tasas.astype(str).values.tolist()
    detalle_rows = [df_detalle.columns.tolist()] + df_detalle.astype(str).values.tolist()
    
    # Insertar fila vacía entre bloques
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + detalle_rows
    
    # Asegurar mismo número de columnas
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo.reset_index(drop=True)
    }

    return output
