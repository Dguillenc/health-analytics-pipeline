# 🏥 Health Analytics Pipeline

> Pipeline de datos end-to-end que procesa métricas de salud desde un smartwatch hasta un informe semanal con análisis de IA — completamente automatizado.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-1.1.3-yellow?logo=duckdb&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automated-2088FF?logo=githubactions&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash_Lite-4285F4?logo=google&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-7_passed-brightgreen?logo=pytest&logoColor=white)
![Pipeline](https://github.com/Dguillenc/Health-analytics-pipeline/actions/workflows/weekly.yml/badge.svg)
---

## 📐 Arquitectura

Fuente de datos:
CMF Watch Pro 2 → Health Connect → Google Drive (ZIP semanal)

Pipeline — GitHub Actions cada domingo a las 9:00 AM

🥉 Bronze — descarga el ZIP de Drive y vuelca las 8 tablas crudas a DuckDB sin modificar nada

🥈 Silver — limpia y valida cada métrica: timestamps, filtros de sensor, traducción de códigos

🥇 Gold — une todas las métricas en una tabla diaria lista para análisis

🤖 Report — Gemini 2.5 Flash Lite analiza los datos y genera el informe

📱 Notify — el informe llega por Telegram cada domingo por la mañana

---

## 🛠️ Stack técnico

| Capa | Tecnología | Por qué |
|------|-----------|---------|
| Orquestación | GitHub Actions | Cron gratuito, sin servidor |
| Almacenamiento | DuckDB | Base de datos analítica embebida, SQL completo |
| Transformación | pandas + SQL | ETL por capas con arquitectura Medallion |
| IA | Gemini 2.5 Flash Lite | Mayor cuota gratuita, menor latencia |
| Notificaciones | Telegram Bot API | Informe directo al móvil |
| Testing | pytest | 7 tests unitarios sobre transformaciones críticas |
| Lenguaje | Python 3.11 | |

---

## 📁 Estructura del proyecto

| Archivo | Función |
|---|---|
| `pipeline/extract.py` | Bronze: descarga y vuelca a DuckDB |
| `pipeline/transform_silver.py` | Silver: limpieza por dominio |
| `pipeline/transform_gold.py` | Gold: agregación diaria |
| `pipeline/report.py` | Análisis con Gemini AI |
| `pipeline/notify.py` | Envío por Telegram |
| `tests/test_transform.py` | 7 tests unitarios con pytest |
| `.github/workflows/weekly.yml` | Cron dominical automatizado |
| `config.py` | Configuración centralizada |
| `main.py` | Orquestador del pipeline |
| `requirements.txt` | Dependencias con versiones fijas |

---

## ⚙️ Cómo funciona

Cada domingo a las 9:00 AM GitHub Actions ejecuta el pipeline automáticamente:

### 🥉 Bronze — Extract
Descarga el ZIP de Google Drive usando la URL de carpeta (no ID de archivo, para que funcione aunque Health Connect regenere el fichero cada semana). Extrae la base de datos SQLite y vuelca las 8 tablas crudas a DuckDB sin modificar ningún valor.

### 🥈 Silver — Transform
Limpia y valida cada métrica de forma independiente:
- Convierte timestamps de milisegundos a fechas legibles (`YYYY-MM-DD`)
- Filtra lecturas erróneas del sensor (FC en reposo >100 bpm, SpO2 <85%)
- Traduce códigos numéricos de Health Connect a texto (`45 → "Fuerza"`)
- Aplica forward-fill en el peso para días sin medición
- Calcula eficiencia del sueño: `(tiempo dormido / tiempo en cama).clip(0,1)`

### 🥇 Gold — Aggregate
Une las 7 tablas Silver en `gold_daily_metrics` mediante JOINs, con una fila por día. Calcula métricas derivadas como `is_workout_day` e incluye verificación automática de duplicados.

### 🤖 Report + Notify
Construye un prompt estructurado con los datos de la semana, estadísticas comparativas con la semana anterior y lo envía a Gemini 2.5 Flash Lite. Implementa backoff progresivo ante errores 503 (hasta 5 reintentos). El informe llega por Telegram en dos mensajes: resumen día a día y análisis experto.

---

## 📊 Métricas procesadas

| Métrica | Fuente | Transformación Silver |
|---------|--------|----------------------|
| Sueño (horas, etapas, eficiencia) | `sleep_session_record_table` + `sleep_stages_table` | JOIN, ms→horas, filtro >30min |
| Pasos diarios | `steps_record_table` | Filtro por `app_info_id=4` (solo reloj) |
| Calorías activas | `active_calories_burned_record_table` | Julios → kcal |
| Sesiones de entrenamiento | `exercise_session_record_table` | Tipo dominante del día |
| FC en reposo | `resting_heart_rate_record_table` | Filtro ≤100 bpm |
| SpO2 | `oxygen_saturation_record_table` | Filtro ≥85%, media diaria |
| Peso corporal | `weight_record_table` | Gramos → kg, forward-fill |

---

## 🚀 Ejecución local

```bash
# Clona el repo
git clone https://github.com/Dguillenc/health-analytics-pipeline.git
cd health-analytics-pipeline

# Instala dependencias
pip install -r requirements.txt

# Configura las variables de entorno
cp .env.example .env
# Edita .env con tus credenciales

# Ejecuta el pipeline completo
python main.py

# Ejecuta solo los tests
python -m pytest tests/ -v
```

---

## 🔐 Variables de entorno

```bash
# .env.example
GDRIVE_FOLDER_ID=   # ID de la carpeta de Google Drive con el export
GEMINI_API_KEY=     # API key de Google AI Studio
TELEGRAM_TOKEN=     # Token del bot de Telegram (@BotFather)
TELEGRAM_CHAT_ID=   # Chat ID donde se envía el informe
```

En GitHub Actions estas variables se configuran como **Secrets** en `Settings → Secrets and variables → Actions`.

---

## 🧠 Decisiones de diseño

**¿Por qué DuckDB y no pandas puro?**
DuckDB permite ejecutar SQL completo sobre DataFrames en memoria sin servidor. Las operaciones de JOIN y agregación que construyen Gold son significativamente más rápidas y legibles en SQL que encadenando operaciones pandas. Además, el archivo `.duckdb` persiste el estado de cada capa entre ejecuciones.

**¿Por qué arquitectura Medallion?**
Separa claramente las responsabilidades: Bronze garantiza que nunca se pierden los datos originales, Silver centraliza toda la lógica de limpieza en un solo sitio, Gold es la única fuente de verdad para el reporting. Si Health Connect cambia el formato de exportación, solo hay que modificar Bronze y Silver — Gold y Report no se tocan.

**¿Por qué Gemini Flash Lite y no Flash?**
Para análisis de texto estructurado con instrucciones claras no se necesita el modelo más potente. Flash Lite tiene mayor cuota gratuita en el tier free (1.000 req/día vs 500) y menor latencia, lo que reduce los errores 503 por sobrecarga que son frecuentes en el tier gratuito durante horas pico.

**¿Por qué buscar por carpeta y no por ID de archivo?**
Health Connect puede generar un archivo nuevo con ID distinto en cada exportación. Apuntar al ID de la carpeta (que nunca cambia) y descargar el ZIP que encuentra dentro hace el pipeline resiliente a ese comportamiento, sin depender de actualizar manualmente el ID cada semana.

---

## 📈 Resultado

Cada domingo recibo en Telegram un informe como este:

📊 INFORME SEMANAL
2026-06-29 → 2026-07-05
📅 RESUMEN DÍA A DÍA
🔵 Lunes (2026-06-29)
💤 Sueño: 7.2h  |  🧠 Profundo: 62min  |  🌀 REM: 48min
🚶 Pasos: 9.240  |  🔥 Kcal: 420
💪 Entreno: Fuerza — 65min
❤️ FC reposo: 52 bpm  |  🩸 SpO2: 97.5%
...




---

*Proyecto desarrollado como parte del portfolio para una transición a Data Engineering.*
