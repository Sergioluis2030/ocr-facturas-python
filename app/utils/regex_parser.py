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
        "serie_numero": serie_numero,
        "fecha_emision": fecha_emision,
        "documento_cliente": documento_cliente,
        "subtotal": subtotal,
        "igv": igv,
        "total": total,
        "qr_detectado": qr_string
    }


def clean_ocr_currency_glitches(text: str) -> str:
    """
    Limpia errores típicos donde 'S/' se lee como '57', '5/', 'SI' o '8/'.
    Ejemplo: '575.80' cuando ya existe '5.80' o '5/ 4.81' -> 'S/ 4.81'
    """
    text = re.sub(r'\b(?:5\/|8\/|SI|S1)\s*(\d+[\.,]\d{2})\b', r'S/ \1', text)
    return text


def extraer_total_desde_letras(text: str) -> float | None:
    """
    Lee la línea 'SON: CINCO CON 80/100 SOLES' o 'SON: TRECE Y 76/100 SOLES'
    Incluso si el OCR leyó '807100' en vez de '80/100'.
    """
    unidades = {
        "CERO": 0, "UN": 1, "UNO": 1, "DOS": 2, "TRES": 3, "CUATRO": 4,
        "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9,
        "DIEZ": 10, "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14,
        "QUINCE": 15, "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18,
        "DIECINUEVE": 19, "VEINTE": 20, "TREINTA": 30, "CUARENTA": 40,
        "CINCUENTA": 50, "SESENTA": 60, "SETENTA": 70, "OCHENTA": 80,
        "NOVENTA": 90, "CIEN": 100
    }
    # Buscar patrón SON: <PALABRAS> <DD>/100 o <DD>7100 (cuando '/' se lee como '7')
    m = re.search(r'SON\s*:?\s*([A-ZÁÉÍÓÚÑ\s]+?)\s*(?:CON|Y)?\s*(\d{2})\s*[\/71]\s*100', text, re.IGNORECASE)
    if not m:
        return None

    palabras = m.group(1).upper().split()
    centavos = int(m.group(2)) / 100.0

    entero = 0
    encontrado = False
    for p in palabras:
        if p in unidades:
            entero += unidades[p]
            encontrado = True

    if encontrado:
        return round(entero + centavos, 2)
    return None


