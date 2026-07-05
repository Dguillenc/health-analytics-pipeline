import pytest
import pandas as pd
import duckdb
from datetime import date, timedelta

# Importamos las funciones que vamos a testear
from pipeline.transform_silver import int_to_date
from pipeline.transform_gold import get_weekly_data
from config import EPOCH, DIAS_ES


# ================================================================
# Tests de int_to_date
# Verificamos que la conversión de entero a fecha es correcta.
# Esta función es crítica — si falla, todas las fechas del
# pipeline están mal y el informe muestra datos del día incorrecto.
# ================================================================

def test_int_to_date_valor_conocido():
    """El día 0 del Epoch es el 1 de enero de 1970."""
    assert int_to_date(0) == "1970-01-01"


def test_int_to_date_devuelve_string():
    """La función debe devolver siempre un string, no un objeto date."""
    resultado = int_to_date(19000)
    assert isinstance(resultado, str)


def test_int_to_date_formato_correcto():
    """El formato debe ser siempre YYYY-MM-DD (10 caracteres)."""
    resultado = int_to_date(20000)
    assert len(resultado) == 10
    partes = resultado.split("-")
    assert len(partes) == 3  # año, mes, día


def test_int_to_date_consistencia():
    """Días consecutivos deben producir fechas consecutivas."""
    dia_n   = int_to_date(20000)
    dia_n1  = int_to_date(20001)
    fecha_n  = date.fromisoformat(dia_n)
    fecha_n1 = date.fromisoformat(dia_n1)
    assert fecha_n1 - fecha_n == timedelta(days=1)


# ================================================================
# Tests de la capa Gold con datos sintéticos
# Creamos una base de datos DuckDB en memoria con datos de prueba
# para verificar que Gold se construye correctamente sin depender
# del archivo real de datos (que no está en GitHub).
# ================================================================

@pytest.fixture
def duck_con_silver():
    """
    Fixture: crea una DuckDB en memoria con tablas Silver mínimas.
    Un fixture es código que pytest ejecuta antes de cada test
    para preparar el entorno — como hacer la cama antes de dormir.
    """
    con = duckdb.connect(":memory:")  # en memoria, sin archivo

    # Creamos tablas Silver con datos sintéticos suficientes
    # para que Gold pueda construirse correctamente
    con.execute("""
        CREATE TABLE silver_steps AS
        SELECT '2026-06-23' AS local_date, 8000 AS steps
        UNION ALL
        SELECT '2026-06-22', 7500
    """)

    con.execute("""
        CREATE TABLE silver_sleep AS
        SELECT '2026-06-23' AS local_date,
               7.5 AS sleep_hours, 90.0 AS light_minutes,
               60.0 AS deep_minutes, 45.0 AS rem_minutes,
               20.0 AS awake_minutes, 0.95 AS sleep_efficiency
        UNION ALL
        SELECT '2026-06-22',
               6.5, 80.0, 50.0, 40.0, 15.0, 0.96
    """)

    con.execute("""
        CREATE TABLE silver_calories AS
        SELECT '2026-06-23' AS local_date, 450.0 AS active_kcal
        UNION ALL
        SELECT '2026-06-22', 380.0
    """)

    con.execute("""
        CREATE TABLE silver_exercise AS
        SELECT '2026-06-23' AS local_date,
               1 AS workouts, 60.0 AS workout_minutes,
               'Fuerza' AS workout_type
        UNION ALL
        SELECT '2026-06-22', 0, 0.0, 'Descanso'
    """)

    con.execute("""
        CREATE TABLE silver_heart_rate AS
        SELECT '2026-06-23' AS local_date, 52 AS resting_hr
        UNION ALL
        SELECT '2026-06-22', 54
    """)

    con.execute("""
        CREATE TABLE silver_spo2 AS
        SELECT '2026-06-23' AS local_date,
               97.5 AS spo2_avg, 96.0 AS spo2_min
        UNION ALL
        SELECT '2026-06-22', 98.0, 97.0
    """)

    con.execute("""
        CREATE TABLE silver_weight AS
        SELECT '2026-06-23' AS local_date, 78.5 AS weight_kg
        UNION ALL
        SELECT '2026-06-22', 78.5
    """)

    yield con  # entregamos la conexión al test
    con.close()  # cerramos al terminar, aunque el test falle


def test_gold_se_construye(duck_con_silver):
    """Gold debe construirse sin errores con datos Silver válidos."""
    from pipeline.transform_gold import build_gold
    build_gold(duck_con_silver)
    count = duck_con_silver.execute(
        "SELECT COUNT(*) FROM gold_daily_metrics"
    ).fetchone()[0]
    assert count == 2


def test_gold_sin_duplicados(duck_con_silver):
    """Gold no debe tener fechas duplicadas."""
    from pipeline.transform_gold import build_gold
    build_gold(duck_con_silver)
    duplicados = duck_con_silver.execute("""
        SELECT COUNT(*) FROM (
            SELECT local_date, COUNT(*) as cnt
            FROM gold_daily_metrics
            GROUP BY local_date HAVING cnt > 1
        )
    """).fetchone()[0]
    assert duplicados == 0


def test_gold_workout_type_descanso(duck_con_silver):
    """
    Los días sin ejercicio deben tener workout_type = 'Descanso',
    no NULL — es importante para el informe de Telegram.
    """
    from pipeline.transform_gold import build_gold
    build_gold(duck_con_silver)
    resultado = duck_con_silver.execute("""
        SELECT workout_type FROM gold_daily_metrics
        WHERE local_date = '2026-06-22'
    """).fetchone()[0]
    assert resultado == "Descanso"