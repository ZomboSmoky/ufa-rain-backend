import os
import random
from typing import Dict, List
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Ufa Rain Radar API")

# ТЕСТОВЫЙ ПУТЬ: Если сервер работает, по чистой ссылке (без хвостиков) он выдаст этот текст
@app.get("/")
async def root():
    return {"status": "working", "message": "Сервер Уфы запущен и отвечает!"}

DISTRICTS = {
    "chernikovka": {"name": "Черниковка", "modifier": 1.05},
    "sipalovo": {"name": "Сипайлово", "modifier": 1.10},
    "center": {"name": "Центр / Зеленая Роща", "modifier": 1.00},
    "dema": {"name": "Дёма", "modifier": 0.95},
    "zaton": {"name": "Затон", "modifier": 1.00}
}

class ForecastResponse(BaseModel):
    district_id: str
    district_name: str
    rain_probability_percent: float
    recommendation: str
    sources_raw: Dict[str, float]

@app.get("/api/v1/forecast", response_model=List[ForecastResponse])
async def get_rain_forecast():
    results = []
    for d_id, d_info in DISTRICTS.items():
        p_yandex = random.uniform(0.1, 0.9)  
        p_accu = random.uniform(0.1, 0.9)
        p_apple = random.uniform(0.1, 0.9)
        
        p_final = (0.5 * p_yandex + 0.3 * p_accu + 0.2 * p_apple) * d_info["modifier"]
        p_final = min(max(p_final, 0.0), 1.0)
        prob = round(p_final * 100, 1)
        
        if prob > 70:
            rec = "Ливень практически неизбежен. Возьмите зонт."
        elif prob > 40:
            rec = "Возможен локальный дождь. Проверьте радар."
        else:
            rec = "Прогноз благоприятный, существенных осадков не ожидается."
            
        results.append(ForecastResponse(
            district_id=d_id,
            district_name=d_info["name"],
            rain_probability_percent=prob,
            recommendation=rec,
            sources_raw={"yandex": round(p_yandex, 2), "accuweather": round(p_accu, 2), "apple_weather": round(p_apple, 2)}
        ))
    return results

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
