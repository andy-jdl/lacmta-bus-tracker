from fastapi import FastAPI, Form
from fastapi.responses import Response
import httpx
from dataclasses import dataclass
from datetime import datetime, timedelta
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from typing import List, Optional
from pydantic import BaseModel
import os

SWIFTLY_API = os.environ["SWIFTLY_API"]

app = FastAPI()

@dataclass(order=True)
class UserPriority:
    phone_number: str
    counter: int
    last_updated: datetime

q = {}

def is_user_limited(phn: str) -> bool:
    now = datetime.now()
    user = q.get(phn)
    if user is None:
        return False
    
    return (now - user.last_updated < timedelta(minutes=1) and user.counter >= 5)

def add_queue(phn: str):
    now = datetime.now()

    if phn not in q:
        q[phn] = UserPriority(phone_number=phn, counter=1, last_updated=now)
        return
    
    user = q[phn]
    if now - user.last_updated >= timedelta(minutes=1):
        user.counter = 1
    else:
        user.counter += 1
    
    user.last_updated = now

@app.get("/")
def read_root():
    return {"Hello": "world"}

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

class SMSResponse(BaseModel):
    status_code: int
    message: str

class Predictions(BaseModel):
    time: datetime
    sec: int

    @property
    def minutes_remaining(self) -> float:
        return self.sec / 60

    @property
    def is_due(self) -> bool:
        return self.sec <= 0

class Destinations(BaseModel):
    directionId: str  # 0 - W
    headsign: str
    predictions: Optional[List[Predictions]] = None

class RoutePrediction(BaseModel):
    routeShortName: str
    stopName: str
    destinations: List[Destinations]

class PredictionsData(BaseModel):
    predictionsData: List[RoutePrediction]

class BusPredictionResponse(BaseModel):
    data: PredictionsData

def validate_destination_response(routePredictions: List[RoutePrediction]) -> SMSResponse:
    if not routePredictions:
        return SMSResponse(status_code=200, message="No arrival data available")

    lines = []
    for route in routePredictions:
        for dest in route.destinations:
            if not dest.predictions:
                lines.append(f"{route.routeShortName} {dest.headsign}: no predictions available")
                continue
            for pred in dest.predictions:
                label = "Due" if pred.is_due else f"{pred.minutes_remaining:.0f} min"
                lines.append(f"{route.routeShortName} {dest.headsign}: {label}")

    return SMSResponse(status_code=200, message="\n".join(lines))

# also handle those empty responses (i.e. no bus routes)
async def get_arrivals(stopId: str):
    stop = int(stopId)
    api_url = f"https://api.goswift.ly/real-time/lametro/predictions?stop={stop}&number=2"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(api_url, headers={
                "Accept": "application/json",
                "Authorization": "${{ SWIFTLY_API }}"
            })
            response.raise_for_status()
            return BusPredictionResponse.model_validate(response.json())
            # form PredictionResponse here
    except httpx.HTTPStatusError as e:
        print(f"bad status code: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        print(f"connection error or timeout: {e}")
    except Exception as e:
        print(f"unexpected error: {type(e).__name__}: {e}")

@app.post("/sms")
async def sms(Body: str = Form(...), From: str = Form(...)):
    phone_number = From.strip()
    if is_user_limited(phone_number):
        return {"error": "RateLimitExceeded", "message": "Try again in one minute"}

    add_queue(phone_number)
    parts = Body.strip().upper().split()

    if len(parts) < 2:
        return SMSResponse(status_code=400, message="Keyword or stop ID missing")

    keyword, stop_id = parts[0], parts[1]
    if keyword != "LACMTA" or not stop_id.isnumeric():
        return SMSResponse(status_code=400, message="Invalid keyword or stop ID")

    reply = await get_arrivals(stop_id)
    if reply is None or reply.data is None:
        return SMSResponse(status_code=502, message="Unable to fetch arrival data")

    return validate_destination_response(reply.data.predictionsData)