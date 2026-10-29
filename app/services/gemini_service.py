import os
import base64
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional, List

# Definición del esquema estructurado con Pydantic para Gemini
class ItemFactura(BaseModel):
    cantidad: Optional[float] = None
    descripcion: Optional[str] = None
    precio_unitario: Optional[float] = None
    importe_item: Optional[float] = None

class ComprobanteSchema(BaseModel):
    tipo_comprobante: Optional[str] = Field(None, description="FACTURA, BOLETA o TICKET")
    ruc_emisor: Optional[str] = Field(None, description="RUC de 11 dígitos del emisor")
    razon_social_emisor: Optional[str] = Field(None, description="Nombre o razón social de la empresa emisora")
    serie_numero: Optional[str] = Field(None, description="Ej: FA12-02183092 o F001-000432")
    fecha_emision: Optional[str] = Field(None, description="Formato YYYY-MM-DD")
    moneda: Optional[str] = Field(None, description="PEN o USD")
    documento_cliente: Optional[str] = Field(None, description="RUC o DNI del cliente")
    nombre_cliente: Optional[str] = Field(None, description="Nombre o razón social del cliente")
    subtotal: Optional[float] = Field(None, description="Subtotal o valor de venta")
    igv: Optional[float] = Field(None, description="Monto del IGV (18%)")
    total: Optional[float] = Field(None, description="Importe total a pagar")
    items: List[ItemFactura] = Field(default_factory=list)

def extract_with_gemini(image_bytes: bytes, mime_type: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "tu_api_key_aqui":
        raise ValueError("GEMINI_API_KEY no configurada en el archivo .env")

    print("   ➡️ Inicializando cliente genai.Client...")
    client = genai.Client(api_key=api_key)

    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    print("   ➡️ Enviando imagen al modelo gemini-3.8-flash...")
    response = client.models.generate_content(
        model='gemini-3.8-flash',
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            ),
            (
                "Analiza la imagen de este comprobante de pago (factura, boleta o ticket peruano). "
                "Extrae los datos contables con total precisión siguiendo estrictamente el esquema JSON solicitado."
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ComprobanteSchema,
        ),
    )

    print("   ⬅️ Respuesta recibida de Google AI Studio correctamente.")
    import json
    return json.loads(response.text)
