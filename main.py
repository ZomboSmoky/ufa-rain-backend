from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import random

app = FastAPI(title="Ufa Rain Radar API — Official 7 Districts")

# Настройка CORS, чтобы ваш фронтенд Streamlit мог забирать данные
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Официальный список 7 административных районов Уфы
OFFICIAL_DISTRICTS = [
    {"id": "demskiy", "name": "Дёмский район"},
    {"id": "kalininskiy", "name": "Калининский район"},
    {"id": "kirovskiy", "name": "Кировский район"},
    {"id": "leninskiy", "name": "Ленинский район"},
    {"id": "oktyabrskiy", "name": "Октябрьский район"},
    {"id": "ordzhonikidzevskiy", "name": "Орджоникидзевский район"},
    {"id": "sovetskiy", "name": "Советский район"}
]

@app.get("/api/v1/forecast")
def get_forecast():
    forecast = []
    
    for district in OFFICIAL_DISTRICTS:
        # Генерируем случайную вероятность для демонстрации (замените на вашу метео-логику)
        prob = random.randint(10, 95)
        
        if prob > 70:
            rec = "⚠️ Внимание! Ожидается сильный ливень. Рекомендуем взять зонт и воздержаться от поездок на личном авто."
        elif prob > 40:
            rec = "🌧️ Возможен небольшой или кратковременный дождь. Зонт лишним не будет."
        else:
            rec = "☀️ Облачно с прояснениями, осадков не ожидается. Отличное время для прогулки!"
            
        forecast.append({
            "district_id": district["id"],
            "district_name": district["name"],
            "rain_probability_percent": prob,
            "recommendation": rec,
            "sources_raw": {
                "gfs_model_probability": f"{prob + random.randint(-5, 5)}%",
                "ecmwf_model_probability": f"{prob + random.randint(-5, 5)}%",
                "icon_model_probability": f"{prob}%",
                "satellite_ir_index": round(random.uniform(0.1, 0.9), 2)
            }
        })
        
    return forecast
