import pdfplumber
import pandas as pd
import re
import unicodedata
import numpy as np
import io
from collections import defaultdict

# --- INFORMACIÓN GENERAL ---
def extract_multi_ec(pdf_stream, drop_if_no_name=True):
    def _norm(s):
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        return s.replace("\xa0", " ")

    def _txt_lines_with_pages(pdf_stream):
        lines_raw, lines_norm, pages = [], [], []
        with pdfplumber.open(pdf_stream) as pdf:
            for pageno, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                raw_lines  = text.splitlines()
                norm_lines = _norm(text).splitlines()
                lines_raw.extend(raw_lines)
                lines_norm.extend(norm_lines)
                pages.extend([pageno] * len(raw_lines))
        return lines_raw, lines_norm, pages

    def _is_structured_name(line):
        if not line: return False
        line = line.strip()
        if any(ch.isdigit() for ch in line): return False
        if "PAG" in line.upper(): return False
        if not re.fullmatch(r"[A-ZÁÉÍÓÚÑ' -]{6,}", line): return False
        tokens = [t for t in line.split() if t]
        if not (2 <= len(tokens) <= 7): return False
        addr_stops = {"ALT","AV","AV.","JR","JR.","CAL","CAL.","CALL.","URB","URB.","PJE","PJE.","MZ","FTE","PQ","PSJ","EST","DOMINGO","MIRAFLORES","LIMA"}
        if any(t in addr_stops for t in tokens): return False
        if sum(1 for t in tokens if len(t) >= 3 and t not in {"DE","DEL","LA","LAS","LOS","Y","DA","DO","SAN","SANTA"}) < 2:
            return False
        return True

    def _first_structured_name(lines):
        for ln in lines[:12]:
            ln = ln.strip()
            if _is_structured_name(ln):
                return ln
        return None

    def _first_date(lines_norm):
        pat = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
        for ln in lines_norm:
            m = pat.search(ln)
            if m: return m.group(1)
        return None

    def _pairs_by_line(lines_norm):
        out = []
        for ln in lines_norm:
            ln = ln.strip()
            if not ln: continue
            m1 = re.search(r"(?:S/?|S/)\s*([\d\.,]+)\s*(?:/|\s+)\s*US\$\s*([\d\.,]+)", ln, re.I)
            if m1: out.append((m1.group(1), m1.group(2))); continue
            m2 = re.search(r"US\$\s*([\d\.,]+)\s*(?:/|\s+)\s*(?:S/?|S/)\s*([\d\.,]+)", ln, re.I)
            if m2: out.append((m2.group(2), m2.group(1))); continue
        return out

    def _periodo_by_line(lines_norm):
        pat = re.compile(r"PERIODO\s+FACTURADO.*?DEL\s+(\d{1,2}\s+[A-ZÁÉÍÓÚÑ]{3,})\s+AL\s+(\d{1,2}\s+[A-ZÁÉÍÓÚÑ]{3,})", re.I)
        for ln in lines_norm:
            m = pat.search(ln)
            if m: return f"{m.group(1)} - {m.group(2)}"
        return None

    def _split_segments(lines_raw, lines_norm, pages):
        segs = []
        cur_raw, cur_norm, cur_pages = [], [], []
        boundary = re.compile(r"TEA\s+regular.*?www\.dinersclub\.pe", re.I)
        for lr, ln, pg in zip(lines_raw, lines_norm, pages):
            cur_raw.append(lr); cur_norm.append(ln); cur_pages.append(pg)
            if boundary.search(ln):
                segs.append((cur_raw, cur_norm, cur_pages))
                cur_raw, cur_norm, cur_pages = [], [], []
        if cur_raw:
            segs.append((cur_raw, cur_norm, cur_pages))
        return segs

    lines_raw, lines_norm, pages = _txt_lines_with_pages(pdf_stream)
    segments = _split_segments(lines_raw, lines_norm, pages)

    rows = []
    for i, (seg_raw, seg_norm, seg_pages) in enumerate(segments, start=1):
        cliente = _first_structured_name(seg_raw)
        page_for_segment = None
        if cliente:
            for ln, pg in zip(seg_raw, seg_pages):
                if ln.strip() == cliente:
                    page_for_segment = pg
                    break
        if page_for_segment is None:
            for ln, pg in zip(seg_norm, seg_pages):
                if ln.strip():
                    page_for_segment = pg
                    break
        if drop_if_no_name and not cliente:
            continue
        ultimo  = _first_date(seg_norm)
        periodo = _periodo_by_line(seg_norm)
        pairs   = _pairs_by_line(seg_norm)
        tot_pen = tot_usd = min_pen = min_usd = None
        if len(pairs) >= 1: tot_pen, tot_usd = pairs[0]
        if len(pairs) >= 2: min_pen, min_usd = pairs[1]
        rows.append({
            "Segmento": f"EC-{i:02d}",
            "Página": page_for_segment,
            "Cliente": cliente,
            "Periodo facturado": periodo,
            "Último día de pago": ultimo,
            "Pago Total Soles":  f"S/ {tot_pen}" if tot_pen else None,
            "Pago Total USD":    f"US$ {tot_usd}" if tot_usd else None,
            "Pago Mínimo Soles": f"S/ {min_pen}" if min_pen else None,
            "Pago Mínimo USD":   f"US$ {min_usd}" if min_usd else None,
        })
    df = pd.DataFrame(rows)
    desired = ["Segmento", "Página", "Cliente", "Periodo facturado", "Último día de pago",
               "Pago Total Soles", "Pago Total USD", "Pago Mínimo Soles", "Pago Mínimo USD"]
    df = df[[c for c in desired if c in df.columns]]
    return df

