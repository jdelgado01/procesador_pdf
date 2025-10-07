import pdfplumber
import pandas as pd
import re
import os
from io import BytesIO

def split_transaction(transaction_string):
    pattern = r'(\d{1,2}\w{3})\s+(\d{1,2}\w{3})\s+(.+?)\s+([\d,\.]+-?)$'
    match = re.match(pattern, transaction_string)
    if match:
        return [match.group(1), match.group(2), match.group(3), match.group(4)]
    return None

def separar_ciclo(line):
    pattern = r'(\d{3}-\d{2}[A-Za-z]{2}-[A-Za-z]{4}-\d{4})\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})'
    match = re.search(pattern, line)
    if match:
        return match.groups()
    return None

def separar_transaccion(transaction_line):
    pattern = r'(\d{2}[A-Za-z]{3})\s+(\d{2}[A-Za-z]{3})\s+([A-Za-z0-9*/ ]+)\s+(\d+\.\d{2})\s+(\d{2}/\d{2})\s+(\d+\.\d{2}\s*%)\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})'
    match = re.match(pattern, transaction_line)
    if match:
        return match.groups()
    return None

def extraer_montos(text):
    pattern = r'[\d,]+\.\d{2}'
    text_clean = text.replace(',', '')
    montos = re.findall(pattern, text_clean)
    return montos

def abrir_pdf(pdf_input):
    """
    Abre el PDF desde una ruta o desde un objeto bytes/file-like.
    """
    if isinstance(pdf_input, (str, os.PathLike)):
        return pdfplumber.open(pdf_input)
    elif isinstance(pdf_input, bytes):
        return pdfplumber.open(BytesIO(pdf_input))
    elif hasattr(pdf_input, 'read'):
        return pdfplumber.open(pdf_input)
    else:
        raise ValueError("pdf_input debe ser una ruta, bytes o file-like object.")

