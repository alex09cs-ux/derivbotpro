# main.py - CÓDIGO COMPLETO PARA RENDER.COM
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
import asyncio
import os
from python_deriv_api import DerivAPI
from typing import List, Dict, Any
import json
import time

app = FastAPI(title="DerivBotPro")

# Configuración
DERIV_APP_ID = os.getenv("DERIV_APP_ID")  # ← Esto toma el valor de .env
REDIRECT_URI = "http://localhost:8000/auth/callback"

# Almacenamiento temporal (solo para desarrollo)
user_tokens = {}
running_bots = {}
digit_history = []  # Últimos 1000 dígitos
recent_digits = []  # Últimos 20 dígitos para mostrar

# --- CLASES DE BOTS ---
class DigitStatisticZeroBot:
    def __init__(self, stake=1.0, window_size=50):
        self.stake = stake
        self.window_size = window_size
        self.triggered = False

    async def analyze(self, digits: List[int]) -> Dict[str, Any] | None:
        if len(digits) < self.window_size:
            return None
        sample = digits[-self.window_size:]
        freq = [sample.count(i) for i in range(10)]
        zero_digits = [i for i in range(10) if freq[i] == 0]
        if zero_digits and not self.triggered:
            prediction = zero_digits[0]
            self.triggered = True
            return {
                "action": "buy",
                "contract_type": "digit_differs",
                "prediction": prediction,
                "amount": self.stake,
                "duration": 5,
                "symbol": "R_10",
                "reason": f"Digit {prediction} has 0% frequency in last {self.window_size} ticks",
                "strategy": "Digit Statistic 0%"
            }
        if self.triggered and len(digits) > 0 and digits[-1] == prediction:
            self.triggered = False
        return None

class TwinDigitBot:
    def __init__(self, stake=1.0):
        self.stake = stake

    async def analyze(self, digits: List[int]) -> Dict[str, Any] | None:
        if len(digits) < 2:
            return None
        if digits[-1] == digits[-2]:
            return {
                "action": "buy",
                "contract_type": "digit_differs",
                "prediction": digits[-1],
                "amount": self.stake,
                "duration": 5,
                "symbol": "R_10",
                "reason": f"Twin digit detected: {digits[-2]}{digits[-1]}",
                "strategy": "Twin Digit"
            }
        return None

class AABBCPatternBot:
    def __init__(self, stake=1.0):
        self.stake = stake

    async def analyze(self, digits: List[int]) -> Dict[str, Any] | None:
        if len(digits) < 5:
            return None
        seq = digits[-5:]
        if seq[0] == seq[1] and seq[2] == seq[3] and seq[0] != seq[2] and seq[3] != seq[4]:
            return {
                "action": "buy",
                "contract_type": "digit_differs",
                "prediction": seq[4],
                "amount": self.stake,
                "duration": 5,
                "symbol": "R_10",
                "reason": f"AABBC pattern: {seq}",
                "strategy": "AABBC Pattern"
            }
        return None

class HedgingOver5Under4Bot:
    def __init__(self, stake=1.0, window=10):
        self.stake = stake
        self.window = window

    async def analyze(self, digits: List[int]) -> Dict[str, Any] | None:
        if len(digits) < self.window:
            return None
        sample = digits[-self.window:]
        count_4 = sample.count(4)
        count_5 = sample.count(5)
        if count_4 == 0 and count_5 == 0:
            return {
                "action": "hedging",
                "contracts": [
                    {"type": "digit_over", "prediction": 5, "amount": self.stake, "duration": 5, "symbol": "R_10"},
                    {"type": "digit_under", "prediction": 4, "amount": self.stake, "duration": 5, "symbol": "R_10"}
                ],
                "reason": f"No 4 or 5 in last {self.window} ticks",
                "strategy": "Hedging Over 5 & Under 4"
            }
        return None

class DigitDiffersRandomBot:
    def __init__(self, stake=1.0):
        self.stake = stake

    async def analyze(self, digits: List[int]) -> Dict[str, Any] | None:
        import random
        pred = random.randint(0, 9)
        return {
            "action": "buy",
            "contract_type": "digit_differs",
            "prediction": pred,
            "amount": self.stake,
            "duration": 5,
            "symbol": "R_10",
            "reason": f"Random prediction: {pred}",
            "strategy": "Random Differs"
        }

