import logging
import duckdb
import pandas as pd
from datetime import date, timedelta
from config import DUCK_PATH, DIAS_ES

logger = logging.getLogger(__name__)


def build_gold(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Construye la tabla Gold uniendo todas las métricas Silver
    en una única tabla diaria lista para análisis y reporting.

    Gold = una fila por día, todas las métricas juntas.
    Es la única tabla que consume el módulo de reporting.

    Usamos LEFT JOINs desde steps como tabla base porque es
    la métrica más completa — casi todos los días tienen pasos,
    aunque no tengan peso o ejercicio registrado.
    """
    logger.info("Construyendo capa Gold...")

    duck.execute("DROP TABLE IF EXISTS gold_daily_metrics")
    duck.execute("""
        CREATE TABLE gold_daily_metrics AS

        SELECT
            -- fecha como clave principal de la tabla Gold
            COALESCE(st.local_date, sl.local_date) AS local_date,

            -- pasos
            COALESCE(st.steps, 0)                  AS steps,

            -- sueño
            sl.sleep_hours,
            sl.light_minutes,
            sl.deep_minutes,
            sl.rem_minutes,
            sl.awake_minutes,
            sl.sleep_efficiency,

            -- calorías activas
            ca.active_kcal,

            -- ejercicio
            COALESCE(ex.workouts, 0)               AS workouts,
            COALESCE(ex.workout_minutes, 0.0)      AS workout_minutes,
            COALESCE(ex.workout_type, 'Descanso')  AS workout_type,

            -- frecuencia cardíaca en reposo
            hr.resting_hr,

            -- SpO2
            sp.spo2_avg,
            sp.spo2_min,

            -- peso (forward-filled en Silver, siempre disponible)
            w.weight_kg,

            -- columna calculada: 1 si entrenó ese día, 0 si no
            -- útil para filtrar y contar días de entrenamiento
            CASE WHEN ex.workouts > 0 THEN 1 ELSE 0 END AS is_workout_day

        FROM silver_steps st

        -- FULL OUTER JOIN con sueño para no perder días
        -- donde hay sueño pero no pasos (o viceversa)
        FULL OUTER JOIN silver_sleep sl
            ON st.local_date = sl.local_date

        LEFT JOIN silver_calories ca
            ON COALESCE(st.local_date, sl.local_date) = ca.local_date

        LEFT JOIN silver_exercise ex
            ON COALESCE(st.local_date, sl.local_date) = ex.local_date

        LEFT JOIN silver_heart_rate hr
            ON COALESCE(st.local_date, sl.local_date) = hr.local_date

        LEFT JOIN silver_spo2 sp
            ON COALESCE(st.local_date, sl.local_date) = sp.local_date

        LEFT JOIN silver_weight w
            ON COALESCE(st.local_date, sl.local_date) = w.local_date

        ORDER BY local_date
    """)

    total = duck.execute("SELECT COUNT(*) FROM gold_daily_metrics").fetchone()[0]
    logger.info(f"  gold_daily_metrics — {total} filas")

    # Verificación de calidad — avisamos si hay fechas duplicadas
    # (no debería haber, pero mejor comprobarlo)
    duplicados = duck.execute("""
        SELECT COUNT(*) FROM (
            SELECT local_date, COUNT(*) as cnt
            FROM gold_daily_metrics
            GROUP BY local_date
            HAVING cnt > 1
        )
    """).fetchone()[0]

    if duplicados > 0:
        logger.warning(f"  ⚠ Se encontraron {duplicados} fechas duplicadas en Gold")
    else:
        logger.info("  Verificación OK — sin fechas duplicadas")


def get_weekly_data(duck: duckdb.DuckDBPyConnection) -> tuple:
    """
    Extrae los datos de la última semana completa de Gold
    para construir el informe semanal.

    Devuelve una tupla (semana, ultimo_dia) donde:
    - semana: lista de 7 diccionarios, uno por día
    - ultimo_dia: fecha del último día con datos de sueño
    """
    logger.info("Extrayendo datos semanales de Gold...")

    # Traemos toda la tabla Gold como DataFrame
    dm = duck.execute("SELECT * FROM gold_daily_metrics").df()

    # El último día con datos de sueño marca el fin de la semana
    # (el sueño es la métrica más tardía en registrarse cada día)
    ultimo = pd.to_datetime(
        dm[dm["sleep_hours"] > 0]["local_date"].max()
    ).date()

    semana = []
    for i in range(6, -1, -1):
        dia = ultimo - timedelta(days=i)
        fila = dm[dm["local_date"] == dia.isoformat()]
        nombre_dia = DIAS_ES[dia.weekday()]

        if not fila.empty:
            r = fila.iloc[0]
            semana.append({
                "fecha":    dia.isoformat(),
                "dia":      nombre_dia,
                "sleep_h":  round(float(r["sleep_hours"]), 1)
                            if pd.notna(r.get("sleep_hours")) else "-",
                "deep_min": round(float(r["deep_minutes"]), 0)
                            if pd.notna(r.get("deep_minutes")) else "-",
                "rem_min":  round(float(r["rem_minutes"]), 0)
                            if pd.notna(r.get("rem_minutes")) else "-",
                "steps":    int(r["steps"])
                            if pd.notna(r.get("steps")) else 0,
                "kcal":     round(float(r["active_kcal"]), 0)
                            if pd.notna(r.get("active_kcal")) else "-",
                "workout":  r.get("workout_type", "Descanso"),
                "w_min":    round(float(r["workout_minutes"]), 0)
                            if pd.notna(r.get("workout_minutes")) else 0,
                "hr":       round(float(r["resting_hr"]), 1)
                            if pd.notna(r.get("resting_hr")) else "-",
                "spo2":     round(float(r["spo2_avg"]), 1)
                            if pd.notna(r.get("spo2_avg")) else "-",
            })
        else:
            semana.append({
                "fecha":    dia.isoformat(),
                "dia":      nombre_dia,
                "sleep_h":  "-",
                "deep_min": "-",
                "rem_min":  "-",
                "steps":    0,
                "kcal":     "-",
                "workout":  "-",
                "w_min":    0,
                "hr":       "-",
                "spo2":     "-",
            })

    return semana, ultimo, dm


def run() -> None:
    """
    Punto de entrada de la capa Gold.
    Construye gold_daily_metrics uniendo todas las tablas Silver.
    """
    duck = duckdb.connect(str(DUCK_PATH))
    try:
        build_gold(duck)
    finally:
        duck.close()

    logger.info("Capa Gold completada")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    run()