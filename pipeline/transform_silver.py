import logging
import duckdb
import pandas as pd
from datetime import date, timedelta
from config import (
    DUCK_PATH,
    EPOCH,
    EXERCISE_TYPE_MAP
)

logger = logging.getLogger(__name__)


def int_to_date(n) -> str:
    """
    Convierte un entero de días desde el Unix Epoch (01/01/1970)
    al formato de fecha estándar 'YYYY-MM-DD'.
    Health Connect guarda todas las fechas como este entero,
    no como texto — necesitamos convertirlo para que sea legible.
    """
    return (EPOCH + timedelta(days=int(n))).isoformat()


def silver_sleep(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma los datos de sueño de Bronze a Silver.

    Lo que hacemos aquí:
    - Calculamos horas de sueño por sesión (Bronze guarda milisegundos)
    - Unimos con las etapas (profundo, REM, ligero, despierto)
    - Convertimos fechas de entero a texto legible
    - Calculamos la eficiencia del sueño
    - Filtramos sesiones claramente erróneas (menos de 30 minutos)
    """
    logger.info("Transformando datos de sueño (Silver)...")

    df_sesiones = duck.execute("""
        SELECT
            local_date,
            -- convertimos milisegundos a horas
            SUM((end_time - start_time) / 1000.0 / 3600.0) AS sleep_hours,
            -- app_info_id=4 es el reloj CMF, filtramos otras fuentes
            app_info_id
        FROM bronze_sleep_session_record_table
        WHERE app_info_id = 4
        GROUP BY local_date, app_info_id
    """).df()

    df_etapas = duck.execute("""
        SELECT
            s.local_date,
            -- sueño ligero (stage_type=4)
            SUM(CASE WHEN st.stage_type = 4
                THEN (st.stage_end_time - st.stage_start_time) / 1000.0 / 60.0
                ELSE 0 END) AS light_minutes,
            -- sueño profundo (stage_type=5)
            SUM(CASE WHEN st.stage_type = 5
                THEN (st.stage_end_time - st.stage_start_time) / 1000.0 / 60.0
                ELSE 0 END) AS deep_minutes,
            -- sueño REM (stage_type=6)
            SUM(CASE WHEN st.stage_type = 6
                THEN (st.stage_end_time - st.stage_start_time) / 1000.0 / 60.0
                ELSE 0 END) AS rem_minutes,
            -- minutos despierto dentro de la sesión (stage_type=1)
            SUM(CASE WHEN st.stage_type = 1
                THEN (st.stage_end_time - st.stage_start_time) / 1000.0 / 60.0
                ELSE 0 END) AS awake_minutes
        FROM bronze_sleep_stages_table st
        -- JOIN para traer la fecha desde la tabla de sesiones
        INNER JOIN bronze_sleep_session_record_table s
            ON st.parent_key = s.row_id
        GROUP BY s.local_date
    """).df()

    # Unimos sesiones con etapas por fecha
    df = df_sesiones.merge(df_etapas, on="local_date", how="left")

    # Convertimos la fecha de entero a texto legible
    df["local_date"] = df["local_date"].apply(int_to_date)

    # Eficiencia del sueño: tiempo dormido real / tiempo total en cama

    df["sleep_efficiency"] = (
        (df["sleep_hours"] * 60 - df["awake_minutes"])
        / (df["sleep_hours"] * 60)
    ).clip(0, 1).round(3)

    # Filtramos sesiones claramente erróneas (menos de 30 minutos)
    # el reloj a veces registra siestas accidentales o errores
    df = df[df["sleep_hours"] >= 0.5].copy()

    # Guardamos en Silver — DROP + CREATE para refrescar siempre
    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_sleep")
    duck.execute("""
        CREATE TABLE silver_sleep AS
        SELECT
            local_date,
            ROUND(sleep_hours, 2)      AS sleep_hours,
            ROUND(light_minutes, 1)    AS light_minutes,
            ROUND(deep_minutes, 1)     AS deep_minutes,
            ROUND(rem_minutes, 1)      AS rem_minutes,
            ROUND(awake_minutes, 1)    AS awake_minutes,
            sleep_efficiency
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_sleep — {duck.execute('SELECT COUNT(*) FROM silver_sleep').fetchone()[0]} filas")


def silver_steps(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma los datos de pasos de Bronze a Silver.

    app_info_id=4 filtra solo los registros del reloj CMF,
    descartando pasos registrados por otras apps (Google Fit, etc.)
    que podrían duplicar los datos.
    """
    logger.info("Transformando datos de pasos (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            SUM(count) AS steps
        FROM bronze_steps_record_table
        WHERE app_info_id = 4
        GROUP BY local_date
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    # Filtramos días con 0 pasos — probablemente no tenia puesto el reloj
    df = df[df["steps"] > 0].copy()

    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_steps")
    duck.execute("""
        CREATE TABLE silver_steps AS
        SELECT
            local_date,
            CAST(steps AS INTEGER) AS steps
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_steps — {duck.execute('SELECT COUNT(*) FROM silver_steps').fetchone()[0]} filas")


def silver_calories(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma las calorías activas de Bronze a Silver.

    La energía en Bronze viene en julios — dividimos entre 1000
    para convertir a kilojulios, que es la unidad estándar de
    Health Connect para calorías activas (equivalente a kcal).
    """
    logger.info("Transformando datos de calorías (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            -- Health Connect guarda energía en julios, convertimos a kcal
            SUM(energy) / 1000.0 AS active_kcal
        FROM bronze_active_calories_burned_record_table
        WHERE app_info_id = 4
        GROUP BY local_date
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_calories")
    duck.execute("""
        CREATE TABLE silver_calories AS
        SELECT
            local_date,
            ROUND(active_kcal, 1) AS active_kcal
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_calories — {duck.execute('SELECT COUNT(*) FROM silver_calories').fetchone()[0]} filas")


def silver_exercise(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma los datos de ejercicio de Bronze a Silver.

    Health Connect guarda el tipo de ejercicio como código numérico.
    Aquí lo traducimos a texto legible usando EXERCISE_TYPE_MAP
    de config.py. También calculamos el tipo dominante del día
    (el entreno más largo si hubo varios en el mismo día).
    """
    logger.info("Transformando datos de ejercicio (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            COUNT(*)                                          AS workouts,
            SUM((end_time - start_time) / 1000.0 / 60.0)    AS workout_minutes,
            exercise_type
        FROM bronze_exercise_session_record_table
        GROUP BY local_date, exercise_type
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    # Traducimos código numérico a nombre legible

    df["exercise_type_name"] = df["exercise_type"].map(EXERCISE_TYPE_MAP).fillna("Otro")

    # Tipo dominante = el entreno con más minutos ese día
    dominant = (
        df.sort_values("workout_minutes", ascending=False)
        .groupby("local_date")["exercise_type_name"]
        .first()
        .reset_index()
        .rename(columns={"exercise_type_name": "workout_type"})
    )

    # Agregamos todo a nivel día
    df_day = (
        df.groupby("local_date")
        .agg(
            workouts=("workouts", "sum"),
            workout_minutes=("workout_minutes", "sum")
        )
        .reset_index()
        .merge(dominant, on="local_date", how="left")
    )

    duck.register("df_temp", df_day)
    duck.execute("DROP TABLE IF EXISTS silver_exercise")
    duck.execute("""
        CREATE TABLE silver_exercise AS
        SELECT
            local_date,
            CAST(workouts AS INTEGER)          AS workouts,
            ROUND(workout_minutes, 1)          AS workout_minutes,
            workout_type
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_exercise — {duck.execute('SELECT COUNT(*) FROM silver_exercise').fetchone()[0]} filas")


def silver_heart_rate(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma la frecuencia cardíaca en reposo de Bronze a Silver.

    Filtramos valores por encima de 100 bpm — son mediciones erróneas
    del sensor, no FC en reposo real. Una FC en reposo de 100+ bpm
    indicaría taquicardia grave y el reloj no mide en reposo en esos
    momentos, son artefactos de medición.
    """
    logger.info("Transformando datos de FC en reposo (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            -- mínimo del día como proxy de FC en reposo real
            MIN(beats_per_minute) AS resting_hr
        FROM bronze_resting_heart_rate_record_table
        WHERE beats_per_minute <= 100
        GROUP BY local_date
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_heart_rate")
    duck.execute("""
        CREATE TABLE silver_heart_rate AS
        SELECT
            local_date,
            CAST(resting_hr AS INTEGER) AS resting_hr
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_heart_rate — {duck.execute('SELECT COUNT(*) FROM silver_heart_rate').fetchone()[0]} filas")


def silver_spo2(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma los datos de SpO2 de Bronze a Silver.

    Filtramos lecturas por debajo del 85% — son errores del sensor
    (dedo mal colocado, movimiento). Una SpO2 real por debajo del 85%
    es una emergencia médica grave, no un dato de salud rutinario.
    """
    logger.info("Transformando datos de SpO2 (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            ROUND(AVG(percentage), 2) AS spo2_avg,
            MIN(percentage)           AS spo2_min
        FROM bronze_oxygen_saturation_record_table
        WHERE percentage >= 85
        GROUP BY local_date
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_spo2")
    duck.execute("""
        CREATE TABLE silver_spo2 AS
        SELECT
            local_date,
            spo2_avg,
            spo2_min
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_spo2 — {duck.execute('SELECT COUNT(*) FROM silver_spo2').fetchone()[0]} filas")


def silver_weight(duck: duckdb.DuckDBPyConnection) -> None:
    """
    Limpia y transforma los datos de peso de Bronze a Silver.

    El peso viene en gramos en Health Connect — dividimos entre 1000
    para convertir a kg. Aplicamos forward-fill para los días sin
    medición: si no te pesaste hoy, asumimos el mismo peso que el
    último día registrado. Esto es más honesto que dejar NaN.
    """
    logger.info("Transformando datos de peso (Silver)...")

    df = duck.execute("""
        SELECT
            local_date,
            -- Health Connect guarda el peso en gramos
            weight / 1000.0 AS weight_kg
        FROM bronze_weight_record_table
        ORDER BY local_date
    """).df()

    df["local_date"] = df["local_date"].apply(int_to_date)

    # Creamos un rango de fechas completo desde el primer registro

    all_dates = pd.DataFrame({
        "local_date": pd.date_range(
            start=df["local_date"].min(),
            end=date.today().isoformat()
        ).strftime("%Y-%m-%d").tolist()
    })

    # Merge y forward-fill — los días sin medición heredan el peso anterior
    df = all_dates.merge(df, on="local_date", how="left")
    df["weight_kg"] = df["weight_kg"].ffill().round(2)

    duck.register("df_temp", df)
    duck.execute("DROP TABLE IF EXISTS silver_weight")
    duck.execute("""
        CREATE TABLE silver_weight AS
        SELECT
            local_date,
            weight_kg
        FROM df_temp
        ORDER BY local_date
    """)

    logger.info(f"  silver_weight — {duck.execute('SELECT COUNT(*) FROM silver_weight').fetchone()[0]} filas")


def run() -> None:
    """
    Punto de entrada de la capa Silver.
    Transforma todas las métricas de Bronze a Silver en orden.
    Si una métrica falla, el pipeline sigue con las demás.
    """
    logger.info("Iniciando transformaciones Silver...")

    duck = duckdb.connect(str(DUCK_PATH))

    try:
        silver_sleep(duck)
        silver_steps(duck)
        silver_calories(duck)
        silver_exercise(duck)
        silver_heart_rate(duck)
        silver_spo2(duck)
        silver_weight(duck)
    finally:
        # El bloque finally garantiza que la conexión se cierra
        # aunque alguna transformación falle
        duck.close()

    logger.info("Capa Silver completada")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    run()