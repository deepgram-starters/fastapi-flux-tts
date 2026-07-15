"""
FastAPI Flux TTS Starter - Backend Server

Bridges a browser WebSocket to Deepgram's Flux streaming text-to-speech
(v2 speak) using the official `deepgram-sdk` async `AsyncDeepgramClient` and its
`speak.v2` API.

Unlike the Flux transcription starter (fastapi-flux), which is a raw `websockets`
proxy, the Deepgram side here goes through the SDK.

Flow:
  browser --(JSON: Speak/Flush/Close)--> backend --(SDK speak.v2)--> Deepgram Flux TTS
  browser <--(binary audio + JSON control)-- backend <--(SDK speak.v2)-- Deepgram Flux TTS

Routes:
- GET /api/session  - JWT session token
- GET /api/metadata - Metadata from deepgram.toml
- WS  /api/tts      - Streaming TTS bridge (auth required)
"""

import os
import json
import secrets
import time
import asyncio

import jwt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import toml

from deepgram import AsyncDeepgramClient
from deepgram.environment import DeepgramClientEnvironment
from deepgram.speak.v2.types import SpeakV2Speak

load_dotenv(override=False)

CONFIG = {
    "port": int(os.environ.get("PORT", 8081)),
    "host": os.environ.get("HOST", "0.0.0.0"),
}

DEFAULT_MODEL = os.environ.get("DEEPGRAM_TTS_MODEL", "flux-alexis-en")
DEFAULT_ENCODING = "linear16"
DEFAULT_SAMPLE_RATE = "24000"


def load_api_key():
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY required")
    return api_key


API_KEY = load_api_key()

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)
JWT_EXPIRY = 3600  # 1 hour

# One async SDK client, reused across connections; the browser never sees the API key.
# DEEPGRAM_BASE_URL (e.g. wss://api.staging.deepgram.com) overrides the default
# production endpoint. speak.v2 uses environment.production for the /v2/speak ws.
def _build_client():
    base_url = os.environ.get("DEEPGRAM_BASE_URL")
    if base_url:
        https = base_url.replace("wss://", "https://").replace("ws://", "http://")
        env = DeepgramClientEnvironment(
            base=https, production=base_url, agent=base_url, agent_rest=https
        )
        print(f"Using custom Deepgram base URL: {base_url}")
        return AsyncDeepgramClient(api_key=API_KEY, environment=env)
    return AsyncDeepgramClient(api_key=API_KEY)


deepgram = _build_client()

app = FastAPI(title="Deepgram Flux TTS API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/session")
async def get_session():
    token = jwt.encode(
        {"iat": int(time.time()), "exp": int(time.time()) + JWT_EXPIRY},
        SESSION_SECRET,
        algorithm="HS256",
    )
    return JSONResponse(content={"token": token})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/metadata")
async def get_metadata():
    try:
        with open("deepgram.toml", "r") as f:
            config = toml.load(f)
        return JSONResponse(content=config.get("meta", {}))
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Metadata read failed"})


@app.websocket("/api/tts")
async def tts(websocket: WebSocket):
    """Streaming TTS bridge: browser <-> Deepgram Flux (v2 speak) via the async SDK."""
    # Validate JWT from the access_token.<jwt> subprotocol
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    valid_proto = None
    for proto in [p.strip() for p in protocols.split(",")]:
        if proto.startswith("access_token."):
            token = proto[len("access_token."):]
            try:
                jwt.decode(token, SESSION_SECRET, algorithms=["HS256"])
                valid_proto = proto
            except Exception:
                pass
            break

    if not valid_proto:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await websocket.accept(subprotocol=valid_proto)
    print("Client connected to /api/tts")

    model = websocket.query_params.get("model") or DEFAULT_MODEL
    encoding = websocket.query_params.get("encoding") or DEFAULT_ENCODING
    sample_rate = websocket.query_params.get("sample_rate") or DEFAULT_SAMPLE_RATE
    print(f"TTS config - model={model}, encoding={encoding}, sample_rate={sample_rate}")

    try:
        async with deepgram.speak.v2.connect(
            model=model, encoding=encoding, sample_rate=sample_rate
        ) as connection:

            async def forward_from_deepgram():
                try:
                    async for message in connection:
                        if isinstance(message, (bytes, bytearray)):
                            await websocket.send_bytes(bytes(message))
                        elif hasattr(message, "model_dump_json"):
                            await websocket.send_text(message.model_dump_json())
                        else:
                            await websocket.send_text(
                                json.dumps({"type": getattr(message, "type", "Unknown")})
                            )
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"Error forwarding from Deepgram: {e}")

            forward_task = asyncio.create_task(forward_from_deepgram())

            try:
                while True:
                    message = await websocket.receive()
                    if message.get("type") == "websocket.disconnect":
                        break
                    text = message.get("text")
                    if text is None:
                        continue  # browser sends JSON control only
                    try:
                        data = json.loads(text)
                    except (ValueError, TypeError):
                        print("Ignoring non-JSON message from client")
                        continue

                    msg_type = data.get("type")
                    if msg_type == "Speak":
                        await connection.send_speak(SpeakV2Speak(text=data.get("text", "")))
                    elif msg_type == "Flush":
                        await connection.send_flush()
                    elif msg_type == "Close":
                        await connection.send_close()
                    else:
                        print(f"Ignoring unknown client message type: {msg_type}")
            except WebSocketDisconnect:
                print("Client disconnected")
            finally:
                forward_task.cancel()
                try:
                    await forward_task
                except asyncio.CancelledError:
                    pass
    except Exception as e:
        print(f"TTS connection error: {e}")
    finally:
        print("Connection cleanup complete")


if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 70)
    print(f"FastAPI Flux TTS Server: http://localhost:{CONFIG['port']}")
    print("")
    print("   GET  /api/session")
    print("   WS   /api/tts (auth required)")
    print("   GET  /api/metadata")
    print("   GET  /health")
    print("=" * 70 + "\n")
    uvicorn.run(app, host=CONFIG["host"], port=CONFIG["port"])
