import pdfplumber
import pandas as pd
import re
import io

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de estado de cuenta del BBVA
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general, movimientos y cuotas
    """
    # Crear un objeto BytesIO para trabajar con los bytes del PDF
    pdf_stream = io.BytesIO(pdf_bytes)
    
    # INFORMACIÓN GENERAL
    registros = []
    segmentos_por_pagina, etiquetas, n = {}, {}, 1
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            if not text:
                continue

            lines = text.splitlines()
            fecha_cierre = None
            ultimo_diapago = None
            pago_mínimo_soles = pago_total_soles = None
            pago_mínimo_dolares = pago_total_dolares = None
            registro_idx = 0

            for line in lines:
                # Buscar fechas de cierre y último día de pago
                if not fecha_cierre or not ultimo_diapago:
                    fechas = re.findall(r'\d{2}/\d{2}/\d{4}', line)
                    if len(fechas) >= 2:
                        fecha_cierre, ultimo_diapago = fechas[:2]

                # Detectar línea con 7 montos
                valores = re.findall(r'-?\d{1,3}(?:,\d{3})*\.\d{2}', line)
                if len(valores) == 7:
                    if registro_idx == 0:
                        pago_mínimo_soles = valores[5].replace(',', '')
                        pago_total_soles = valores[6].replace(',', '')
                    elif registro_idx == 1:
                        pago_mínimo_dolares = valores[5].replace(',', '')
                        pago_total_dolares = valores[6].replace(',', '')
                    registro_idx += 1

            if fecha_cierre and ultimo_diapago:
                par = (fecha_cierre, ultimo_diapago)
                if par not in etiquetas:
                    etiquetas[par] = f"EC-{n:02d}"
                    n += 1
                segmentos_por_pagina[str(page.page_number)] = etiquetas[par]
                registros.append([
                    etiquetas[par],
                    page.page_number,
                    fecha_cierre,
                    ultimo_diapago,
                    pago_mínimo_soles,
                    pago_total_soles,
                    pago_mínimo_dolares,
                    pago_total_dolares
                ])

    df_general = pd.DataFrame(registros, columns=[
        'Segmento',
        'Página',
        'Fecha de Cierre',
        'Último Día de Pago',
        'Pago Mínimo Soles',
        'Pago Total Soles',
        'Pago Mínimo Dólares',
        'Pago Total Dólares'
    ])
    # Un único registro por (Fecha de Cierre, Último Día de Pago)
    df_general = df_general.sort_values('Página').drop_duplicates(
        subset=['Fecha de Cierre', 'Último Día de Pago'], keep='first'
    )

    # MOVIMIENTOS
    pattern = r'^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})$'
    data = []
    stop_pattern = re.compile(r'INTERESES?\s*SI\s*PAGA\s*MINIMO', re.IGNORECASE)

    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            text = page.extract_text()
            pg = str(page.page_number)
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                if stop_pattern.search(line.replace(" ", "").upper()):
                    break
                match = re.match(pattern, line)
                if match:
                    fecha = match.group(1)
                    comercio = match.group(2)
                    monto_soles = float(match.group(3).replace(',', ''))
                    monto_usd = float(match.group(4).replace(',', ''))
                    segmento = segmentos_por_pagina.get(pg, "")
                    data.append([segmento, pg, fecha, comercio, monto_soles, monto_usd])

    df_montos = pd.DataFrame(data, columns=[
        'Segmento',
        'Página',
        'Fecha Consumo',
        'Descripción',
        'Monto Soles',
        'Monto USD'
    ])

    # CUOTAS
    pattern_monto_cuota = re.compile(
        r'(\d+\.\d{2})(?:\s*)(\d{1,2})\s*de\s*(\d{2,3})',
        re.IGNORECASE
    )
    data = []

    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf_file:
        for page in pdf_file.pages:
            pg = str(page.page_number)
            segmento = segmentos_por_pagina.get(pg, "")
            lines = page.extract_text().split('\n')
            stop = False
            for line in lines:
                line = line.strip()
                if re.search(r'TOTAL\s+CUOTAS\s+DEL\s+MES\s+LINEA\s+DE\s+CREDITO', line, re.IGNORECASE):
                    stop = True
                    break
                if not re.match(r'^\d{2}/\d{2}/\d{4}', line):
                    continue
                try:
                    fecha_match = re.match(r'^(\d{2}/\d{2}/\d{4})', line)
                    if not fecha_match:
                        continue
                    fecha = fecha_match.group(1)
                    match_combo = pattern_monto_cuota.search(line)
                    if not match_combo:
                        continue
                    monto_original = float(match_combo.group(1))
                    cuota_raw_1 = match_combo.group(2)
                    cuota_raw_2 = match_combo.group(3)
                    concepto_raw = line[len(fecha):match_combo.start()].strip()
                    concepto = re.sub(r'\s+', ' ', concepto_raw)
                    tasa_match = re.search(r'(\d{1,3}\.\d{2})%', line)
                    tasa_valida = ""
                    if tasa_match:
                        parte_entera, parte_decimal = tasa_match.group(1).split(".")
                        if len(parte_entera) >= 1 and len(parte_decimal) == 2:
                            tasa_valida = f"{tasa_match.group(1)}%"
                    tasa_inicio = tasa_valida[0] if tasa_valida else ""
                    if len(cuota_raw_2) == 3 and cuota_raw_2[-2:] == tasa_valida[:2]:
                        cuota_raw_2 = cuota_raw_2[:-2]
                    elif cuota_raw_2[-1] == tasa_inicio:
                        cuota_raw_2 = cuota_raw_2[:-1]
                    cuota = f"{cuota_raw_1} de {cuota_raw_2}"
                    decimales = re.findall(r'\d+\.\d{2}', line)
                    if len(decimales) < 4:
                        continue
                    capital = float(decimales[-3])
                    interes = float(decimales[-2])
                    importe = float(decimales[-1])
                    data.append([
                        segmento, pg, fecha, concepto, monto_original,
                        cuota, tasa_valida, capital, interes, importe
                    ])
                except:
                    continue
            if stop:
                continue

    df_cuotas = pd.DataFrame(data, columns=[
        'Segmento',
        'Página',
        'Fecha',
        'Concepto',
        'Monto Original',
        'Número de cuota',
        'Tasa de cuota',
        'Capital de cuota',
        'Interés de cuota',
        'Importe cuota (S/ o USD)'
    ])

    def separar_cuota_y_tasa(row):
        cuota = row["Número de cuota"]
        tasa = row["Tasa de cuota"]
        match_cuota = re.match(r"(\d{1,2})\s+de\s+(\d{3})", cuota)
        match_tasa = re.match(r"(\d{3})\.\d{2}%", tasa)
        if match_cuota and match_tasa:
            cuota1 = match_cuota.group(1)
            cuota2_full = match_cuota.group(2)
            tasa_prefix = match_tasa.group(1)
            if len(cuota2_full) == 3 and tasa.startswith(tasa_prefix):
                cuota2_fixed = cuota2_full[0]
                tasa_fixed = f"{cuota2_full[1:]}.{tasa.split('.')[1]}%"
                return pd.Series([f"{cuota1} de {cuota2_fixed}", tasa_fixed])
        return pd.Series([cuota, tasa])

    df_cuotas[["Número de cuota", "Tasa de cuota"]] = df_cuotas.apply(separar_cuota_y_tasa, axis=1)
    df_cuotas["Tasa de cuota"] = df_cuotas["Tasa de cuota"].str.replace("%%", "%", regex=False)

    # Unir df_general y df_montos en una sola página tipo Excel
    # Convertir ambos DataFrames a listas de filas
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    movimientos_rows = [df_montos.columns.tolist()] + df_montos.astype(str).values.tolist()

    # Insertar una fila vacía entre ambos bloques
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + movimientos_rows

    # Crear un DataFrame combinado (rellenando columnas si es necesario)
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo,
        'Cuotas': df_cuotas.reset_index(drop=True)
    }

    return output

