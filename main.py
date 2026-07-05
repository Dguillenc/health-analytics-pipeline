import logging
from datetime import datetime
from pipeline import extract, report, notify
from pipeline.transform_silver import run as silver_run
from pipeline.transform_gold import run as gold_run


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 50)
    logger.info(f"health-analytics-pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)

    try:
        # Capa Bronze: descarga y vuelca datos crudos
        extract.run()

        # Capa Silver: limpia y valida por dominio
        silver_run()

        # Capa Gold: agrega a nivel diario
        gold_run()

        # Genera informe con Gemini y envía por Telegram
        tabla_str, analisis, fecha_inicio, fecha_fin = report.run()
        notify.send_telegram(tabla_str, analisis, fecha_inicio, fecha_fin)

        logger.info("Pipeline completado")

    except Exception as e:
        logger.error(f"Error en el pipeline: {e}")
        notify.send_error(str(e))
        raise


if __name__ == "__main__":
    main()