def parse_invoice_text(raw_text: str) -> dict:
    clean_text = clean_ocr_currency_glitches(raw_text.replace('\r', ''))

    # 1. RUC (11 dígitos empezando en 10 o 20)
    rucs = list(dict.fromkeys([m.group(0) for m in re.finditer(r'\b(?:10|20)\d{9}\b', clean_text)]))
    ruc_emisor = rucs[0] if len(rucs) > 0 else None
    documento_cliente = rucs[1] if len(rucs) > 1 else None

    # 2. Serie y Correlativo (Ej: B401-00305952, B041-00754705, FA12-02183092)
    serie_match = re.search(r'\b([FBE][A-Z0-9]{3})\s*[-–]\s*(\d{1,10})\b', clean_text, re.IGNORECASE)
    serie_numero = f"{serie_match.group(1).upper()}-{serie_match.group(2)}" if serie_match else None

    tipo_comprobante = "FACTURA" if (serie_numero and serie_numero.startswith('F')) else "BOLETA"

    # 3. Fecha de emisión (Solo años válidos de emisión 2024-2026, ignorando promos o vencimientos)
    fecha_emision = None
    # Buscar primero cerca de la palabra EMISION
    m_emision = re.search(r'EMISI[OÓ]N.*?(\d{2})[\/\-\.](\d{2})[\/\-\.](202[4-6])', clean_text, re.IGNORECASE | re.DOTALL)
    if m_emision:
        fecha_emision = f"{m_emision.group(3)}-{m_emision.group(2)}-{m_emision.group(1)}"
    else:
        fechas = re.findall(r'\b(\d{2})[\/\-\.](\d{2})[\/\-\.](202[4-6])\b', clean_text)
        if fechas:
            d, m, y = fechas[0]
            fecha_emision = f"{y}-{m}-{d}"

    # 4. Extraer todos los montos decimales que aparecen desde "OP. GRAVADA" hacia abajo
    # (Esto ignora automáticamente el S/ 5.90 o S/ 7.90 de la publicidad de arriba)
    pos_gravada = re.search(r'GRAVADA', clean_text, re.IGNORECASE)
    zona_contable = clean_text[pos_gravada.start():] if pos_gravada else clean_text

    montos_zona = []
    for x in re.findall(r'\b\d{1,4}[\.,]\d{2}\b', zona_contable):
        val = float(x.replace(',', '.'))
        montos_zona.append(val)

    # Si hay un monto corrupto por el 'S/' leído como '57' (ej. 575.80 cuando 5.80 ya está en la lista), lo limpiamos
    montos_limpios = []
    for v in montos_zona:
        s_val = f"{v:.2f}"
        if s_val.startswith("57") and len(s_val) > 5:
            sin_prefijo = float(s_val[2:])
            if sin_prefijo in montos_zona:
                continue
        montos_limpios.append(v)

    # 5. Candado 1: Obtener el total exacto desde "SON: CINCO CON 80/100 SOLES" si existe
    total_letras = extraer_total_desde_letras(clean_text)

    subtotal = None
    igv = None
    recargo_consumo = None
    total = total_letras

    # 6. Buscar combinación matemática exacta en la zona contable:
    # Caso A (Normal): Subtotal + IGV == Total (ej: 11.66 + 2.10 = 13.76)
    # Caso B (Restaurante con RC): Subtotal + IGV + RC == Total (ej: 4.81 + 0.86 + 0.13 = 5.80)
    n = len(montos_limpios)
    encontrado_combo = False

    # Probar tríos (Subtotal + IGV + RC = Total) si hay Recargo al Consumo
    if re.search(r'\bRC\b', zona_contable) and n >= 4:
        for i in range(n):
            for j in range(i + 1, n):
                for k in range(j + 1, n):
                    suma_trio = round(montos_limpios[i] + montos_limpios[j] + montos_limpios[k], 2)
                    for m_idx in range(n):
                        candidato_total = montos_limpios[m_idx]
                        if abs(candidato_total - suma_trio) <= 0.03 and candidato_total > 0:
                            if total_letras is None or abs(candidato_total - total_letras) <= 0.05:
                                trio = sorted([montos_limpios[i], montos_limpios[j], montos_limpios[k]], reverse=True)
                                # Verificar que el segundo sea aprox el 18% del primero (IGV)
                                if trio[0] > 0 and 0.15 <= (trio[1] / trio[0]) <= 0.20:
                                    subtotal = trio[0]
                                    igv = trio[1]
                                    recargo_consumo = trio[2]
                                    total = candidato_total
                                    encontrado_combo = True
                                    break
                    if encontrado_combo:
                        break
                if encontrado_combo:
                    break
            if encontrado_combo:
                break

    # Probar pares (Subtotal + IGV = Total)
    if not encontrado_combo and n >= 3:
        for i in range(n):
            for j in range(i + 1, n):
                suma_par = round(montos_limpios[i] + montos_limpios[j], 2)
                for m_idx in range(n):
                    candidato_total = montos_limpios[m_idx]
                    if abs(candidato_total - suma_par) <= 0.03 and candidato_total > 0:
                        if total_letras is None or abs(candidato_total - total_letras) <= 0.05:
                            par = sorted([montos_limpios[i], montos_limpios[j]], reverse=True)
                            if par[0] > 0 and 0.15 <= (par[1] / par[0]) <= 0.20:
                                subtotal = par[0]
                                igv = par[1]
                                total = candidato_total
                                encontrado_combo = True
                                break
                if encontrado_combo:
                    break
            if encontrado_combo:
                break

    # Respaldo si solo se detectó el total
    if total and not subtotal:
        subtotal = round(total / 1.18, 2)
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