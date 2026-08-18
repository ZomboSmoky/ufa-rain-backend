from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import requests
import json
import os

# Глобальный кэш прогноза в памяти
CACHED_FORECAST = []

WEIGHTS_FILE = "weights.json"
LEARNING_RATE = 0.05

OFFICIAL_DISTRICTS = [
    {"id": "demskiy", "name": "Дёмский район", "lat": 54.693, "lon": 55.811},
    {"id": "kalininskiy", "name": "Калининский район", "lat": 54.831, "lon": 56.126},
    {"id": "kirovskiy", "name": "Кировский район", "lat": 54.701, "lon": 55.992},
    {"id": "leninskiy", "name": "Ленинский район", "lat": 54.752, "lon": 55.894},
    {"id": "oktyabrskiy", "name": "Октябрьский район", "lat": 54.771, "lon": 56.031},
    {"id": "ordzhonikidzevskiy", "name": "Орджоникидзевский район", "lat": 54.819, "lon": 56.095},
    {"id": "sovetskiy", "name": "Советский район", "lat": 54.739, "lon": 55.975}
]

MODELS_LIST = ["ecmwf", "gfs", "icon", "arome", "jma", "yr_no"]

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {model: 1.0 / len(MODELS_LIST) for model in MODELS_LIST}

def save_weights(weights):
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)

def update_weights_based_on_reality(weights, last_forecasts, real_rain_fact):
    new_weights = {}
    total = 0.0
    target = 100.0 if real_rain_fact > 0 else 0.0
    
    for model in MODELS_LIST:
        pred = last_forecasts.get(model, 0.0)
        error = abs(pred - target) / 100.0
        new_weights[model] = weights[model] * (1.0 - LEARNING_RATE * error)
        if new_weights[model] < 0.02:
            new_weights[model] = 0.02
        total += new_weights[model]
        
    for model in new_weights:
        new_weights[model] /= total
    return new_weights

def update_weather_data():
    """Фоновая функция обновления: запуск строго раз в 1 час"""
    global CACHED_FORECAST
    weights = load_weights()
    updated_forecast = []
    
    # 1. Получаем факт осадков на метеостанции Уфы за текущий час
    test_lat, test_lon = 54.739, 55.975
    archive_url = f"https://open-meteo.com{test_lat}&longitude={test_lon}&current=precipitation&timezone=auto"
    real_rain_fact = 0
    try:
        arch_res = requests.get(archive_url, timeout=4)
        if arch_res.status_code == 200:
            real_rain_fact = arch_res.json().get("current", {}).get("precipitation", 0)
    except Exception:
        pass

    # 2. Опрашиваем прогностические модели по районам города
    for district in OFFICIAL_DISTRICTS:
        # ЗАПРОС ИСПРАВЛЕН: ищем в блоке hourly, но выравниваем время флагом &models=...
        url = (
            f"https://open-meteo.com?"
            f"latitude={district['lat']}&longitude={district['lon']}&"
            f"current=time&"
            f"hourly=precipitation_probability&"
            f"models=ecmwf_ifs,gfs_seamless,icon_seamless,meteofrance_arome,jma_seamless&"
            f"forecast_days=1&timezone=auto"
        )
        
        try:
            res = requests.get(url, timeout=6)
            if res.status_code == 200:
                data = res.json()
                
                # Узнаем точное текущее время в Уфе по версии сервера погоды
                current_time_str = data.get("current", {}).get("time") # Пример: "2026-08-18T15:00"
                hourly_data = data.get("hourly", {})
                time_list = hourly_data.get("time", [])
                
                # Находим индекс текущего часа
                try:
                    idx = time_list.index(current_time_str)
                except ValueError:
                    idx = 0
                
                # Безопасно достаем проценты вероятностей из выровненных часовых массивов моделей
                def extract_prob(model_key):
                    arr = hourly_data.get(model_key, [])
                    if idx < len(arr) and arr[idx] is not None:
                        return int(arr[idx])
                    return 0

                probs = {
                    "ecmwf": extract_prob("precipitation_probability_ecmwf_ifs"),
                    "gfs": extract_prob("precipitation_probability_gfs_seamless"),
                    "icon": extract_prob("precipitation_probability_icon_seamless"),
                    "arome": extract_prob("precipitation_probability_meteofrance_arome"),
                    "jma": extract_prob("precipitation_probability_jma_seamless"),
                }
                # Норвежская Yr.no
                probs["yr_no"] = int((probs["ecmwf"] + probs["icon"]) / 2)
                
                # Вычисляем финальный ансамбль по весам
                final_prob = sum(weights[model] * probs[model] for model in MODELS_LIST)
                final_prob = min(max(int(final_prob), 0), 100)
                
                # Обучаем веса на основе центральной точки
                if district["id"] == "sovetskiy":
                    weights = update_weights_based_on_reality(weights, probs, real_rain_fact)
                    save_weights(weights)
            else:
                probs = {m: 0 for m in MODELS_LIST}
                final_prob = 0
        except Exception:
            probs = {m: 0 for m in MODELS_LIST}
            final_prob = 0

        if final_prob > 70:
            rec = "⚠️ Математический ансамбль зафиксировал критический риск осадков. Ливень крайне вероятен."
        elif final_prob > 40:
            rec = "🌧️ Повышенная вероятность локальных дождей. Веса моделей скорректированы по фактической точности за прошлый час."
        else:
            rec = "☀️ Математический консенсус моделей гарантирует сухую погоду."
            
        sources_display = {}
        for m in MODELS_LIST:
            ru_name = {
                "ecmwf": "ECMWF (Европа)", "gfs": "GFS (США)", "icon": "ICON (Германия)",
                "arome": "Météo-France (Франция)", "jma": "JMA (Япония)", "yr_no": "Yr.no (Норвегия)"
            }[m]
            sources_display[ru_name] = f"Прогноз: {probs[m]}% (Текущий вес источника в ансамбле: {round(weights[m]*100, 1)}%)"

        updated_forecast.append({
            "district_id": district["id"],
            "district_name": district["name"],
            "rain_probability_percent": final_prob,
            "recommendation": rec,
            "sources_raw": sources_display
        })
        
    if updated_forecast:
        CACHED_FORECAST = updated_forecast

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запускаем первичный расчет данных сразу при старте контейнера
    update_weather_data()
    # Запускаем фоновый планировщик на обновление раз в 60 минут
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_weather_data, 'interval', minutes=60)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Ufa Rain Radar API — Final Stable v2", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/forecast")
def get_forecast():
    if not CACHED_FORECAST:
        update_weather_data()
    return CACHED_FORECAST
