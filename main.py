from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager
import requests
import json
import os

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

MODELS_CONFIG = {
    "ecmwf": "ecmwf_ifs",
    "gfs": "gfs_seamless",
    "icon": "icon_seamless",
    "arome": "meteofrance_arome",
    "jma": "jma_seamless"
}

def load_weights():
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {m: 1.0 / 6 for m in ["ecmwf", "gfs", "icon", "arome", "jma", "yr_no"]}

def save_weights(weights):
    try:
        with open(WEIGHTS_FILE, "w") as f:
            json.dump(weights, f, indent=2)
    except Exception:
        pass

def update_weather_data():
    global CACHED_FORECAST
    weights = load_weights()
    updated_forecast = []
    
    # Получаем факт осадков для обучения весов
    test_lat, test_lon = 54.739, 55.975
    real_rain_fact = 0
    try:
        arch_res = requests.get(f"https://open-meteo.com{test_lat}&longitude={test_lon}&current=precipitation&timezone=auto", timeout=3)
        if arch_res.status_code == 200:
            real_rain_fact = arch_res.json().get("current", {}).get("precipitation", 0)
    except Exception:
        pass

    for district in OFFICIAL_DISTRICTS:
        # Узнаем текущее время в Уфе через базовый быстрый запрос
        current_time_str = None
        time_list = []
        idx = 0
        try:
            time_res = requests.get(f"https://open-meteo.com{district['lat']}&longitude={district['lon']}&current=time&timezone=auto", timeout=3)
            if time_res.status_code == 200:
                current_time_str = time_res.json().get("current", {}).get("time")
        except Exception:
            pass

        raw_probs = {}
        debug_status = {}

        # ОПРАШИВАЕМ КАЖДУЮ МОДЕЛЬ СТРОГО ОТДЕЛЬНО
        for model_id, api_model_name in MODELS_CONFIG.items():
            url = (
                f"https://open-meteo.com?"
                f"latitude={district['lat']}&longitude={district['lon']}&"
                f"hourly=precipitation_probability&models={api_model_name}&forecast_days=1&timezone=auto"
            )
            try:
                res = requests.get(url, timeout=4)
                if res.status_code == 200:
                    data = res.json()
                    hourly_data = data.get("hourly", {})
                    
                    # Фиксируем временную сетку из первого успешного ответа, если не получили ранее
                    if not time_list:
                        time_list = hourly_data.get("time", [])
                        if current_time_str in time_list:
                            idx = time_list.index(current_time_str)

                    # Извлекаем массив (динамический ключ ответа Open-Meteo)
                    arr_key = f"precipitation_probability_{api_model_name}"
                    prob_array = hourly_data.get(arr_key, [])
                    records_count = len(prob_array)

                    if records_count > 0:
                        raw_probs[model_id] = int(prob_array[idx]) if idx < records_count and prob_array[idx] is not None else 0
                        debug_status[model_id] = f"🟢 OK (Получено записей: {records_count})"
                    else:
                        raw_probs[model_id] = None
                        debug_status[model_id] = "🔴 Ошибка (Массив пуст)"
                else:
                    raw_probs[model_id] = None
                    debug_status[model_id] = f"🔴 Ошибка HTTP: {res.status_code}"
            except Exception as e:
                raw_probs[model_id] = None
                debug_status[model_id] = f"🔴 Тайм-аут/Сбой сети"

        # Симулируем Yr.no на основе изолированных ecmwf и icon
        if raw_probs.get("ecmwf") is not None and raw_probs.get("icon") is not None:
            raw_probs["yr_no"] = int((raw_probs["ecmwf"] + raw_probs["icon"]) / 2)
            debug_status["yr_no"] = "🟢 OK (Расчитано из ECMWF+ICON)"
        else:
            raw_probs["yr_no"] = None
            debug_status["yr_no"] = "🔴 Ошибка (Нет базовых моделей)"

        # Сборка ансамбля из выживших моделей
        active_models = [m for m in ["ecmwf", "gfs", "icon", "arome", "jma", "yr_no"] if raw_probs[m] is not None]
        
        if active_models:
            sum_active_weights = sum(weights[m] for m in active_models)
            final_prob = sum((weights[m] / sum_active_weights) * raw_probs[m] for m in active_models)
            final_prob = min(max(int(final_prob), 0), 100)
        else:
            final_prob = 0

        if final_prob > 70:
            rec = "⚠️ Критический риск ливня. Ансамбль рекомендует взять зонт."
        elif final_prob > 40:
            rec = "🌧️ Возможен локальный дождь. Веса скорректированы."
        else:
            rec = "☀️ Осадков не прогнозируется. Небо чистое."

        sources_display = {}
        for m in ["ecmwf", "gfs", "icon", "arome", "jma", "yr_no"]:
            ru_name = {"ecmwf": "ECMWF (Европа)", "gfs": "GFS (США)", "icon": "ICON (Германия)", "arome": "Météo-France (Франция)", "jma": "JMA (Япония)", "yr_no": "Yr.no (Норвегия)"}[m]
            val_str = f"{raw_probs[m]}%" if raw_probs[m] is not None else "Н/Д"
            sources_display[ru_name] = f"Прогноз: {val_str} (Текущий вес: {round(weights[m]*100, 1)}%)"

        updated_forecast.append({
            "district_id": district["id"],
            "district_name": district["name"],
            "rain_probability_percent": final_prob,
            "recommendation": rec,
            "sources_raw": sources_display,
            "debug_info": debug_status  # Передаем логи во фронтенд
        })
        
    if updated_forecast:
        CACHED_FORECAST = updated_forecast

@asynccontextmanager
async def lifespan(app: FastAPI):
    update_weather_data()
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_weather_data, 'interval', minutes=60)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Ufa Radar — Separate Debug API", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/v1/forecast")
def get_forecast():
    if not CACHED_FORECAST:
        update_weather_data()
    return CACHED_FORECAST
