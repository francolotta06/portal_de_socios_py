import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'clave-secreta-para-las-sesiones-2026*')
    MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/portal_socios')
    # PayPal Sandbox
    # Obtene tus credenciales en: https://developer.paypal.com/dashboard/applications/sandbox
    PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', 'Abh0JxxPcISes03SpcFPUVPdEqebctbVuU_rBW8jjx10i6Ifc9UPOcxFKhzgRUeHd2Rsgm0V6i1IzgCv')
    PAYPAL_CLIENT_SECRET = os.environ.get('PAYPAL_CLIENT_SECRET', 'EBqGxr68iRR9n20WZwosZBTiizrQHJR-kdJIOCnqwxvHaL_8VbCuEPByGxgp3RDi9VG38Rfb_4aqLkcM')
    PAYPAL_BASE_URL = 'https://api-m.sandbox.paypal.com'

    # Tipo de cambio para sandbox: $1000 ARS = $1 USD (solo demo)
    PAYPAL_TIPO_CAMBIO = 9_999_999.0