def extract_ec_movements(pdf_stream):
    TARGET_HEADERS = [
        "PAGOS/ABONOS REALIZADOS EN EL MES",
        "COMISIONES Y OTROS CARGOS",
    ]
    _TARGET_HEADERS_NORM = { unicodedata.normalize("NFD", h.upper()).replace("\xa0"," ").replace("\u00A0","") for h in TARGET_HEADERS }
    def _norm(s):
        s = unicodedata.normalize("NFD", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        return s.replace("\xa0", " ")
    def _words_by_lines(pdf_stream):
        lines = []
        with pdfplumber.open(pdf_stream) as pdf:
            for pageno, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=True)
                groups = defaultdict(list)
                for w in words:
                    groups[round(w["top"], 1)].append(w)
                for top in sorted(groups.keys()):
                    ws = sorted(groups[top], key=lambda w: w["x0"])
                    text = " ".join(w["text"] for w in ws)
                    lines.append({
                        "page": pageno,
                        "top": top,
                        "text": text,
                        "norm": _norm(text.upper()),
                        "words": ws
                    })
        return lines
    def _split_segments(lines):
        segs, cur = [], []
        boundary = re.compile(r"TEA\s+REGULAR.*?WWW\.DINERSCLUB\.PE", re.I)
        for ln in lines:
            cur.append(ln)
            if boundary.search(ln["norm"]):
                segs.append(cur); cur = []
        if cur: segs.append(cur)
        return segs
    MONTH_ABBRS = {"ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SET","SEP","OCT","NOV","DIC"}
    def _parse_day(tok):
        tok = tok.replace(".", "")
        return int(tok) if tok.isdigit() and 1 <= int(tok) <= 31 else None
    def _parse_month_abbr(tok):
        t = _norm(tok.upper()).replace(".","")
        t = {"SET":"SEP"}.get(t, t)[:3]
        return t if t in MONTH_ABBRS else None
    def _extract_dates_tokens_to_str(words):
        toks = [w["text"] for w in words]
        pos, found = 0, []
        while pos < len(toks)-1 and len(found) < 2:
            d = _parse_day(toks[pos]); m = _parse_month_abbr(toks[pos+1])
            if d and m:
                found.append(f"{int(d)} {m}")
                pos += 2
            else:
                pos += 1
        if not found:
            return None, None, 0
        pos_desc, count, i = 0, 0, 0
        while i < len(toks)-1 and count < len(found):
            if _parse_day(toks[i]) and _parse_month_abbr(toks[i+1]):
                count += 1; i += 2; pos_desc = i
            else:
                i += 1
        fcons = found[0] if len(found) >= 1 else None
        fproc = found[1] if len(found) >= 2 else None
        return fcons, fproc, pos_desc
    def _amount_from_token(tok):
        if all(x not in tok for x in [".",",","S/","US$","-","(",")"]):
            return None
        t = tok.replace(",","").replace("S/","").replace("US$","")
        neg = False
        if "(" in t and ")" in t: neg = True
        t = t.replace("(","").replace(")","")
        if t.startswith("-"): neg, t = True, t[1:]
        try:
            val = float(t)
            return -val if neg else val
        except:
            return None
    def _collect_amount_xmids(rows_words):
        xs = []
        for words in rows_words:
            for w in words[::-1]:
                if _amount_from_token(w["text"]) is not None:
                    xs.append((w["x0"]+w["x1"])/2.0)
        return xs
    def _x_threshold(xs):
        if len(xs) < 2: return None
        xs = sorted(xs)
        gaps = [(xs[i+1]-xs[i], i) for i in range(len(xs)-1)]
        _, i = max(gaps, key=lambda t: t[0])
        return (xs[i]+xs[i+1])/2.0
    def _extract_section_rows(seg, header_norm):
        rows = []
        idxs = [i for i, ln in enumerate(seg) if header_norm in ln["norm"]]
        for idx in idxs:
            j = idx + 1
            while j < len(seg):
                ln = seg[j]
                if ln["norm"].strip() in _TARGET_HEADERS_NORM and j != idx:
                    break
                is_title = (ln["text"].isupper() and not re.search(r"\d", ln["text"]) and len(ln["text"]) >= 8)
                if is_title and not re.search(r"S/|US\$|\d{1,2}[- ]?[A-Z]{3}", ln["norm"]):
                    break
                rows.append(ln); j += 1
        return rows
    lines = _words_by_lines(pdf_stream)
    segments = _split_segments(lines)
    all_rows = []
    for seg_idx, seg in enumerate(segments, start=1):
        rows = []
        for hdr in TARGET_HEADERS:
            rows.extend(_extract_section_rows(seg, _norm(hdr.upper())))
        rows = [r for r in rows if not re.match(r"^(SUB\s+TOTAL|TOTAL|SALDO)", r["norm"])]
        if not rows:
            continue
        xs = _collect_amount_xmids([r["words"] for r in rows])
        thr = _x_threshold(xs)
        for ln in rows:
            fcons, fproc, start_desc = _extract_dates_tokens_to_str(ln["words"])
            if fcons is None and fproc is None:
                continue
            toks = [w["text"] for w in ln["words"]]
            amts = [( _amount_from_token(w["text"]), (w["x0"]+w["x1"])/2.0 ) for w in ln["words"]]
            amts = [(v,x) for v,x in amts if v is not None]
            soles = dolares = None
            if amts:
                if thr is not None:
                    for v,x in amts:
                        if x <= thr and soles is None: soles = v
                        if x >  thr and dolares is None: dolares = v
                else:
                    if len(amts)==1:
                        dolares = amts[0][0]
                    else:
                        left  = min(amts, key=lambda t: t[1])[0]
                        right = max(amts, key=lambda t: t[1])[0]
                        soles, dolares = left, right
            desc = " ".join(toks[start_desc:]).strip()
            desc = re.sub(r"([\s\-]*\(?-?[\d\.,]+\)?\s*)+$", "", desc).strip()
            all_rows.append({
                "EC": f"EC-{seg_idx:02d}",
                "Página": ln["page"],
                "Fecha consumo": fcons,
                "Fecha proceso": fproc,
                "Detalle de movimientos": desc,
                "Soles": soles,
                "Dolares": dolares,
            })
    df = pd.DataFrame(all_rows)
    if not df.empty:
        df = df.sort_values(["EC", "Página"], kind="mergesort").reset_index(drop=True)
        df = df[["EC","Página","Fecha consumo","Fecha proceso","Detalle de movimientos","Soles","Dolares"]]
    return df

