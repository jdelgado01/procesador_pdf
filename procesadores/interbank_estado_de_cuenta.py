import pdfplumber
import pandas as pd
import re
import io

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de estado de cuenta del IBK.
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general y movimientos
    """
    pdf_stream = io.BytesIO(pdf_bytes)
    full_text = ""
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if text:
                full_text += "\n" + text

    # Extraer nombre del cliente
    def extraer_cliente(texto: str) -> str:
        lineas = texto.splitlines()
        for i, linea in enumerate(lineas):
            if re.search(r'\d{4}\s\d{2}\*\*\s\*{4}\s\d{4}', linea):
                if i + 1 < len(lineas):
                    posible_nombre = lineas[i + 1].strip()
                    if re.match(r'^[A-ZÑÁÉÍÓÚ\s]{5,}$', posible_nombre):
                        return posible_nombre
        return None

    cliente = extraer_cliente(full_text)

    # Fechas de ciclo
    match_fechas = re.search(r'del\s+(\d{2}/\d{2}/\d{4})\s+al\s+cierre\s+de\s+(\d{2}/\d{2}/\d{4})', full_text, re.IGNORECASE)
    fecha_inicio_ciclo, fecha_fin_ciclo = match_fechas.groups() if match_fechas else (None, None)

    # Fecha límite de pago
    match_inicio_seccion = re.search(r'ÚLTIMO DÍA DE PAGO', full_text, re.IGNORECASE)
    ultimodia_pago = None
    if match_inicio_seccion:
        texto_despues_seccion = full_text[match_inicio_seccion.end():]
        match_fecha = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', texto_despues_seccion)
        if match_fecha:
            ultimodia_pago = match_fecha.group(1)

    # Pago del mes y mínimo
    match_pago_mes = re.search(r'PAGO DEL MES.*?=\s*([\d,]+\.\d{2})', full_text)
    pago_total_soles = match_pago_mes.group(1) if match_pago_mes else None

    match_pago_min = re.search(r'PAGO M[IÍ]NIMO.*?=\s*([\d,]+\.\d{2})', full_text)
    pago_minimo_soles = match_pago_min.group(1) if match_pago_min else None

    # Otros campos
    match_pago_mes_usd = re.search(r'US\$ ([\d,]+\.\d{2})\s*\n\s*', full_text)
    pago_total_usd = match_pago_mes_usd.group(1) if match_pago_mes_usd else None
    match_pago_min_usd = re.search(r'US\$ ([\d,]+\.\d{2})', full_text)
    pago_minimo_usd = match_pago_min_usd.group(1) if match_pago_min_usd else None

    fila = [cliente, fecha_inicio_ciclo, fecha_fin_ciclo, ultimodia_pago, pago_total_soles, pago_total_usd, pago_minimo_soles, pago_minimo_usd]
    info_general = pd.DataFrame([fila], columns=[
        'Nombre Cliente', 'Fecha Inicio', 'Fecha Cierre', 'Ultimo dia pago',
        'Pago Total Soles', 'Pago Total USD', 'Pago Minimo Soles', 'Pago Minimo USD'
    ])

    # Movimientos
    pattern = r'^(\d{2}-[A-Za-z]{3})\s+(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$'
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
                    fecha = match1.group(1)
                    comercio = match1.group(2)
                    monto_soles = match1.group(3)
                    monto_usd = match1.group(4)
                    data.append([pg, fecha, comercio, monto_soles, monto_usd])

    monto = pd.DataFrame(data, columns=[
        'Página', 'Fecha Consumo', 'Descripción', 'Monto Soles', 'Monto USD'
    ])

    output = {
        'Resumen': info_general.reset_index(drop=True).to_dict(orient='records'),
        'Movimientos': monto.reset_index(drop=True).to_dict(orient='records')
    }
    return output
