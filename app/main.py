import os
import time
import asyncio
import numpy as np
import cv2
from fastapi import FastAPI, File, UploadFile, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="API de Extracción de Facturas y Boletas (Python)",
    version="1.0.2"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.services.gemini_service import extract_with_gemini
from app.services.ocr_fallback_service import extract_with_tesseract, try_read_qr_opencv
from app.utils.regex_parser import parse_sunat_qr


@app.get("/api/health")
def health_check():
    api_key = os.getenv("GEMINI_API_KEY", "")
    return {
        "ok": True,
        "mensaje": "Servidor FastAPI de extracción activo",
        "gemini_configurado": bool(api_key and api_key != "tu_api_key_aqui"),
        "forzar_fallback": os.getenv("FORCE_FALLBACK", "false").lower() == "true"
    }


@app.post("/api/procesar-factura")
async def procesar_factura(
    foto: UploadFile = File(...),
    forzar_fallback: bool = Query(False)
):
    start_time = time.time()

    allowed_types = ["image/jpeg", "image/png", "image/webp", "application/pdf"]
    if foto.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato no soportado. Sube una imagen JPG, PNG, WEBP o PDF."
        )

    image_bytes = await foto.read()
    file_size_kb = round(len(image_bytes) / 1024, 2)
    force_env = os.getenv("FORCE_FALLBACK", "false").lower() == "true"

    # =========================================================================
    # PASO 1: LECTOR QR LOCAL (PYZBAR + OPENCV) - Siempre corre primero (~0.04s)
    # =========================================================================
    try:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if img_bgr is not None:
            qr_raw = try_read_qr_opencv(img_bgr)
            if qr_raw:
                qr_data = parse_sunat_qr(qr_raw)
                if qr_data.get("ruc_emisor") and qr_data.get("total") is not None:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    print(f"   ⚡ [PASO 1] QR SUNAT detectado de inmediato ({elapsed_ms}ms): {qr_raw}")
                    return {
                        "ok": True,
                        "origen_extraccion": "LOCAL_QR_INSTANTANEO",
                        "confianza": "ALTA",
                        "tiempo_procesamiento_ms": elapsed_ms,
                        "archivo": {"nombre": foto.filename, "mimetype": foto.content_type, "tamano_kb": file_size_kb},
                        "datos": qr_data
                    }
    except Exception as qr_err:
        print(f"ℹ️ Omitiendo chequeo rápido de QR: {qr_err}")

    # =========================================================================
    # PASO 2: GEMINI EN LA NUBE (Se omite si forzar_fallback=True)
    # =========================================================================
    if not forzar_fallback and not force_env:
        try:
            print(f"[PASO 2] Procesando '{foto.filename}' con Gemini (Límite: 10s)...")
            datos_gemini = await asyncio.wait_for(
                asyncio.to_thread(extract_with_gemini, image_bytes, foto.content_type),
                timeout=5
            )
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "ok": True,
                "origen_extraccion": "GEMINI_FREE_TIER",
                "confianza": "ALTA",
                "tiempo_procesamiento_ms": elapsed_ms,
                "archivo": {"nombre": foto.filename, "mimetype": foto.content_type, "tamano_kb": file_size_kb},
                "datos": datos_gemini
            }
        except asyncio.TimeoutError:
            print("⏱️ ¡Gemini tardó más de 10 segundos! Activando Plan B local...")
        except Exception as e:
            print(f"⚠️ Gemini no disponible ({e}). Saltando al Plan B local...")

    # =========================================================================
    # PASO 3: RED NEURONAL LOCAL (EasyOCR de emergencia)
    # =========================================================================
    try:
        print(f"[PASO 3] Ejecutando EasyOCR local de emergencia...")
        datos_fallback = await asyncio.to_thread(extract_with_tesseract, image_bytes)
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "ok": True,
            "origen_extraccion": "OCR_LOCAL_EASYOCR",
            "confianza": "MEDIA_REQUIERE_REVISION",
            "advertencia": "Datos extraídos con EasyOCR local (Gemini no respondió o se omitió).",
            "tiempo_procesamiento_ms": elapsed_ms,
            "archivo": {"nombre": foto.filename, "mimetype": foto.content_type, "tamano_kb": file_size_kb},
            "datos": datos_fallback
        }
    except Exception as fallback_error:
        print(f"❌ Error crítico en todos los motores: {str(fallback_error)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallaron todos los métodos de extracción: {str(fallback_error)}"
        )