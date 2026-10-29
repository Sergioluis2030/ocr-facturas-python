# API de Extracción de Facturas y Boletas en Python (FastAPI + Gemini + Fallback Tesseract)

Proyecto migrado a **Python (FastAPI)** listo para probar en local. Recibe la foto de una factura o boleta, extrae los campos estructurados usando **Gemini 3.8-flash (Free Tier)** y, si hay alta demanda (error 503), falla la red o se agota la cuota, activa automáticamente **PyTesseract en local**.

## 1. Requisitos previos en tu PC
Debes tener instalado **Python 3.10+** y el binario de **Tesseract-OCR** instalado en tu sistema (necesario para el fallback local).
- **Windows:** Descarga e instala Tesseract desde [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) y asegúrate de agregarlo al PATH o configurar su ruta.

## 2. Instalación rápida

1. Descomprime este archivo `.zip` y entra a la carpeta desde tu terminal:
   ```bash
   cd ocr-facturas-python
   ```
2. Crea y activa tu entorno virtual:
   ```bash
   python -m venv venv
   # En Windows:
   venv\Scripts\activate
   # En Linux / Mac:
   source venv/bin/activate
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Crea tu archivo `.env` copiando el ejemplo:
   ```bash
   cp .env.example .env
   ```
   *(O renombra `.env.example` a `.env`)* y coloca tu `GEMINI_API_KEY`.
5. Inicia el servidor:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

---

## 3. Cómo probar en Postman

- **Método:** `POST`
- **URL:** `http://localhost:8000/api/procesar-factura`
- **Body:** Selecciona `form-data`, crea una key llamada `foto` de tipo **File** y sube tu comprobante.
- **Forzar Fallback:** Puedes agregar el query param `?forzar_fallback=true` para probar el motor local directo.
