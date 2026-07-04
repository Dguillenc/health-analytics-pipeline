import os
import time
import logging
import zipfile
import shutil
import sqlite3

import duckdb
import gdown
import pandas as pd
import requests
from pathlib import Path
from dotenv import load_dotenv

from config import (
    GDRIVE_FOLDER_ID,
    ZIP_PATH,
    DB_PATH,
    DUCK_PATH,
    DATA_DIR
)

# Cargamos variables de entorno (solo necesario al ejecutar este
# módulo directamente, main.py ya lo hace para el pipeline completo)
load_dotenv()

# Cada módulo tiene su propio logger — así en los logs sabemos
# exactamente qué módulo generó cada mensaje
logger = logging.getLogger(__name__)


def download_zip() -> None:
    """
    Descarga el ZIP de salud desde la carpeta de Google Drive.
    Usamos URL de carpeta en vez de ID de archivo para que funcione
    aunque Health Connect regenere el archivo cada semana.
    La carpeta debe estar compartida como 'cualquiera con el enlace'.
    """
    logger.info("Descargando ZIP desde Google Drive...")

    # Carpeta temporal de descarga — la limpiamos antes de empezar
    # para evitar que queden ZIPs viejos de ejecuciones anteriores
    tmp_dir = DATA_DIR / "drive_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    folder_url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"

    gdown.download_folder(
        url=folder_url,
        output=str(tmp_dir),
        quiet=False,
        use_cookies=False
    )

    # Buscamos el ZIP descargado dentro de la carpeta temporal
    zips = list(tmp_dir.glob("*.zip"))

    if not zips:
        raise FileNotFoundError(
            "No se encontró ningún ZIP en la carpeta de Drive. "
            "Verifica que la carpeta está compartida como "
            "'cualquiera con el enlace'."
        )

    # Si hubiera varios ZIPs tomamos el más reciente por seguridad
    zip_reciente = sorted(
        zips,
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )[0]

    logger.info(f"ZIP encontrado: {zip_reciente.name}")

    # Movemos el ZIP a su ubicación definitiva y borramos el temporal
    # rename() mueve el archivo sin copiarlo — más eficiente
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()  # borramos el ZIP anterior si existe
    zip_reciente.rename(ZIP_PATH)
    shutil.rmtree(tmp_dir)

    logger.info(f"ZIP guardado en {ZIP_PATH}")


def extract_db() -> None:
    """
    Extrae el archivo .db del ZIP descargado.
    El .db es la base de datos SQLite que genera Health Connect
    con todos los registros de salud del reloj.
    Los datos se guardan en data/ que está en .gitignore —
    nunca llegan a GitHub.
    """
    logger.info("Extrayendo base de datos del ZIP...")

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        # Buscamos el primer .db dentro del ZIP
        db_name = next(
            (n for n in z.namelist() if n.endswith(".db")),
            None
        )

        if not db_name:
            raise FileNotFoundError(
                "No se encontró ningún .db dentro del ZIP. "
                "El formato del export de Health Connect puede haber cambiado."
            )

        # Copiamos el .db del ZIP al disco
        # "wb" = write binary, porque SQLite es un archivo binario
        with z.open(db_name) as src, open(DB_PATH, "wb") as dst:
            dst.write(src.read())

    logger.info(f"DB extraída en {DB_PATH}")


def load_bronze() -> None:
    """
    Vuelca las tablas crudas de SQLite a DuckDB (capa Bronze).

    Bronze = datos exactamente como vienen de la fuente, sin ninguna
    transformación. Si el dato original está mal, Bronze lo guarda
    igual — eso es intencionado. Silver y Gold son las capas que
    limpian y transforman.

    Convención de nombres: prefijo 'bronze_' en todas las tablas
    de esta capa, siguiendo la arquitectura Medallion.
    """
    logger.info("Volcando datos crudos a DuckDB (capa Bronze)...")

    # Fuente: SQLite generado por Health Connect
    sqlite_conn = sqlite3.connect(DB_PATH)

    # Destino: DuckDB, nuestra base de datos analítica
    # El archivo .duckdb está en data/ — nunca sube a GitHub
    duck_conn = duckdb.connect(str(DUCK_PATH))

    # Tablas que exporta Health Connect en el .db
    # Si en el futuro añade nuevas tablas, solo hay que añadirlas aquí
    tablas = [
        "sleep_session_record_table",
        "sleep_stages_table",
        "steps_record_table",
        "active_calories_burned_record_table",
        "exercise_session_record_table",
        "resting_heart_rate_record_table",
        "oxygen_saturation_record_table",
        "weight_record_table",
    ]

    for tabla in tablas:
        try:
            # Leemos la tabla completa de SQLite a un DataFrame
            df = pd.read_sql(f"SELECT * FROM {tabla}", sqlite_conn)

            # Registramos el DataFrame como vista temporal en DuckDB
            duck_conn.register("df_temp", df)

            # Borramos la tabla Bronze si ya existía de una ejecución
            # anterior y la recreamos con los datos frescos de hoy.
            # En Bronze siempre volcamos todo desde cero — es la capa
            # de datos crudos, no necesitamos historial aquí.
            duck_conn.execute(f"DROP TABLE IF EXISTS bronze_{tabla}")
            duck_conn.execute(f"""
                CREATE TABLE bronze_{tabla} AS
                SELECT * FROM df_temp
            """)

            logger.info(f"  bronze_{tabla} — {len(df)} filas")

        except Exception as e:
            logger.warning(f"  No se pudo volcar {tabla}: {e}")


def run() -> None:
    """
    Punto de entrada de la capa Extract.
    main.py llama solo a esta función — no necesita saber
    nada de lo que hay dentro.

    Orden de ejecución:
    1. Descarga el ZIP de Drive
    2. Extrae el .db del ZIP
    3. Vuelca los datos crudos a DuckDB (Bronze)
    """
    download_zip()
    extract_db()
    load_bronze()


if __name__ == "__main__":
    # Configuración de logging solo cuando ejecutamos este módulo
    # directamente para pruebas — en producción lo configura main.py
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    run()