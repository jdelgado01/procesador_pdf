import pdfplumber
import pandas as pd
import re
import io
from datetime import datetime

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de préstamo del BBVA
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
            
            if "TOTALES--->" in text:
                break

            nombre = re.search(r'NOMBRE DEL SOLICITANTE\s*:\s*(.+)', text)
            numero_prestamo = re.search(r'NRO\. PRESTAMO\s*:\s*([\d\-]+)', text)
            fecha_formalización = re.search(r'FECHA DE FORMALIZACION\s*:\s*(\d{2}-\d{2}-\d{4})', text)
            importe_concedido = re.search(r'IMPORTE CONCEDIDO\s*:\s*([\d.,]+)', text)
            importe_retenido = re.search(r'IMPORTE RETENIDO\s*:\s*([\d.,]+)', text)
            tasa_efectiva = re.search(r'TASA EFECTIVA ANUAL\s*:\s*([\d.,]+)\s*%', text)
            tcea_ref = re.search(r'TASA COSTO EFECTIVO ANUAL REF\.OPER\.\s*:\s*([\d.,]+)%', text)
            plazo = re.search(r'PLAZO\s*:\s*(\d+)\s+MESES', text)

            if all([nombre, numero_prestamo, fecha_formalización, importe_concedido, 
                   importe_retenido, tasa_efectiva, tcea_ref, plazo]):
                cliente = nombre.group(1)
                numero = numero_prestamo.group(1)
                fecha = datetime.strptime(fecha_formalización.group(1), "%d-%m-%Y").date()
                importe_c = float(importe_concedido.group(1).replace(',', ''))
                importe_r = float(importe_retenido.group(1).replace(',', ''))
                tasa_e = float(tasa_efectiva.group(1).replace(',', '.'))
                tasa_r = float(tcea_ref.group(1).replace(',', '.'))
                cuotas = int(plazo.group(1))
                pagina = page.page_number

                datos.append([pagina, cliente, numero, fecha, importe_c, importe_r, tasa_e, tasa_r, cuotas])

    df_general = pd.DataFrame(datos, columns=['Página', 'Cliente', 'Nro. Prestamo', 
                                            'Fecha de Formalización', 'Importe Concedido', 
                                            'Importe Retenido', 'Tasa Efectiva Anual',
                                            'Tasa Costo Efectivo Anual REF.OPER.', 'Plazo'])
    df_general = df_general.drop_duplicates(subset=[col for col in df_general.columns if col != 'Página'])

    # DETALLE DE CUOTAS
    pattern = r'^\s*(\d+)\s+(\d{2}/\d{2}/\d{4})\s+([\d\.,]+)\s+([\d\.,]+|)\s+([\d\.,]+)\s+(\d+\.?\d*)\s*([\d\.,]*)\s*([\d\.,]*)\s+([\d\.,]+)\s*$'
    data = []

    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            pg = page.page_number
            lines = text.split('\n')

            for line in lines:
                match = re.match(pattern, line.strip())
                if match:
                    valores = []
                    for i in range(1, 10):
                        valor = match.group(i).strip()
                        valores.append(valor if valor != '' else '0')
                    
                    data.append([
                        pg,
                        int(valores[0]),     # Cuota
                        valores[1],          # Fecha Vencimiento
                        valores[2],          # Saldo
                        valores[3],          # Amortización
                        valores[4],          # Interés
                        valores[5],          # Comisión
                        valores[6],          # Seguro Desgrav.
                        valores[7],          # Otros Seguros
                        valores[8]           # Total a Pagar
                    ])

    df_detalle = pd.DataFrame(data, columns=['Página', 'Cuota', 'Fecha Vencimiento', 
                                           'Saldo', 'Amortización', 'Interés', 'Comisión', 
                                           'Seguro Desgrav.', 'Otros Seguros', 'Total a Pagar'])

    # Convertir campos numéricos
    columnas_numericas = ['Saldo', 'Amortización', 'Interés', 'Comisión', 
                         'Seguro Desgrav.', 'Otros Seguros', 'Total a Pagar']
    for col in columnas_numericas:
        df_detalle[col] = df_detalle[col].apply(lambda x: float(str(x).replace(',', '')))

    # Convertir fechas
    df_detalle['Fecha Vencimiento'] = pd.to_datetime(df_detalle['Fecha Vencimiento'], 
                                                    format='%d/%m/%Y').dt.date

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
