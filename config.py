import os
from pathlib import Path
from datetime import date
from dotenv import load_dotenv

# Cargamos las variables del archivo .env (solo en local)
# En GitHub Actions estas variables vienen de los Secrets
load_dotenv()

# =============================================================
# RUTAS
# =============================================================

# Raíz del proyecto — siempre apunta a esta carpeta,
# independientemente de desde dónde se ejecute el script
BASE_DIR = Path(__file__).resolve().parent

# Carpeta de datos locales (está en .gitignore, nunca sube a GitHub)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)  # la crea si no existe

# Rutas de archivos temporales que el pipeline genera en local
ZIP_PATH  = DATA_DIR / "salud.zip"
DB_PATH   = DATA_DIR / "health_connect_export.db"
DUCK_PATH = DATA_DIR / "health.duckdb"

# =============================================================
# CREDENCIALES — leídas desde variables de entorno
# Nunca hardcodeadas aquí
# =============================================================

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY")
GEMINI_URL       = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =============================================================
# CONSTANTES DE DOMINIO
# =============================================================

# Health Connect guarda fechas como días desde el Unix Epoch (01/01/1970)
# Necesitamos esta referencia para convertir esos números a fechas reales
EPOCH = date(1970, 1, 1)

# Python devuelve el día de la semana como número (0=lunes, 6=domingo)
# Este diccionario lo traduce a español para el informe
DIAS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles",
    3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
}

# Health Connect identifica los tipos de ejercicio con códigos numéricos
# Este diccionario los traduce a nombres legibles
EXERCISE_TYPE_MAP = {
    45: "Fuerza",
    53: "Running",
    58: "Senderismo",
    5:  "Otro"
}