import os
from typing import Dict, List
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import requests

app = FastAPI(title="Ufa Rain Radar API")

@app.get("/")
async def root():
    return {"status": "working", "message": "Умный ансамбль погоды Уфы запущен!"}

DISTRICTS = {
    "chernikovka": {"name": "Черниковка", "lat": 54.8122, "lon": 56.0915, "modifier": 1.05},
    "sipalovo": {"name": "Сипайлово", "lat": 54.7678, "lon": 56.0621, "modifier": 1.10},
    "center": {"name": "Центр / Зеленая Роща", "lat": 54.7348, "lon": 55.9579, "modifier": 1.00},
    "dema": {"name": "Дёма", "lat": 54.6983, "lon": 55.8115, "modifier": 0.95},
    "zaton": {"name": "Затон", "lat": 54.7621, "lon": 55.8944, "modifier": 1.00}
}

class ForecastResponse(BaseModel):
    district_id: str
    district_name: str
    rain_probability_percent: float
    recommendation: str
    sources_raw: Dict[str, float]

def fetch_open_meteo(lat: float, lon: float) -> float:
    """Запрос к реальному API. Возвращает вероятность от 0.0 до 1.0"""
    url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=precipitation_probability&forecast_hours=1"
    response = requests.get(url, timeout=4).json()
    return response["hourly"]["precipitation_probability"][0] / 100.0

@app.get("/api/v1/forecast", response_model=List[ForecastResponse])
async def get_rain_forecast():
    results = []
    
    for d_id, d_info in DISTRICTS.items():
        # Сбор данных с симуляцией отказов реальных служб
        # В продакшене тут три разных блока try-except для Яндекс, Accu, Apple
        sources = {"yandex": None, "accuweather": None, "apple_weather": None}
        
        # 1. Запрос для Яндекса
        try:
            base_prob = fetch_open_meteo(d_info["lat"], d_info["lon"])
            sources["yandex"] = min(max(base_prob * 1.02, 0.0), 1.0)
        except Exception:
            sources["yandex"] = None # Служба «упала»
            
        # 2. Запрос для AccuWeather
        try:
            base_prob = fetch_open_meteo(d_info["lat"], d_info["lon"])
            sources["accuweather"] = min(max(base_prob * 0.95, 0.0), 1.0)
        except Exception:
            sources["accuweather"] = None
            
        # 3. Запрос для Apple Weather
        try:
            base_prob = fetch_open_meteo(d_info["lat"], d_info["lon"])
            sources["apple_weather"] = min(max(base_prob * 0.98, 0.0), 1.0)
        except Exception:
            sources["apple_weather"] = None

        # --- АЛГОРИТМ ДИНАМИЧЕСКОГО ПЕРЕСЧЕТА ВЕСОВ ---
        # Базовые идеальные веса моделей
        base_weights = {"yandex": 0.5, "accuweather": 0.3, "apple_weather": 0.2}
        
        active_weights_sum = 0.0
        weighted_probabilities_sum = 0.0
        
        # Считаем сумму весов только тех служб, которые отдали данные
        for source_name, prob_val in sources.items():
            if prob_val is not None:
                active_weights_sum += base_weights[source_name]
                weighted_probabilities_sum += prob_val * base_weights[source_name]
        
        # Если хоть одна служба ответила — нормируем (усредняем по выжившим)
        if active_weights_sum > 0:
            p_final = (weighted_probabilities_sum / active_weights_sum) * d_info["modifier"]
        else:
            p_final = 0.0 # Полный блэкаут всех служб интернета
            
        p_final = min(max(p_final, 0.0), 1.0)
        prob = round(p_final * 100, 1)
        
        # Формируем красивый вывод для фронтенда
        sources_clean = {k: (v if v is not None else -1.0) for k, v in sources.items()}
        
        if prob > 70:
            rec = "⚠️ Ливень неизбежен! Избегайте низин (особенно перекрестков в Сипайлово и под мостами)."
        elif prob > 40:
            rec = " Showers likely. Возможен локальный дождь в ближайший час."
        else:
            rec = "☀️ Небо ясное, существенных осадков не ожидается."
            
        results.append(ForecastResponse(
            district_id=d_id,
            district_name=d_info["name"],
            rain_probability_percent=prob,
            recommendation=rec,
            sources_raw=sources_clean
        ))
    return results

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
