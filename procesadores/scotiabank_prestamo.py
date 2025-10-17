import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de préstamo del Scotiabank
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

            cuenta_match = re.search(r'Cuenta\s*:\s*(\d+)\s+(.*)', text)
            fecha_inicio_match = re.search(r'Fecha Inicio\s*:\s*(\d{2}/\d{2}/\d{2})', text)
            cuotas_match = re.search(r'Nro\.Cuotas\s*:\s*(\d+)', text)
            importe_total_match = re.search(r'Importe\s*:\s*S/\s*([\d.,]+)', text)
            tasa_efe_anual_match = re.search(r'Tasa Efe Anual\s*:\s*([\d.,]+)', text)
            tasa_coste_anual_match = re.search(r'Tasa Cos Efe Anual\s*:\s*([\d.,]+)', text)
            tasa_seguro_match = re.search(r'Tasa U\. Seg\. Desg\.\s*:\s*([\d.,]+)', text)

            if all([cuenta_match, fecha_inicio_match, cuotas_match, importe_total_match, 
                   tasa_efe_anual_match, tasa_coste_anual_match, tasa_seguro_match]):
                fecha = datetime.strptime(fecha_inicio_match.group(1), "%d/%m/%y").date()
                cuenta = cuenta_match.group(1).title()
                cliente = cuenta_match.group(2).title()
                importe = float(importe_total_match.group(1).replace('.', '').replace(',', '.'))
                tasa_efectiva = float(tasa_efe_anual_match.group(1).replace(',', '.'))
                tasa_coste = float(tasa_coste_anual_match.group(1).replace(',', '.'))
                tasa_seguro = float(tasa_seguro_match.group(1).replace(',', '.'))
                cuotas = int(cuotas_match.group(1))

                datos.append([cliente, cuenta, fecha, importe, tasa_efectiva, tasa_coste, tasa_seguro, cuotas])
                break

    df_general = pd.DataFrame(datos, columns=['Cliente', 'Cuenta', 'Fecha Inicio', 'Importe', 
                                            'Tasa Efe Anual', 'Tasa Cos Efe Anual', 
                                            'Tasa U. Seg. Desg.', 'Nro.Cuotas'])

    # DETALLE DE CUOTAS
    pattern = r'^(\d+)\s+(\d{2}/\d{2}/\d{2})\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([\d.,\-]+)\s+([A-Z]+)\s+(\d{2}/\d{2}/\d{2})$'
    data = []

    def convertir_valor(valor):
        valor = valor.strip()
        negativo = valor.endswith('-')
        valor = valor.replace('-', '')
        valor = valor.replace('.', '').replace(',', '.')
        return -float(valor) if negativo else float(valor)

    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            pg = page.page_number
            lines = text.split('\n')

            for line in lines:
                match = re.match(pattern, line.strip())
                if match:
                    data.append([
                        pg,
                        int(match.group(1)),
                        match.group(2),
                        match.group(3),
                        match.group(4),
                        match.group(5),
                        match.group(6),
                        match.group(7),
                        match.group(8),
                        match.group(9)
                    ])

    df_detalle = pd.DataFrame(data, columns=['Página', 'Cuota', 'Fecha Vencimiento', 
                                           'Capital', 'Intereses', 'Comisión', 'Seguros', 
                                           'Cuota Total', 'Estado', 'Fecha Pago'])

    # Convertir campos numéricos
    columnas_numericas = ['Capital', 'Intereses', 'Comisión', 'Seguros', 'Cuota Total']
    for col in columnas_numericas:
        df_detalle[col] = df_detalle[col].apply(convertir_valor)

    # Convertir fechas
    df_detalle['Fecha Vencimiento'] = pd.to_datetime(df_detalle['Fecha Vencimiento'], 
                                                    format='%d/%m/%y').dt.date
    df_detalle['Fecha Pago'] = pd.to_datetime(df_detalle['Fecha Pago'], 
                                             format='%d/%m/%y').dt.date

    # Crear DataFrame combinado para la hoja de resumen
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
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
