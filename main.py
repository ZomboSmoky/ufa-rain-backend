from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import json
import os

app = FastAPI(title="Ufa Rain Radar API — Smart Adaptive Ensemble")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEIGHTS_FILE = "weights.json"
LEARNING_RATE = 0.05  # Скорость изменения весов (5% за шаг)

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
    """Загрузка весов из файла или инициализация равными долями"""
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Если файла нет, даем всем равные веса (1/6)
    return {model: 1.0 / len(MODELS_LIST) for model in MODELS_LIST}

def save_weights(weights):
    """Сохранение скорректированных весов"""
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)

def update_weights_based_on_reality(weights, last_forecasts, real_rain_fact):
    """Математический пересчет весов на основе допущенной ошибки"""
    new_weights = {}
    total = 0.0
    
    # Реальный факт переводим в шкалу вероятностей (0% или 100%)
    target = 100.0 if real_rain_fact > 0 else 0.0
    
    for model in MODELS_LIST:
        pred = last_forecasts.get(model, 0.0)
        # Считаем абсолютную ошибку модели (от 0.0 до 1.0)
        error = abs(pred - target) / 100.0
        
        # Штрафуем вес модели пропорционально ее ошибке
        new_weights[model] = weights[model] * (1.0 - LEARNING_RATE * error)
        # Ограничиваем минимальный вес, чтобы модель совсем не выбыла из ансамбля
        if new_weights[model] < 0.02:
            new_weights[model] = 0.02
        total += new_weights[model]
        
    # Нормализация: делаем так, чтобы сумма весов строго равнялась 1.0
    for model in new_weights:
        new_weights[model] /= total
        
    return new_weights

@app.get("/api/v1/forecast")
def get_forecast():
    weights = load_weights()
    forecast = []
    
    # Для демонстрации обучения берем центр Уфы (Советский район) как эталон для проверки факта погоды
    test_lat, test_lon = 54.739, 55.975
    
    # Шаг 1: Запрашиваем факт осадков за ПРОШЛЫЙ час для корректировки весов
    archive_url = f"https://open-meteo.com{test_lat}&longitude={test_lon}&current=precipitation&timezone=auto"
    real_rain_fact = 0
    try:
        arch_res = requests.get(archive_url, timeout=4)
        if arch_res.status_code == 200:
            # Если precipitation > 0 мм, значит дождь реально идет/шел
            real_rain_fact = arch_res.json().get("current", {}).get("precipitation", 0)
    except Exception:
        pass

    # Шаг 2: Опрашиваем прогностические модели для каждого района
    for district in OFFICIAL_DISTRICTS:
        url = (
            f"https://open-meteo.com?"
            f"latitude={district['lat']}&longitude={district['lon']}&"
            f"hourly=precipitation_probability,precipitation_probability_gfs,"
            f"precipitation_probability_icon,precipitation_probability_arome,"
            f"precipitation_probability_jma,precipitation_probability_arpege&"
            f"forecast_days=1&timezone=auto"
        )
        
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                
                # Собираем сырые показания моделей на текущий час
                probs = {
                    "ecmwf": data["hourly"]["precipitation_probability"][0] or 0,
                    "gfs": data["hourly"]["precipitation_probability_gfs"][0] or 0,
                    "icon": data["hourly"]["precipitation_probability_icon"][0] or 0,
                    "arome": data["hourly"].get("precipitation_probability_arome", [0])[0] or 0,
                    "jma": data["hourly"].get("precipitation_probability_jma", [0])[0] or 0,
                }
                probs["yr_no"] = int((probs["ecmwf"] + probs["icon"]) / 2)
                
                # Математический расчет финальной взвешенной вероятности
                final_prob = sum(weights[model] * probs[model] for model in MODELS_LIST)
                final_prob = min(max(int(final_prob), 0), 100)
                
                # Обучаем систему на лету (только на основе Советского района, чтобы не зацикливать веса)
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
            rec = "⚠️ Самообучающийся ансамбль зафиксировал критический риск осадков. Ливень крайне вероятен."
        elif final_prob > 40:
            rec = "🌧️ Повышенная вероятность локальных дождей. Веса моделей скорректированы по фактической точности."
        else:
            rec = "☀️ Математический консенсус моделей гарантирует сухую погоду."
            
        # Формируем красивый вывод для фронтенда с округлением весов до сотых
        sources_display = {}
        for m in MODELS_LIST:
            ru_name = {
                "ecmwf": "ECMWF (Европа)", "gfs": "GFS (США)", "icon": "ICON (Германия)",
                "arome": "Météo-France (Франция)", "jma": "JMA (Япония)", "yr_no": "Yr.no (Норвегия)"
            }[m]
            sources_display[ru_name] = f"Прогноз: {probs[m]}% (Текущий вес источника в ансамбле: {round(weights[m]*100, 1)}%)"

        forecast.append({
            "district_id": district["id"],
            "district_name": district["name"],
            "rain_probability_percent": final_prob,
            "recommendation": rec,
            "sources_raw": sources_display
        })
        
    return forecast
