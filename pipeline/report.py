import re
import time
import logging
import requests
import duckdb
import pandas as pd
from datetime import timedelta
from config import (
    DUCK_PATH,
    GEMINI_API_KEY,
    GEMINI_URL,
    DIAS_ES
)

logger = logging.getLogger(__name__)


def tabla_texto(semana: list) -> str:
    """
    Convierte la lista de días de la semana en texto formateado
    para enviar por Telegram. Cada día ocupa un bloque visual
    con emojis para facilitar la lectura en móvil.
    """
    EMOJI_DIA = {
        "Lunes": "🔵", "Martes": "🔵", "Miércoles": "🔵",
        "Jueves": "🔵", "Viernes": "🔵",
        "Sábado": "🟡", "Domingo": "🟡"
    }
    EMOJI_WORKOUT = {
        "Fuerza": "💪", "Running": "🏃",
        "Senderismo": "🥾", "Descanso": "😴", "Otro": "🏋️"
    }

    lineas = ["📅 RESUMEN DÍA A DÍA\n"]

    for d in semana:
        emo  = EMOJI_DIA.get(d["dia"], "🔵")
        wemo = EMOJI_WORKOUT.get(str(d["workout"]), "😴")
        hr   = f"{d['hr']} bpm" if str(d["hr"]) not in ["-", "nan"] else "sin datos"
        spo2 = f"{d['spo2']}%" if str(d["spo2"]) not in ["-", "nan"] else "sin datos"

        lineas.append(
            f"{emo} {d['dia']} ({d['fecha']})\n"
            f"   💤 Sueño: {d['sleep_h']}h  |  🧠 Profundo: {d['deep_min']}min  |  🌀 REM: {d['rem_min']}min\n"
            f"   🚶 Pasos: {d['steps']}  |  🔥 Kcal: {d['kcal']}\n"
            f"   {wemo} Entreno: {d['workout']} — {d['w_min']}min\n"
            f"   ❤️ FC reposo: {hr}  |  🩸 SpO2: {spo2}\n"
        )

    return "\n".join(lineas)


def build_prompt(semana: list, dm: pd.DataFrame, ultimo) -> str:
    """
    Construye el prompt que se envía a Gemini con los datos
    de la semana y las estadísticas comparativas.

    """
    tabla = tabla_texto(semana)

    dias_con_steps  = [d for d in semana if d["steps"] > 0]
    dias_con_sleep  = [d for d in semana if d["sleep_h"] != "-"]
    dias_con_hr     = [d for d in semana if str(d["hr"]) not in ["-", "nan"]]

    total_pasos    = sum(d["steps"] for d in dias_con_steps)
    total_entrenam = sum(1 for d in semana if d["workout"] not in ["-", "Descanso"])
    total_min_ent  = sum(d["w_min"] for d in semana if d["w_min"] not in ["-", 0])
    avg_sleep      = round(sum(float(d["sleep_h"]) for d in dias_con_sleep) / max(len(dias_con_sleep), 1), 2)
    avg_deep       = round(sum(float(d["deep_min"]) for d in dias_con_sleep if d["deep_min"] != "-") / max(len(dias_con_sleep), 1), 1)
    avg_hr         = round(sum(float(d["hr"]) for d in dias_con_hr) / max(len(dias_con_hr), 1), 1)

    # Comparativa con la semana anterior para detectar tendencias
    semana_ant_start = ultimo - timedelta(days=13)
    semana_ant_end   = ultimo - timedelta(days=7)
    semana_ant = dm[
        (dm["local_date"] >= semana_ant_start.isoformat()) &
        (dm["local_date"] <= semana_ant_end.isoformat())
    ]
    avg_steps_ant = round(semana_ant["steps"].mean(), 0) if not semana_ant["steps"].isna().all() else "N/A"
    avg_sleep_ant = round(semana_ant["sleep_hours"].mean(), 2) if not semana_ant["sleep_hours"].isna().all() else "N/A"

    return f"""
Eres un experto en salud, rendimiento físico y recuperación.
Genera un informe semanal conciso en español. El usuario entrena fuerza y practica BJJ.

DATOS DE LA SEMANA ({(ultimo - timedelta(days=6)).isoformat()} → {ultimo.isoformat()})

{tabla}

ESTADÍSTICAS:
- Total pasos: {total_pasos}
- Días de entrenamiento: {total_entrenam}/7
- Total minutos entrenados: {total_min_ent}
- Media sueño/noche: {avg_sleep}h
- Media sueño profundo/noche: {avg_deep}min
- Media FC reposo: {avg_hr} bpm

SEMANA ANTERIOR:
- Media pasos: {avg_steps_ant}
- Media sueño: {avg_sleep_ant}h

ESTRUCTURA (sé conciso, 1-2 líneas por sección):

📊 RESUMEN EJECUTIVO
💤 SUEÑO
🏃 ACTIVIDAD
💪 ENTRENAMIENTO
❤️ RECUPERACIÓN
⚠️ ALERTAS
✅ RECOMENDACIONES

Texto plano, sin asteriscos ni etiquetas. Máximo 2000 caracteres.
"""


def call_gemini(prompt: str, max_retries: int = 5) -> str:
    """
    Llama a la API de Gemini con reintentos automáticos.

    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 3000
        }
    }

    for intento in range(1, max_retries + 1):
        try:
            resp = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60
            )
            resp.raise_for_status()

            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

            # Limpiamos el texto de posibles artefactos de formato
            # que Gemini a veces añade aunque se lo pidamos que no
            content = re.sub(r'<[^>]+>', '', content)
            content = re.sub(r'```[a-z]*', '', content)
            content = re.sub(r'\*+', '', content)
            content = re.sub(r'\n\s*\n\s*\n', '\n\n', content).strip()

            return content

        except requests.exceptions.HTTPError as e:
            if resp.status_code == 503 and intento < max_retries:
                espera = intento * 10
                logger.warning(f"Gemini 503 (intento {intento}/{max_retries}). Reintentando en {espera}s...")
                time.sleep(espera)
                continue
            raise


def run() -> tuple:
    """
    Lee los datos de Gold, construye el prompt y llama a Gemini.
    Devuelve (tabla_str, analisis, fecha_inicio, fecha_fin)
    para que notify.py los envíe por Telegram.
    """
    logger.info("Generando informe semanal...")

    duck = duckdb.connect(str(DUCK_PATH))
    try:
        from pipeline.transform_gold import get_weekly_data
        semana, ultimo, dm = get_weekly_data(duck)
    finally:
        duck.close()

    tabla_str    = tabla_texto(semana)
    prompt       = build_prompt(semana, dm, ultimo)
    analisis     = call_gemini(prompt)
    fecha_inicio = (ultimo - timedelta(days=6)).isoformat()
    fecha_fin    = ultimo.isoformat()

    logger.info("Informe generado correctamente")
    return tabla_str, analisis, fecha_inicio, fecha_fin


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    tabla_str, analisis, fecha_inicio, fecha_fin = run()
    print("\n" + "="*50)
    print(tabla_str)
    print("="*50)
    print(analisis)
    
