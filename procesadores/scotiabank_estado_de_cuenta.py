import pdfplumber
import pandas as pd
import re
import io

def procesar_documento(pdf_bytes):
    """
    Procesa un archivo PDF de estado de cuenta de Scotiabank.
    Args:
        pdf_bytes: Bytes del archivo PDF
    Returns:
        dict: Diccionario con DataFrames de información general, movimientos y cuotas
    """
    pdf_stream = io.BytesIO(pdf_bytes)
    # --- INFORMACIÓN GENERAL ---
    with pdfplumber.open(pdf_stream) as pdf_file:
        full_text = ""
        for page in pdf_file.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    sep = r"[\s\u00A0\u2010\u2011\u2012\u2013\u2014\u2015-]*"
    pat_311 = rf"3{sep}1{sep}1{sep}6{sep}0{sep}0{sep}0"
    pat_0801 = rf"0{sep}801{sep}1{sep}6000"
    pat_anchor = (
        r"llamando\s+al\s*" + pat_311 +
        r"\s+desde\s+Lima\s+o\s+(?:al\s+)?" + pat_0801 +
        r"\s+desde\s+provincias\.?"
    )
    if len(re.findall(pat_anchor, full_text, flags=re.I)) > 1:
        segmentos = re.split(r"(?<=" + pat_anchor + r")", full_text, flags=re.I)
        segmentos = [s.strip() for s in segmentos if s and s.strip()]
    else:
        segmentos = [full_text.strip()]

    registros = []
    for i, seg in enumerate(segmentos, start=1):
        lineas = seg.splitlines()
        linea_3 = lineas[3].strip() if len(lineas) > 3 else ""
        cliente = re.sub(r'S\/\s?[\d,]+\.\d{2}\s+US\$\s?[\d,]+\.\d{2}', '', linea_3).strip()
        fecha_fin_ciclo = lineas[2].strip() if len(lineas) > 2 else None
        if not (fecha_fin_ciclo and re.match(r'\d{2}-\d{2}-\d{4}', fecha_fin_ciclo)):
            fecha_fin_ciclo = None
        match_montos = re.search(r'S\/\s?([\d,]+\.\d{2})\s+US\$\s?([\d,]+\.\d{2})', linea_3)
        pago_total_soles = match_montos.group(1) if match_montos else None
        pago_total_usd = match_montos.group(2) if match_montos else None
        ultimodia_pago = lineas[6].strip() if len(lineas) > 6 else None
        if not (ultimodia_pago and re.match(r'\d{2}-\d{2}-\d{4}', ultimodia_pago)):
            ultimodia_pago = None
        match_pago_min_usd = re.findall(r'US\$ ([\d,]+\.\d{2})', seg)
        pago_minimo_usd = match_pago_min_usd[1] if len(match_pago_min_usd) >= 2 else None
        match_pago_min_soles = re.findall(r'S\/ ([\d,]+\.\d{2})', seg)
        pago_minimo_soles = match_pago_min_soles[2] if len(match_pago_min_soles) >= 3 else None
        registros.append([
            f"EC-{i:02d}", cliente, fecha_fin_ciclo, ultimodia_pago,
            pago_total_soles, pago_total_usd, pago_minimo_soles, pago_minimo_usd
        ])
    df_general = pd.DataFrame(
        registros,
        columns=['Segmento','Cliente','Fecha cierre','Ultimo dia de pago',
                 'Pago Total Soles','Pago Total USD','Pago Minimo Soles','Pago Minimo USD']
    )

    # --- MOVIMIENTOS 
    def _to_float(txt):
        if not txt:
            return None
        txt = txt.replace(",", "")
        neg = txt.endswith("-")
        val = float(txt.rstrip("-"))
        return -val if neg else val

    def _centro(word):
        return (word["x0"] + word["x1"]) / 2

    filas = []
    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf:
        sep = r"[\s\u00A0\u2010\u2011\u2012\u2013\u2014\u2015-]*"
        pat_311  = rf"3{sep}1{sep}1{sep}6{sep}0{sep}0{sep}0"
        pat_0801 = rf"0{sep}801{sep}1{sep}6000"
        pat_anchor = re.compile(
            r"llamando\s+al\s*" + pat_311 +
            r"\s+desde\s+Lima\s+o\s+(?:al\s+)?" + pat_0801 +
            r"\s+desde\s+provincias\.?",
            re.I
        )
        current_seg = 0
        for page in pdf.pages:
            text = page.extract_text() or ""
            has_anchor = bool(pat_anchor.search(text))
            if "Fecha Compra" in text:
                if current_seg == 0:
                    current_seg = 1
                seg_label = f"EC-{current_seg:02d}"
                soles_x = dolares_x = None
                for w in page.extract_words():
                    if w["text"] == "Soles":
                        soles_x = _centro(w)
                    elif "ólares" in w["text"]:
                        dolares_x = _centro(w)
                if soles_x is None or dolares_x is None:
                    nums = [_centro(w) for w in page.extract_words()
                            if re.fullmatch(r"^\d{1,3}(?:,\d{3})*\.\d{2}-?$", w["text"])]
                    if not nums:
                        if has_anchor:
                            current_seg += 1
                        continue
                    from statistics import mean, median
                    mid = median(nums)
                    soles_x   = mean([x for x in nums if x <  mid])
                    dolares_x = mean([x for x in nums if x >= mid])
                line_dict = {}
                for w in page.extract_words():
                    y = round(w["top"], 1)
                    line_dict.setdefault(y, []).append(w)
                for words in line_dict.values():
                    words.sort(key=lambda w: w["x0"])
                    tokens = [w["text"] for w in words]
                    line_text = " ".join(tokens)
                    if re.search(r"(?i)\bsaldo\s+anterior\b", line_text):
                        sa_soles = sa_dolares = None
                        for w in words:
                            if re.fullmatch(r"^\d{1,3}(?:,\d{3})*\.\d{2}-?$", w["text"]):
                                if abs(_centro(w) - soles_x) < abs(_centro(w) - dolares_x):
                                    sa_soles = _to_float(w["text"])
                                else:
                                    sa_dolares = _to_float(w["text"])
                        if sa_soles is not None or sa_dolares is not None:
                            filas.append({
                                "segmento":      seg_label,
                                "fecha_compra":  None,
                                "fecha_proceso": None,
                                "descripcion":   "Saldo Anterior",
                                "monto_soles":   sa_soles,
                                "monto_dolares": sa_dolares,
                            })
                        continue
                    if (len(tokens) < 3 or
                        not re.fullmatch(r"\d{2}/\d{2}/\d{2}", tokens[0]) or
                        not re.fullmatch(r"\d{2}/\d{2}/\d{2}", tokens[1])):
                        continue
                    compra, proceso = tokens[:2]
                    desc_parts, soles, dolares = [], None, None
                    for w in words[2:]:
                        if re.fullmatch(r"^\d{1,3}(?:,\d{3})*\.\d{2}-?$", w["text"]):
                            if abs(_centro(w) - soles_x) < abs(_centro(w) - dolares_x):
                                soles = _to_float(w["text"])
                            else:
                                dolares = _to_float(w["text"])
                        else:
                            desc_parts.append(w["text"])
                    descripcion = " ".join(desc_parts).strip()
                    if not descripcion or descripcion.lower().startswith(("deuda total",)):
                        continue
                    filas.append({
                        "segmento":      seg_label,
                        "fecha_compra":  compra,
                        "fecha_proceso": proceso,
                        "descripcion":   descripcion,
                        "monto_soles":   soles,
                        "monto_dolares": dolares,
                    })
            if has_anchor:
                current_seg += 1
    df_movimientos = pd.DataFrame(filas)
    cols = ["segmento", "fecha_compra", "fecha_proceso", "descripcion", "monto_soles", "monto_dolares"]
    df_movimientos = df_movimientos.reindex(columns=cols)

    # --- CUOTAS ---
    pattern = r'^(.+?)\s+(\d{2}/\d{2}/\d{2})\s+([\d\.]+)\s+([\d,]+\.\d{2})\s+(\d{2}/\d{2})\s+([\d\.]+)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})$'
    datos = []
    pdf_stream.seek(0)
    with pdfplumber.open(pdf_stream) as pdf:
        sep = r"[\s\u00A0\u2010\u2011\u2012\u2013\u2014\u2015-]*"
        pat_311  = rf"3{sep}1{sep}1{sep}6{sep}0{sep}0{sep}0"
        pat_0801 = rf"0{sep}801{sep}1{sep}6000"
        pat_anchor = re.compile(
            r"llamando\s+al\s*" + pat_311 +
            r"\s+desde\s+Lima\s+o\s+(?:al\s+)?" + pat_0801 +
            r"\s+desde\s+provincias\.?",
            re.I
        )
        current_seg = 1
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            seg_label = f"EC-{current_seg:02d}"
            lines = page_text.split('\n')
            for line in lines:
                match = re.match(pattern, line.strip())
                if match:
                    fila = [
                        seg_label,
                        match.group(1),
                        match.group(2),
                        float(match.group(3)),
                        float(match.group(4).replace(',', '')),
                        match.group(5),
                        float(match.group(6)),
                        float(match.group(7).replace(',', '')),
                        float(match.group(8).replace(',', '')),
                        float(match.group(9).replace(',', ''))
                    ]
                    datos.append(fila)
            if pat_anchor.search(page_text):
                current_seg += 1
    df_cuotas = pd.DataFrame(
        datos,
        columns=[
            "Segmento", "Descripción", "Fecha de compra", "TEA", "Consumo",
            "Nro. Cuota", "Interés del mes", "Capital",
            "Cuota del mes Soles", "Cuota del mes Dólares"
        ]
    )

    df_resumen = pd.concat([
        df_general.reset_index(drop=True),
        pd.DataFrame([[""] * len(df_general.columns)]),  # Fila vacía
        df_movimientos.reset_index(drop=True)
    ], ignore_index=True)

    output = {
        'Resumen': df_resumen,
        'Cuotas': df_cuotas.reset_index(drop=True)
    }
    return output


