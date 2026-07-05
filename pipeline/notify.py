import logging
import requests
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send_telegram(tabla_str: str, analisis: str, fecha_inicio: str, fecha_fin: str) -> None:
    """
    Envía el informe semanal por Telegram en dos mensajes:
    1. La tabla día a día con los datos crudos
    2. El análisis experto generado por Gemini

    Dividimos en chunks de 4000 caracteres porque Telegram
    tiene un límite de 4096 caracteres por mensaje.
    """
    msg1 = f"📊 INFORME SEMANAL\n{fecha_inicio} → {fecha_fin}\n\n{tabla_str}"
    msg2 = f"🤖 ANÁLISIS EXPERTO\n\n{analisis}"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    for msg in [msg1, msg2]:
        # Dividimos mensajes largos en chunks de 4000 caracteres
        chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
        for chunk in chunks:
            resp = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk},
                timeout=30
            )
            resp.raise_for_status()

    logger.info("Informe enviado por Telegram")


def send_error(mensaje: str) -> None:
    """
    Envía un mensaje de error por Telegram cuando el pipeline falla.
    Así recibimos una notificación inmediata en el móvil si algo
    sale mal el domingo por la mañana.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"❌ Error en el pipeline:\n{mensaje}"
            },
            timeout=30
        )
    except Exception:
        # Si falla el envío del error, no queremos otro error —
        # simplemente lo ignoramos y dejamos que el log lo capture
        logger.error("No se pudo enviar el error por Telegram")
        