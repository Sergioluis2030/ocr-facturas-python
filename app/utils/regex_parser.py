import re

def parse_sunat_qr(qr_string: str) -> dict:
    parts = [p.strip() for p in qr_string.split('|')]
    if len(parts) < 7:
        return {}

    ruc_emisor = parts[0] if re.match(r'^(10|20)\d{9}$', parts[0]) else None
    tipo_cod = parts[1]
    tipo_comprobante = "FACTURA" if tipo_cod == "01" else ("BOLETA" if tipo_cod == "03" else None)
    serie_numero = f"{parts[2]}-{parts[3]}" if parts[2] and parts[3] else None

    try:
        igv = float(parts[4])
    except ValueError:
        igv = None

    try:
        total = float(parts[5])
    except ValueError:
        total = None

    subtotal = round(total - igv, 2) if (total is not None and igv is not None) else None
    fecha_emision = parts[6] if parts[6] else None
    documento_cliente = parts[8] if len(parts) > 8 and parts[8].isdigit() else None

    return {
        "tipo_comprobante": tipo_comprobante,
        "ruc_emisor": ruc_emisor,
        "razon_social_emisor": None,
        "serie_numero": serie_numero,
        "fecha_emision": fecha_emision,
        "moneda": "PEN",
        "documento_cliente": documento_cliente,
        "nombre_cliente": None,
        "subtotal": subtotal,
        "igv": igv,
        "total": total,
        "items": [],
        "qr_detectado": qr_string
    }


def clean_ocr_currency_glitches(text: str) -> str:
    text = re.sub(r'\b(?:5\/|8\/|SI|S1)\s*(\d+[\.,]\d{2})\b', r'S/ \1', text)
    return text


def extraer_total_desde_letras(text: str) -> float | None:
    """
    Convierte importes en letras a número:
    Soporta:
    - 'SON: CINCO CON 80/100 SOLES' -> 5.80
    - 'SON: TRECE Y 76/100 SOLES' -> 13.76
    - 'SEISCIENTOS NOVENTA Y NUEVE SOLES' (sin SON y sin 00/100, como Promart) -> 699.00
    """
    valores = {
        "CERO": 0, "UN": 1, "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4,
        "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9,
        "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14,
        "QUINCE": 15, "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18,
        "DIECINUEVE": 19, "VEINTE": 20, "VEINTIUN": 21, "VEINTIUNO": 21,
        "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24, "VEINTICINCO": 25,
        "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
        "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60,
        "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90,
        "CIEN": 100, "CIENTO": 100, "DOSCIENTOS": 200, "TRESCIENTOS": 300,
        "CUATROCIENTOS": 400, "QUINIENTOS": 500, "SEISCIENTOS": 600,
        "SETECIENTOS": 700, "OCHOCIENTOS": 800, "NOVECIENTOS": 900,
        "MIL": 1000
    }

    # Caso 1: Con fracción XX/100 SOLES
    m1 = re.search(r'(?:SON\s*:?\s*)?([A-ZÁÉÍÓÚÑ\s]{3,60}?)\s*(?:CON|Y)?\s*(\d{2})\s*[\/71]\s*100\s*SOLES', text, re.IGNORECASE)
    if m1:
        palabras = m1.group(1).upper().split()
        centavos = int(m1.group(2)) / 100.0
        suma = sum(valores[p] for p in palabras if p in valores)
        if suma > 0 or "CERO" in palabras:
            return round(suma + centavos, 2)

    # Caso 2: Sin fracción (Ej. "SEISCIENTOS NOVENTA Y NUEVE SOLES")
    m2 = re.search(r'([A-ZÁÉÍÓÚÑ\s]{4,60}?)\s+SOLES\b', text, re.IGNORECASE)
    if m2:
        palabras = m2.group(1).upper().split()
        suma = sum(valores[p] for p in palabras if p in valores)
        if suma > 0:
            return float(suma)

    return None