def procesar_movimientos(pdf_input):
    transactions = []
    with abrir_pdf(pdf_input) as pdf:
        for page in pdf.pages:
            pg = str(page.page_number)
            text = page.extract_text()
            lines = text.split('\n')
            i = 0
            tarjeta = inicio = fin = limite = pago_min_soles = pago_total_soles = pago_min_usd = pago_total_usd = saldo_anterior = None
            for line in lines:
                if '-XXXX' in line:
                    ciclo = separar_ciclo(line)
                    if ciclo:
                        tarjeta, inicio, fin = ciclo
                if 'Fecha límite de pago' in line:
                    limite = lines[i+1] if i+1 < len(lines) else None
                if 'Pago mínimo S/' in line:
                    montos = extraer_montos(lines[i+1]) if i+1 < len(lines) else []
                    if len(montos) >= 2:
                        pago_min_soles = montos[0]
                        pago_total_soles = montos[1]
                if 'Pago mínimo US$' in line:
                    montos = extraer_montos(lines[i+1]) if i+1 < len(lines) else []
                    if len(montos) >= 2:
                        pago_min_usd = montos[0]
                        pago_total_usd = montos[1]
                if "SALDO ANTERIOR" in line:
                    saldo_match = re.search(r'[\d.,]+', line)
                    if saldo_match:
                        saldo_anterior = saldo_match.group(0).replace(',', '')
                if any(keyword in line for keyword in ['CONSUMO', 'PAGOSERVIC', ' PAGO','CARGO','DEVOLUCIÓN']):
                    columns = split_transaction(line)
                    if columns:
                        columns.append(pg)
                        columns.append(tarjeta)
                        columns.append(inicio)
                        columns.append(fin)
                        columns.append(limite)
                        columns.append(pago_min_soles)
                        columns.append(pago_total_soles)
                        columns.append(pago_min_usd)
                        columns.append(pago_total_usd)
                        columns.append(saldo_anterior)
                        transactions.append(columns)
                i += 1
    df = pd.DataFrame(transactions, columns=[
        'Fecha de Proceso', 'Fecha de Consumo', 'Descripción', 'Monto','Pagina', 'Tarjeta',
        'Inicio ciclo facturación', 'Fin ciclo facturación', 'Fecha límite de pago', 'Pago mínimo S/',
        'Pago total S/.', 'Pago mínimo US$', 'Pago total US$','Saldo Anterior'
    ])
    columnas_fecha = ['Inicio ciclo facturación', 'Fin ciclo facturación', 'Fecha límite de pago']
    for col in columnas_fecha:
        df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
    meses = {
        'Ene': 'Jan', 'Feb': 'Feb', 'Mar': 'Mar', 'Abr': 'Apr', 'May': 'May', 'Jun': 'Jun',
        'Jul': 'Jul', 'Ago': 'Aug', 'Set': 'Sep', 'Sep': 'Sep', 'Oct': 'Oct', 'Nov': 'Nov', 'Dic': 'Dec'
    }
    def convertir_fecha(fecha_str, inicio_str):
        if not isinstance(fecha_str, str) or not isinstance(inicio_str, str):
            return pd.NaT
        for esp, eng in meses.items():
            if esp in fecha_str:
                fecha_str = fecha_str.replace(esp, eng)
                break
        try:
            año = pd.to_datetime(inicio_str, dayfirst=True).year
            return pd.to_datetime(f"{fecha_str}{año}", format="%d%b%Y", errors='coerce')
        except:
            return pd.NaT
    df['Fecha de Proceso'] = df.apply(lambda row: convertir_fecha(row['Fecha de Proceso'], str(row['Inicio ciclo facturación'])), axis=1)
    df['Fecha de Consumo'] = df.apply(lambda row: convertir_fecha(row['Fecha de Consumo'], str(row['Inicio ciclo facturación'])), axis=1)
    df['Inicio ciclo facturación'] = df['Inicio ciclo facturación'].dt.date
    df['Fin ciclo facturación'] = df['Fin ciclo facturación'].dt.date
    df['Fecha límite de pago'] = df['Fecha límite de pago'].dt.date
    df['Fecha de Proceso'] = df['Fecha de Proceso'].dt.date
    df['Fecha de Consumo'] = df['Fecha de Consumo'].dt.date
    columnas_monto = ['Pago mínimo S/', 'Pago total S/.', 'Pago mínimo US$', 'Pago total US$', 'Saldo Anterior']
    def limpiar_a_float(valor):
        if pd.isna(valor):
            return None
        return float(str(valor).replace(',', '').replace('S/.', '').replace('$', '').strip())
    for col in columnas_monto:
        df[col] = df[col].apply(limpiar_a_float)
    def procesar_monto(valor):
        if pd.isna(valor):
            return None
        valor_str = str(valor).strip()
        negativo = valor_str.endswith('-')
        valor_str = valor_str.replace('-', '')
        try:
            valor_float = float(valor_str.replace(',', ''))
        except:
            return None
        return -valor_float if negativo else valor_float
    df['Monto'] = df['Monto'].apply(procesar_monto)
    base_movimiento = [ 'Pagina', 'Inicio ciclo facturación', 'Fin ciclo facturación', 'Fecha límite de pago', 'Pago mínimo S/', 'Pago total S/.','Pago mínimo US$',
                   'Pago total US$','Fecha de Proceso', 'Fecha de Consumo', 'Saldo Anterior','Descripción','Monto']
    df_movimientos = df[base_movimiento]
    return df_movimientos

