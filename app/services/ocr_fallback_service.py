import cv2
import numpy as np
import easyocr
from app.utils.regex_parser import parse_invoice_text, parse_sunat_qr

_ocr_reader = None

def get_easyocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        print("   📦 Cargando modelo neuronal EasyOCR en memoria...")
        _ocr_reader = easyocr.Reader(['es'], gpu=True, quantize=True)
    return _ocr_reader


def try_read_qr_opencv(img_bgr: np.ndarray) -> str | None:
    detector = cv2.QRCodeDetector()

    # Intentos progresivos con la imagen completa y con filtros de umbral
    h, w, _ = img_bgr.shape
    
    # Intento 1: Original
    data, _, _ = detector.detectAndDecode(img_bgr)
    if data and "|" in data:
        return data

    # Intento 2: Enfocar la mitad inferior (donde suele estar el QR en los tickets)
    bottom_half = img_bgr[int(h*0.5):h, 0:w]
    data, _, _ = detector.detectAndDecode(bottom_half)
    if data and "|" in data:
        return data

    # Intento 3: Binarización Otsu para resaltar el QR sobre el fondo oscuro
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
    data, _, _ = detector.detectAndDecode(thresh)
    if data and "|" in data:
        return data

    return None


def extract_with_tesseract(image_bytes: bytes) -> dict:
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if img_bgr is None:
        raise ValueError("No se pudo decodificar la imagen con OpenCV.")

    print("   🔍 Ejecutando EasyOCR optimizado para ticket térmico...")
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    
    # Redimensionar para acelerar CPU
    h, w = gray.shape
    if w > 900:
        scale = 900.0 / w
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    # Ecualización CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    processed_img = clahe.apply(gray)

    reader = get_easyocr_reader()
    results = reader.readtext(processed_img, detail=1, paragraph=False, canvas_size=1000)

    results_sorted = sorted(results, key=lambda r: r[0][0][1])
    raw_lines = [text for (_, text, conf) in results_sorted if conf > 0.15]
    raw_text = "\n".join(raw_lines)

    parsed_ocr = parse_invoice_text(raw_text)
    parsed_ocr["metodo_last_resort"] = "EASYOCR_FLEXIBLE"
    return parsed_ocr