def parse_invoice_text(raw_text: str) -> dict:
    clean_text = clean_ocr_currency_glitches(raw_text.replace('\r', ''))

    # 1. Separar RUC Emisor vs RUC/DNI Cliente
    # Si un RUC está precedido por "DOC IDENTIDAD", "CLIENTE" o "SEÑOR", es el cliente
    ruc_cliente_match = re.search(r'(?:IDENTIDAD|CLIENTE|SE.OR)[\s\S]{0,35}?\b((?:10|20)\d{9}|\d{8})\b', clean_text, re.IGNORECASE)
    documento_cliente = ruc_cliente_match.group(1) if ruc_cliente_match else None

    todos_rucs = list(dict.fromkeys([m.group(0) for m in re.finditer(r'(?:10|20)\d{9}', clean_text)]))
    ruc_emisor = None
    for r in todos_rucs:
        if r != documento_cliente:
            ruc_emisor = r
            break
    # Si no se pudo distinguir, pero sabemos que es Promart / Homecenters Peruanos:
    if not ruc_emisor and re.search(r'PROMART|HOMECENTERS\s+PERUANOS', clean_text, re.IGNORECASE):
        ruc_emisor = "20536557858"
    elif not ruc_emisor and todos_rucs:
        ruc_emisor = todos_rucs[0]

    # 2. Serie y Correlativo (Ej: FA12-02183092, B401-00305952, B041-00754705)
    serie_match = re.search(r'\b([FBE][A-Z0-9]{3})\s*[-–]\s*(\d{1,10})\b', clean_text, re.IGNORECASE)
    serie_numero = f"{serie_match.group(1).upper()}-{serie_match.group(2)}" if serie_match else None

    tipo_comprobante = "FACTURA" if (serie_numero and serie_numero.startswith('F')) else "BOLETA"

    # 3. Fecha de emisión: Soporta DD/MM/YYYY y formato corto de ticket DD.MM.YY (ej: 14.10.26 o 14,10.26)
    fecha_emision = None
    m_emision = re.search(r'EMISI[OÓ]N.*?(\d{2})[\/\-\.,](\d{2})[\/\-\.,](202[4-6])', clean_text, re.IGNORECASE | re.DOTALL)
    if m_emision:
        fecha_emision = f"{m_emision.group(3)}-{m_emision.group(2)}-{m_emision.group(1)}"
    else:
        fechas_4d = re.findall(r'\b(\d{2})[\/\-\.,](\d{2})[\/\-\.,](202[4-6])\b', clean_text)
        if fechas_4d:
            d, m, y = fechas_4d[0]
            fecha_emision = f"{y}-{m}-{d}"
        else:
            # Buscar formato corto DD.MM.YY (ej. 14.10.26 o 14,10.26 junto a la hora)
            fechas_2d = re.findall(r'\b(0[1-9]|[12]\d|3[01])[\.,\/\-](0[1-9]|1[0-2])[\.,\/\-](2[4-7])\b', clean_text)
            if fechas_2d:
                d, m, y2 = fechas_2d[0]
                fecha_emision = f"20{y2}-{m}-{d}"

    # 4. Extraer montos (incluso si están pegados a letras por ruido del reverso como '10v592,37')
    pos_contable = re.search(r'SUBTOTAL|EXONERADA|GRAVADA', clean_text, re.IGNORECASE)
    zona_contable = clean_text[pos_contable.start():] if pos_contable else clean_text

    # No usamos \b al inicio para capturar '10v592,37' -> '592.37'
    raw_decimals = re.findall(r'(?<!\d)(\d{1,5}[\.,]\d{2})(?!\d)', zona_contable)
    montos_zona = []
    for x in raw_decimals:
        val = float(x.replace(',', '.'))
        if val > 0:  # Ignorar los 0.00 de OP. EXONERADA / INAFECTA / VUELTO
            montos_zona.append(val)

    # Limpiar falsos '57' por símbolo 'S/'
    montos_limpios = []
    for v in montos_zona:
        s_val = f"{v:.2f}"
        if s_val.startswith("57") and len(s_val) > 5:
            sin_prefijo = float(s_val[2:])
            if sin_prefijo in montos_zona:
                continue
        montos_limpios.append(v)

    # 5. Candado en letras ("SEISCIENTOS NOVENTA Y NUEVE SOLES" -> 699.00)
    total_letras = extraer_total_desde_letras(clean_text)

    subtotal = None
    igv = None
    recargo_consumo = None
    total = total_letras

    n = len(montos_limpios)
    encontrado_combo = False

    # Caso A: Trío (Subtotal + IGV + RC = Total)
    if re.search(r'\bRC\b', zona_contable) and n >= 4:
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    suma_trio = round(montos_limpios[i] + montos_limpios[j] + montos_limpios[k], 2)
                    for m_idx in range(n):
                        cand = montos_limpios[m_idx]
                        if abs(cand - suma_trio) <= 0.03:
                            if total_letras is None or abs(cand - total_letras) <= 0.05:
                                trio = sorted([montos_limpios[i], montos_limpios[j], montos_limpios[k]], reverse=True)
                                if trio[0] > 0 and 0.15 <= (trio[1] / trio[0]) <= 0.20:
                                    subtotal, igv, recargo_consumo, total = trio[0], trio[1], trio[2], cand
                                    encontrado_combo = True
                                    break
                    if encontrado_combo: break
                if encontrado_combo: break
            if encontrado_combo: break

    # Caso B: Par (Subtotal + IGV = Total)
    if not encontrado_combo and n >= 3:
        for i in range(n):
            for j in range(i + 1, n):
                suma_par = round(montos_limpios[i] + montos_limpios[j], 2)
                for m_idx in range(n):
                    cand = montos_limpios[m_idx]
                    if abs(cand - suma_par) <= 0.03:
                        if total_letras is None or abs(cand - total_letras) <= 0.05:
                            par = sorted([montos_limpios[i], montos_limpios[j]], reverse=True)
                            if par[0] > 0 and 0.15 <= (par[1] / par[0]) <= 0.20:
                                subtotal, igv, total = par[0], par[1], cand
                                encontrado_combo = True
                                break
                if encontrado_combo: break
            if encontrado_combo: break

    # Caso C: Si el IGV fue tapado en la foto (como el 106.63 en Promart), pero tenemos Total (699.00) y Subtotal (592.37)
    if not encontrado_combo:
        # Si no hubo total en letras, el monto que más se repite (>1 vez, ej. 699.00 aparece 3 veces) es el Total
        if total is None and montos_limpios:
            frecuencias = {x: montos_limpios.count(x) for x in set(montos_limpios)}
            mas_repetido = max(frecuencias, key=frecuencias.get)
            if frecuencias[mas_repetido] >= 2:
                total = mas_repetido
            else:
                total = max(montos_limpios)

        # Verificar si en la lista está el subtotal exacto (Total / 1.18)
        if total:
            sub_esperado = round(total / 1.18, 2)
            for m_val in montos_limpios:
                if abs(m_val - sub_esperado) <= 0.05:
                    subtotal = m_val
                    igv = round(total - subtotal, 2)
                    break
            if not subtotal:
                subtotal = sub_esperado
                igv = round(total - subtotal, 2)

    resultado = {
        "tipo_comprobante": tipo_comprobante,
        "ruc_emisor": ruc_emisor,
        "razon_social_emisor": None,
        "serie_numero": serie_numero,
        "fecha_emision": fecha_emision,
        "moneda": "PEN",
        "documento_cliente": documento_cliente,
        "nombre_cliente": None,
        "subtotal": subtotal,
        "igv": igv,
        "total": total,
        "items": [],
        "texto_crudo_ocr": clean_text.strip()
    }

    if recargo_consumo is not None:
        resultado["recargo_consumo"] = recargo_consumo

    return resultado