# --- CLIENTE DERIV ---
class DerivClient:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.api = None
        self.connected = False

    async def connect(self):
        try:
            self.api = DerivAPI(app_id=DERIV_APP_ID, access_token=self.access_token)
            await self.api.authorize()
            self.connected = True
            print("✅ Conectado a Deriv")
            await self.api.subscribe({"ticks": "R_10"})
            await self.api.subscribe({"ticks": "Volatility 10 Index"})
            while self.connected:
                data = await self.api.receive()
                if "tick" in data:
                    price = data["tick"]["quote"]
                    last_digit = int(str(price).split('.')[-1][-1])
                    global digit_history, recent_digits
                    digit_history.append(last_digit)
                    recent_digits = digit_history[-20:]  # Solo los últimos 20
                    if len(digit_history) > 1000:
                        digit_history.pop(0)
        except Exception as e:
            print(f"❌ Error en Deriv: {e}")
            await asyncio.sleep(5)
            await self.connect()

# --- ENDPOINTS ---
@app.get("/")
def root():
    return {"message": "Bienvenido a DerivBotPro. Usa /auth para iniciar sesión."}

@app.get("/auth")
def auth():
    url = f"https://oauth.deriv.com/oauth2/authorize?client_id={DERIV_APP_ID}&redirect_uri={REDIRECT_URI}&response_type=token&scope=read trade"
    return RedirectResponse(url=url)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    query_params = dict(request.query_params)
    token = query_params.get("access_token")
    if not token:
        raise HTTPException(status_code=400, detail="Token no recibido")
    user_tokens[request.client.host] = token
    return RedirectResponse(url="http://localhost:3000/dashboard")

@app.get("/data")
def get_data():
    return {
        "last_digit": recent_digits[-1] if recent_digits else None,
        "digit_history": recent_digits,
        "balance": 0,
        "bots": [
            {"name": "Digit Statistic 0%", "strategy": "Detecta dígito que no aparece en X ticks", "market": "R_10", "icon": "📈"},
            {"name": "Twin Digit", "strategy": "Comprar DIFFERS cuando dos dígitos iguales seguidos", "market": "R_10", "icon": "🔁"},
            {"name": "AABBC Pattern", "strategy": "Patrón AABBC → comprar DIFFERS del último dígito", "market": "R_10", "icon": "🔢"},
            {"name": "Hedging Over 5 & Under 4", "strategy": "Hedging si no hay 4 ni 5 en últimos 10 ticks", "market": "R_10", "icon": "⚖️"},
            {"name": "Random Differs", "strategy": "Predicción aleatoria (prueba)", "market": "R_10", "icon": "🎲"}
        ]
    }

@app.post("/start-bot")
async def start_bot(request: Request):
    data = await request.json()
    token = data.get("token")
    bot_name = data.get("bot_name")

    if token not in user_tokens.values():
        raise HTTPException(status_code=401, detail="Token no autorizado")

    client = DerivClient(token)
    await client.connect()

    bot_map = {
        "Digit Statistic 0%": DigitStatisticZeroBot(stake=1.0, window_size=50),
        "Twin Digit": TwinDigitBot(stake=1.0),
        "AABBC Pattern": AABBCPatternBot(stake=1.0),
        "Hedging Over 5 & Under 4": HedgingOver5Under4Bot(stake=1.0),
        "Random Differs": DigitDiffersRandomBot(stake=1.0)
    }

    bot = bot_map.get(bot_name)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado")

    running_bots[token] = {"bot": bot, "client": client, "is_running": True}
    asyncio.create_task(run_bot_loop(token, bot, client))
    return {"status": f"Bot {bot_name} iniciado"}

async def run_bot_loop(token: str, bot, client: DerivClient):
    while running_bots[token].get("is_running", False):
        await asyncio.sleep(1)
        if len(digit_history) >= 2:
            result = await bot.analyze(digit_history)
            if result:
                print(f"🤖 Bot {result['strategy']} → {result['reason']}")
                # Aquí iría la lógica real de compra con buy_contract()
                # Por ahora solo simulamos
                pass

@app.post("/stop-bot")
async def stop_bot(request: Request):
    data = await request.json()
    token = data.get("token")
    if token in running_bots:
        running_bots[token]["is_running"] = False
        return {"status": "Bot detenido"}
    return {"status": "No hay bot activo"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)