def extract_ec_cuotas(pdf_stream):
    NMONTHS = {"ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SET","SEP","OCT","NOV","DIC"}
    def norm(s):
        s = unicodedata.normalize("NFD", s)
        return "".join(ch for ch in s if unicodedata.category(ch)!="Mn").replace("\xa0"," ").upper()
    def words_by_lines(pdf_stream):
        out=[]
        with pdfplumber.open(pdf_stream) as pdf:
            for p,pg in enumerate(pdf.pages, start=1):
                ws = pg.extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=True)
                rows=defaultdict(list)
                for w in ws: rows[round(w["top"],1)].append(w)
                for top in sorted(rows):
                    line=sorted(rows[top], key=lambda w:w["x0"])
                    out.append({"page":p,"top":top,"words":line,"norm":" ".join(w["text"] for w in line)})
        for r in out: r["norm"]=norm(r["norm"])
        return out
    def split_segments(lines):
        segs,cur=[],[]
        cut=re.compile(r"TEA\s+REGULAR.*?WWW\.DINERSCLUB\.PE")
        for ln in lines:
            cur.append(ln)
            if cut.search(ln["norm"]): segs.append(cur); cur=[]
        if cur: segs.append(cur)
        return segs
    def dates_tokens(words):
        toks=[w["text"] for w in words]; pos=0; found=[]
        def day(t): t=t.replace(".",""); return t.isdigit() and 1<=int(t)<=31
        def mon(t): t=norm(t).replace(".","")[:3]; t={"SET":"SEP"}.get(t,t); return t if t in NMONTHS else None
        while pos<len(toks)-1 and len(found)<2:
            if day(toks[pos]) and mon(toks[pos+1]): found.append(f"{int(toks[pos])} {mon(toks[pos+1])}"); pos+=2
            else: pos+=1
        if not found: return None,None,0
        i=cnt=pos_desc=0
        while i<len(toks)-1 and cnt<len(found):
            if day(toks[i]) and mon(toks[i+1]): cnt+=1; i+=2; pos_desc=i
            else: i+=1
        return (found[0], found[1] if len(found)>1 else None, pos_desc)
    def looks_header(s): return ("CUOTAS" in s) and ("TEA" in s)
    def is_upper_no_digits(s): return s.isupper() and not re.search(r"\d", s)
    def find_rows(seg):
        rows=[]
        idx=[i for i,ln in enumerate(seg) if looks_header(ln["norm"])]
        for k in idx:
            j=k+1
            while j<len(seg):
                t=seg[j]["norm"].strip()
                if looks_header(t) and j!=k: break
                if is_upper_no_digits(t):
                    if len(t.split())<=2: j+=1; continue
                    else: break
                rows.append(seg[j]); j+=1
        return [r for r in rows if dates_tokens(r["words"])[0] or dates_tokens(r["words"])[1]]
    def parse_amt(txt):
        if all(x not in txt for x in [".",",","S/","US$","-","(",")"]): return None
        t=txt.replace(",","").replace("S/","").replace("US$","")
        neg=("(" in t and ")" in t) or t.startswith("-")
        t=t.replace("(","").replace(")","").lstrip("-")
        try: val=float(t); return -val if neg else val
        except: return None
    def learn_centers(rows):
        xs=[]
        for ln in rows:
            for w in ln["words"]:
                v=parse_amt(w["text"])
                if v is None: continue
                x=(w["x0"]+w["x1"])/2
                if x>250: xs.append(x)
        if not xs: return []
        xs=sorted(xs); clusters=[]; cur=[xs[0]]
        for x in xs[1:]:
            if abs(x-cur[-1])<=12: cur.append(x)
            else: clusters.append(cur); cur=[x]
        clusters.append(cur)
        return sorted(float(np.median(c)) for c in clusters)
    lines=words_by_lines(pdf_stream)
    segments=split_segments(lines)
    cols=["Importe","Saldo","Capital","Interés","Cuota del mes Soles","Cuota del mes Dólares"]
    out=[]
    for si,seg in enumerate(segments, start=1):
        rows=find_rows(seg)
        centers=learn_centers(rows)
        for ln in rows:
            toks=[w["text"] for w in ln["words"]]
            fcons,fproc,i0=dates_tokens(ln["words"])
            cuota_idx=tea_idx=None; tea_val=None
            for i,t in enumerate(toks):
                if re.fullmatch(r"\(\s*\d+\s*/\s*\d+\s*\)", t): cuota_idx=i
                if re.fullmatch(r"\d+(?:[.,]\d+)?%", t) or t=="0%": tea_idx,tea_val=i,t.replace(",",".")
            i_end=min([x for x in [len(toks), cuota_idx, tea_idx] if x is not None])
            desc=" ".join(toks[i0:i_end]).strip()
            vals={c:None for c in cols}
            for w in ln["words"]:
                v=parse_amt(w["text"])
                if v is None or not centers: continue
                x=(w["x0"]+w["x1"])/2
                if x<=250: continue
                idx=int(np.argmin([abs(x-c) for c in centers]))
                if idx<len(cols) and vals[cols[idx]] is None: vals[cols[idx]]=v
            out.append({
                "EC": f"EC-{si:02d}",
                "Página": ln["page"],
                "Fecha consumo": fcons,
                "Fecha proceso": fproc,
                "Descripción": desc,
                "Nro. Cuota": toks[cuota_idx] if cuota_idx is not None else None,
                "TEA": tea_val,
                **vals
            })
    df=pd.DataFrame(out)
    if not df.empty:
        df=df.sort_values(["EC","Página"]).reset_index(drop=True)
    return df

def procesar_documento(pdf_bytes):
    pdf_stream = io.BytesIO(pdf_bytes)
    df_general = extract_multi_ec(pdf_stream, drop_if_no_name=True)
    df_movs = extract_ec_movements(pdf_stream)
    df_cuotas = extract_ec_cuotas(pdf_stream)

    # Unir df_general y df_movs en una sola hoja tipo Excel (igual que en bbva)
    resumen_rows = [df_general.columns.tolist()] + df_general.astype(str).values.tolist()
    movimientos_rows = [df_movs.columns.tolist()] + df_movs.astype(str).values.tolist()
    combined_rows = resumen_rows + [[""] * len(resumen_rows[0])] + movimientos_rows
    max_cols = max(len(row) for row in combined_rows)
    combined_rows = [row + [""] * (max_cols - len(row)) for row in combined_rows]
    df_resumen_completo = pd.DataFrame(combined_rows)

    output = {
        'Resumen': df_resumen_completo.reset_index(drop=True),
        'Cuotas': df_cuotas.reset_index(drop=True)
    }
    return output

