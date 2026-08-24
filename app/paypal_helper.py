import requests
import base64
from flask import current_app


def _obtener_token():
    client_id = current_app.config['PAYPAL_CLIENT_ID']
    secret = current_app.config['PAYPAL_CLIENT_SECRET']
    base_url = current_app.config['PAYPAL_BASE_URL']

    credenciales = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    respuesta = requests.post(
        f"{base_url}/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credenciales}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data="grant_type=client_credentials",
        timeout=10
    )
    respuesta.raise_for_status()
    return respuesta.json()["access_token"]


def crear_orden(monto_ars, url_retorno, url_cancelacion, descripcion):
    """Crea una orden en PayPal y devuelve (order_id, url_aprobacion)."""
    base_url = current_app.config['PAYPAL_BASE_URL']
    tipo_cambio = current_app.config.get('PAYPAL_TIPO_CAMBIO', 1000.0)

    monto_usd = round(monto_ars / tipo_cambio, 2)
    if monto_usd < 0.01:
        monto_usd = 0.01

    token = _obtener_token()
    respuesta = requests.post(
        f"{base_url}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "description": descripcion[:127],
                "amount": {
                    "currency_code": "USD",
                    "value": str(monto_usd)
                }
            }],
            "application_context": {
                "return_url": url_retorno,
                "cancel_url": url_cancelacion,
                "brand_name": "Portal de Socios - Club Atletico",
                "locale": "es-AR",
                "user_action": "PAY_NOW"
            }
        },
        timeout=15
    )
    respuesta.raise_for_status()
    datos = respuesta.json()

    for enlace in datos.get("links", []):
        if enlace["rel"] == "approve":
            return datos["id"], enlace["href"]

    raise Exception(f"PayPal no devolvio enlace de aprobacion: {datos}")


def capturar_orden(order_id):
    """Captura (confirma) el pago de una orden ya aprobada por el usuario."""
    base_url = current_app.config['PAYPAL_BASE_URL']
    token = _obtener_token()
    respuesta = requests.post(
        f"{base_url}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=15
    )
    respuesta.raise_for_status()
    return respuesta.json()
