from fastapi import FastAPI, Form
from fastapi.responses import Response
import httpx
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timedelta
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

# Note to self, when sending an API, Content Type headers is usually for POST/PUT

# TODO API Key
# store your API key securly

app = FastAPI()

# TODO Build validator
# Also, free tier of ngrok has dynamic IP address.
# Make sure you change the URL in your dashboard when starting your server again [x]
# You need to register A2Auth for your phone number to send messages. Let's wait until you get API access [x]

@app.post("/hook")
async def chat(From: str = Form(...), Body: str = Form(...)):
    response = MessagingResponse()
    # msg = response.message(f"Hi {From}, you said: {Body}")
    return Response(content=str(response), media_type="application/xml")

@dataclass(order=True)
class UserPriority:
    phone_number: str
    counter: int
    last_updated: datetime

# For Development purposes

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
# For Development purposes


# TODO [x] Twillio setup, [x] Metro API setup

# Twilio webhook

@app.get("/")
def read_root():
    return {"Hello": "world"}

@app.post("/sms")
async def sms(Body: str = Form(...), From: str = Form(...)):
    phone_number = From.strip()
    if is_user_limited(phone_number):
        return {"RateLimitExceeded": "Try again in one minute"}
    else:
        add_queue(phone_number)


    parts = Body.strip().upper().split()

    if len(parts) < 2:
        print("Keyword or stopId missing")
    else:
        keyword, stopId = parts[0], parts[1]
        if keyword != 'LACMTA' or not stopId.isnumeric():
            print("Keyword or stopId missing")
    
    try:
        reply = await get_arrivals(stopId)
        if reply == "good":
            print("You're good to go")
    except:
        print("An error occured")

    return {"keyword": keyword, "stopId": stopId}

# also handle those empty responses (i.e. no bus routes)
async def get_arrivals(stopId: str):
    stop = int(stopId)
    api_url = f"https://api.goswift.ly/real-time/lametro/predictions?stop={stop}&number=2"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(api_url, headers={
                "Accept": "application/json",
                "Authorization": "authorization_key"
            })
            response.raise_for_status()
            print(response.status_code)
            data = response.json()
            print(data)
            # form PredictionResponse here
            return "good"
    except httpx.HTTPStatusError as e:
        print("bad status code")
    except httpx.RequestError as e:
        print("handled connection errors or timeouts etc.")
    except Exception as e:
        print("an unexpectted error")