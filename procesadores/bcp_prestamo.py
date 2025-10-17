import pdfplumber
import pandas as pd
import re
from datetime import datetime
import io

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de préstamo del BCP
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general y detalle del préstamo
    """
    # Crear un objeto BytesIO para trabajar con los bytes del PDF
    pdf_stream = io.BytesIO(pdf_bytes)
    
    # INFORMACIÓN GENERAL
    pattern_tasas = (
        r'TASA DE INTERES COMPENSATORIA EFECTIVA ANUAL\s*\(?\d*\)?:\s*([\d.,]+)%.*?'
        r'COSTO EFECTIVO\s*:\s*([\d.,]+)%.*?'
        r'TASA ANUAL SEGURO DESGRAVAMEN\s*:\s*([\d.,]+)%.*?'
        r'TASA ANUAL SEGURO INMUEBLE\s*:\s*([\d.,]+)%'
    )
    pattern_fecha = r'FECHA DESEMBOLSO\s*:\s*(\d{2}/\d{2}/\d{2})'
    datos = []
    
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split('\n')
            
            # Buscar nombre del cliente
            for i, line in enumerate(lines):
                if "CREDITO NRO" in line.upper() and i >= 3:
                    nombre_cliente = lines[i - 3].strip()
                    break
                    
            full_text = ' '.join(lines)
            match_tasas = re.search(pattern_tasas, full_text)
            match_fecha = re.search(pattern_fecha, full_text)
            
            if match_tasas and match_fecha:
                fecha_str = match_fecha.group(1)
                fecha_date = datetime.strptime(fecha_str, "%d/%m/%y").date()
                
                tasa_interes = float(match_tasas.group(1).replace(',', '.'))
                costo_efectivo = float(match_tasas.group(2).replace(',', '.'))
                seguro_desgravamen = float(match_tasas.group(3).replace(',', '.'))
                seguro_inmueble = float(match_tasas.group(4).replace(',', '.'))
                
                datos.append([
                    nombre_cliente, fecha_date, tasa_interes, 
                    costo_efectivo, seguro_desgravamen, seguro_inmueble
                ])
                break

    df_general = pd.DataFrame(datos, columns=[
        'Nombre Cliente',
        'FECHA DESEMBOLSO',
        'TASA DE INTERES COMPENSATORIA EFECTIVA ANUAL',
        'COSTO EFECTIVO',
        'TASA ANUAL SEGURO DESGRAVAMEN',
        'TASA ANUAL SEGURO INMUEBLE'
    ])

    # DETALLE DE CUOTAS
    pattern = r'(\d+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'
    data = []
    
    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if not text:
                continue
            
            for line in text.split('\n'):
                match = re.match(pattern, line)
                if match:
                    fecha = match.group(1)
                    saldo = match.group(2)
                    amortizacion = match.group(3)
                    intereses = match.group(4)
                    segurodes = match.group(5)
                    segurobien = match.group(6)
                    comisiones = match.group(7)
                    cuota = match.group(8)
                    data.append([
                        fecha, saldo, amortizacion, intereses,
                        segurodes, segurobien, comisiones, cuota
                    ])

    df_detalle = pd.DataFrame(data, columns=[
        'Fecha', 'Saldo', 'Amortizacion', 'Intereses',
        'Seguro Desg.', 'Seguro Bien', 'Comisiones', 'Cuota'
    ])

    # Convertir columnas a tipos apropiados
    df_detalle['Fecha'] = pd.to_datetime(df_detalle['Fecha'], dayfirst=True).dt.date
    columnas_numericas = [
        'Saldo', 'Amortizacion', 'Intereses',
        'Seguro Desg.', 'Seguro Bien', 'Comisiones', 'Cuota'
    ]
    df_detalle[columnas_numericas] = df_detalle[columnas_numericas].replace({',': ''}, regex=True)
    df_detalle[columnas_numericas] = df_detalle[columnas_numericas].apply(pd.to_numeric)

    # Calcular totales
    total = df_detalle[columnas_numericas].sum()
    fila_total = ['TOTAL A PAGAR'] + total.tolist()
    total_row = pd.DataFrame([fila_total], columns=df_detalle.columns)
    df_detalle = pd.concat([df_detalle, total_row], ignore_index=True)

    # Combinar DataFrames en un solo resultado
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    detalle_rows = [df_detalle.columns.tolist()] + df_detalle.astype(str).values.tolist()
    
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + detalle_rows
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    return {
        'Resumen': df_resumen_completo.reset_index(drop=True)
    }