def procesar_cuotas(pdf_input, df_mov):
    transactions = []
    with abrir_pdf(pdf_input) as pdf:
        for page in pdf.pages:
            pg = str(page.page_number)
            text = page.extract_text()
            lines = text.split('\n')
            i = 0
            for line in lines:
                if 'DETALLE PLAN CUOTAS SOLES' in line:
                    d = 'PLAN CUOTAS SOLES'
                    j = 2
                    while i + j < len(lines):
                        transaction_line = lines[i + j]
                        if '%' in transaction_line:
                            transaction_line_clean = transaction_line.replace(',', '')
                            columns = separar_transaccion(transaction_line_clean)
                            if columns:
                                columns = list(columns)
                                columns.append(pg)
                                columns.append(d)
                                transactions.append(columns)
                        else:
                            break
                        j += 1
                i += 1
    dfw = pd.DataFrame(transactions, columns=[
        'Fecha de Proceso', 'Fecha de Consumo', 'Descripción', 'Compras','NroCuota', 'TEA',
        'capital', 'intereses', 'total', 'Pagina', 'plan cuotas SOLES'
    ])
    dfw['Pagina'] = dfw['Pagina'].astype(str)
    df_mov['Pagina'] = df_mov['Pagina'].astype(str)
    dfw = dfw.merge(df_mov[['Pagina', 'Fin ciclo facturación']], on='Pagina', how='left')
    dfw.drop_duplicates(inplace=True)
    dfw['TEA'] = dfw['TEA'].str.replace('%', '', regex=False).str.strip()
    columnas_float = ['Compras', 'capital', 'TEA','intereses', 'total']
    for col in columnas_float:
        dfw[col] = pd.to_numeric(dfw[col], errors='coerce')
    meses = {
        'Ene': 'Jan', 'Feb': 'Feb', 'Mar': 'Mar', 'Abr': 'Apr', 'May': 'May', 'Jun': 'Jun',
        'Jul': 'Jul', 'Ago': 'Aug', 'Set': 'Sep', 'Sep': 'Sep', 'Oct': 'Oct', 'Nov': 'Nov', 'Dic': 'Dec'
    }
    def convertir_fecha(fecha_str, inicio_str):
        if not isinstance(fecha_str, str) or not isinstance(inicio_str, str):
            return pd.NaT
        for esp, eng in meses.items():
            if esp in fecha_str:
                fecha_str = fecha_str.replace(esp, eng)
                break
        try:
            año = pd.to_datetime(inicio_str, dayfirst=True).year
            return pd.to_datetime(f"{fecha_str}{año}", format="%d%b%Y", errors='coerce')
        except:
            return pd.NaT
    dfw['Fecha de Proceso'] = dfw.apply(lambda row: convertir_fecha(row['Fecha de Proceso'], str(row['Fin ciclo facturación'])), axis=1)
    dfw['Fecha de Consumo'] = dfw.apply(lambda row: convertir_fecha(row['Fecha de Consumo'], str(row['Fin ciclo facturación'])), axis=1)
    dfw['Fecha de Proceso'] = dfw['Fecha de Proceso'].dt.date
    dfw['Fecha de Consumo'] = dfw['Fecha de Consumo'].dt.date
    base_cuotas = [ 'Pagina', 'Fecha de Proceso', 'Fecha de Consumo', 'plan cuotas SOLES', 'Descripción', 'Compras' ,'NroCuota','TEA',
                   'capital','intereses', 'total']
    df_cuotas = dfw[base_cuotas]
    df_cuotas.rename(columns={'TEA': 'TEA%'}, inplace=True)
    return df_cuotas

def procesar_documento(pdf_input):
    """
    Procesa el documento PDF y retorna un diccionario con DataFrames de resumen y cuotas.
    """
    df_movimientos = procesar_movimientos(pdf_input)
    df_cuotas = procesar_cuotas(pdf_input, df_movimientos)

    # Crear resumen tipo Excel: encabezado + filas de movimientos
    resumen_rows = [df_movimientos.columns.tolist()] + df_movimientos.astype(str).values.tolist()
    movimientos_rows = [df_cuotas.columns.tolist()] + df_cuotas.astype(str).values.tolist()

    # Insertar una fila vacía entre ambos bloques
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + movimientos_rows

    # Rellenar columnas si es necesario
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo.reset_index(drop=True),
        'Cuotas': df_cuotas.reset_index(drop=True)
    }
    return output
