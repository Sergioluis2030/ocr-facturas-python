import cv2
import numpy as np
import easyocr
from app.utils.regex_parser import parse_invoice_text, parse_sunat_qr

# Intentar importar pyzbar (el lector industrial de QR/barras)
try:
    from pyzbar.pyzbar import decode as pyzbar_decode, ZBarSymbol
    HAS_PYZBAR = True
except Exception as e:
    print(f"ℹ️ pyzbar no disponible ({e}), se usará solo OpenCV QR.")
    HAS_PYZBAR = False

_ocr_reader = None

def get_easyocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        print("   📦 Cargando modelo neuronal EasyOCR en memoria...")
        _ocr_reader = easyocr.Reader(['es'], gpu=True, quantize=True)
    return _ocr_reader


def _decode_single_image(img: np.ndarray, cv_detector: cv2.QRCodeDetector) -> str | None:
    """Prueba primero con pyzbar (más tolerante a inclinación/desenfoque) y luego con OpenCV."""
    if HAS_PYZBAR:
        try:
            decoded_objs = pyzbar_decode(img, symbols=[ZBarSymbol.QRCODE])
            for obj in decoded_objs:
                text = obj.data.decode("utf-8", errors="ignore").strip()
                if "|" in text and len(text) >= 20:
                    return text
        except Exception:
            pass

    try:
        data, _, _ = cv_detector.detectAndDecode(img)
        if data and "|" in data and len(data) >= 20:
            return data
        if hasattr(cv_detector, "detectAndDecodeCurved"):
            data_c, _ = cv_detector.detectAndDecodeCurved(img)
            if data_c and "|" in data_c and len(data_c) >= 20:
                return data_c
    except Exception:
        pass

    return None


def try_read_qr_opencv(img_bgr: np.ndarray) -> str | None:
    """
    Escáner QR multi-etapa para tickets térmicos peruanos:
    Prueba en escala de grises, recorte inferior, zoom x2, nitidez (sharpen),
    CLAHE, Otsu y umbral adaptativo.
    """
    cv_detector = cv2.QRCodeDetector()
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Recorte de la mitad inferior (donde siempre va el QR de SUNAT)
    bottom_half = gray[int(h * 0.40):h, 0:w]
    # Recorte central-inferior (aislando el QR principal de tickets vecinos)
    bottom_center = gray[int(h * 0.45):int(h * 0.92), int(w * 0.15):int(w * 0.85)]

    # Filtro de nitidez (Sharpening) para bordes térmicos borrosos
    kernel_sharpen = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(bottom_half, -1, kernel_sharpen)

    # Contraste CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    bottom_clahe = clahe.apply(bottom_half)

    # Binarizaciones (Otsu y Adaptativa de bloque grande y mediano)
    _, otsu = cv2.threshold(bottom_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adapt_31 = cv2.adaptiveThreshold(bottom_clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 8)
    adapt_51 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 51, 10)

    # Zoom x2 y x0.75 sobre el recorte inferior (crucial cuando los módulos del QR son muy pequeños o muy grandes)
    zoom_in = cv2.resize(bottom_center, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, zoom_otsu = cv2.threshold(zoom_in, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    zoom_out = cv2.resize(bottom_half, None, fx=0.7, fy=0.7, interpolation=cv2.INTER_AREA)

    candidatos = [
        gray,
        bottom_half,
        bottom_clahe,
        sharpened,
        otsu,
        adapt_31,
        adapt_51,
        zoom_in,
        zoom_otsu,
        zoom_out,
    ]

    for cand in candidatos:
        res = _decode_single_image(cand, cv_detector)
        if res:
            return res

    return None


def extract_with_tesseract(image_bytes: bytes) -> dict:
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        raise ValueError("No se pudo decodificar la imagen con OpenCV.")

    # Si entraron directo al Paso 3 por forzar_fallback, igual intentamos el QR primero
    qr_raw = try_read_qr_opencv(img_bgr)
    if qr_raw:
        qr_data = parse_sunat_qr(qr_raw)
        if qr_data.get("ruc_emisor") and qr_data.get("total") is not None:
            print(f"   ⚡ QR SUNAT detectado dentro del fallback: {qr_raw}")
            qr_data["metodo_last_resort"] = "QR_LOCAL_RESCATE"
            return qr_data

    print("   🔍 Ejecutando EasyOCR optimizado para ticket térmico...")
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    h, w = gray.shape
    if w > 950:
        scale = 950.0 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    processed_img = clahe.apply(gray)

    reader = get_easyocr_reader()
    results = reader.readtext(processed_img, detail=1, paragraph=False, canvas_size=1000)

    results_sorted = sorted(results, key=lambda r: r[0][0][1])
    raw_lines = [text for (_, text, conf) in results_sorted if conf > 0.18]
    raw_text = "\n".join(raw_lines)

    parsed_ocr = parse_invoice_text(raw_text)
    parsed_ocr["metodo_last_resort"] = "EASYOCR_FLEXIBLE"
    return parsed_ocr