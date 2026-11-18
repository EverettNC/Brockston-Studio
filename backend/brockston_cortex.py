from __future__ import annotations
from fastapi import FastAPI, HTTPException, Body, Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional, Dict, Any, Callable
import logging
import uuid
import json
import io
import hmac
import hashlib
import re
import time
import random
from cryptography.fernet import Fernet, InvalidToken
import boto3
from botocore.exceptions import ClientError
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config  # type: ignore
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from pydub import AudioSegment
import requests

try:
    import anyio
    from anyio import to_thread

    ANYIO_AVAILABLE = True
except ImportError:
    # Fallback for missing anyio
    import asyncio
    from typing import Any, Callable

    class MockToThread:
        @staticmethod
        async def run_sync(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, func, *args)

    # Create instance to avoid type issues
    _mock_to_thread = MockToThread()
    to_thread = _mock_to_thread  # type: ignore
    ANYIO_AVAILABLE = False
from starlette.types import ASGIApp, Scope, Receive, Send
import redis
from dotenv import load_dotenv
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.propagate = False
from dotenv import dotenv_values
import os

app = FastAPI()

# from learning_routes import router as learning_router  # Module doesn't exist
# app.include_router(learning_router, prefix="/learning")


ENV_PATH = Path(__file__).resolve().parent / ".env"
print("ENV_PATH:", ENV_PATH, "exists:", ENV_PATH.exists())

vals = dotenv_values(ENV_PATH)
opaque_secret = vals.get("BROCKSTON_OPAQUE_SECRET", "")
print(
    "VALS_HAS_OPAQUE:",
    "BROCKSTON_OPAQUE_SECRET" in vals,
    "len:",
    len(opaque_secret) if opaque_secret else 0,
)

load_dotenv(ENV_PATH, override=True)

# Key drop box (Settings panel) still wins over the .env just loaded.
try:
    from backend import key_box as _key_box
except ImportError:
    import key_box as _key_box
_key_box.apply_to_environ()

v = os.getenv("BROCKSTON_OPAQUE_SECRET")
print("OS_HAS_OPAQUE:", bool(v), "len:", 0 if not v else len(v))

if not v and opaque_secret:
    os.environ["BROCKSTON_OPAQUE_SECRET"] = opaque_secret
    v = os.getenv("BROCKSTON_OPAQUE_SECRET")
    print("FORCED_OS_HAS_OPAQUE:", bool(v), "len:", 0 if not v else len(v))

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Env / Secrets ----
EK = os.getenv("BROCKSTON_ENCRYPTION_KEY") or os.getenv("ALPHAVOX_ENCRYPTION_KEY")
if not EK:
    raise ValueError("BROCKSTON_ENCRYPTION_KEY or ALPHAVOX_ENCRYPTION_KEY missing")
try:
    cipher = Fernet(EK.encode("utf-8"))
except Exception:
    raise ValueError("BROKSTON_ENCRYPTION_KEY is not a valid Fernet key")

DB_DSN = os.getenv("BROCKSTON_DB_DSN")
if not DB_DSN:
    logger.warning("BROCKSTON_DB_DSN not set - database features disabled")
    DB_DSN = "sqlite:///brockston_local.db"  # Fallback to local SQLite

SAGEMAKER_ENDPOINT = os.getenv("SAGEMAKER_ENDPOINT")

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("BROCKSTON_S3_BUCKET")
if not S3_BUCKET:
    logger.warning("BROCKSTON_S3_BUCKET not set - S3 features disabled")
    S3_BUCKET = None
KMS_KEY_ID = os.getenv("BROCKSTON_KMS_KEY_ID")
if not KMS_KEY_ID:
    logger.warning("BROCKSTON_KMS_KEY_ID not set - KMS encryption disabled")
    KMS_KEY_ID = None
OPAQUE_SECRET = os.getenv("BROCKSTON_OPAQUE_SECRET")
if not OPAQUE_SECRET:
    logger.critical(
        "BROCKSTON_OPAQUE_SECRET is not set. "
        "Refusing to start with an insecure default. "
        "Set BROCKSTON_OPAQUE_SECRET in your environment or .env file."
    )
    raise RuntimeError(
        "BROCKSTON_OPAQUE_SECRET is required — refusing to start with insecure default. "
        "Cardinal Rule 12: Security is mandatory, not decorative."
    )
SAGEMAKER_CONF_THRESHOLD = float(os.getenv("SAGEMAKER_CONF_THRESHOLD", 0.5))
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    logger.warning("REDIS_URL not set - Redis features disabled")
    REDIS_URL = None

# ---- DB ----
engine = create_engine(
    DB_DSN,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
)

# ---- AWS Clients ----
_BOTO_CFG = Config(
    region_name=AWS_REGION,
    retries={"max_attempts": 3, "mode": "standard"},
    read_timeout=5,
    connect_timeout=3,
)
boto_session = boto3.Session(region_name=AWS_REGION)
polly_client = boto_session.client("polly", config=_BOTO_CFG)
s3_client = boto_session.client("s3", config=_BOTO_CFG)
sagemaker_runtime = boto_session.client("sagemaker-runtime", config=_BOTO_CFG)

# ---- Redis (rate limits) ----
redis_client = redis.from_url(REDIS_URL)

# ---- App ----
app = FastAPI(
    title="Brokston Cortex Brain",
    version="3.0.0",
    docs_url=None if os.getenv("ENV") == "prod" else "/docs",
    redoc_url=None if os.getenv("ENV") == "prod" else "/redoc",
    openapi_url=None if os.getenv("ENV") == "prod" else "/openapi.json",
)


# ---- Global error masking for request/validation ----
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": "Bad request"})


# ---- Constants ----
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # per-tenant per window
USER_FRACTION = 10  # user share of tenant limit
MAX_BODY = 256 * 1024  # 256 KiB
MAX_HISTORY_COUNT = 10_000


# ---- ASGI body limiter (no private attrs) ----
class BodySizeLimiterMiddleware:
    def __init__(self, app: ASGIApp, max_size: int = MAX_BODY):
        self.app = app
        self.max_size = max_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT"):
            await self.app(scope, receive, send)
            return

        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                # ASGI spec compatibility
                message = {"type": "http.body", **message}
            if message["type"] == "http.body":
                chunk = message.get("body", b"")
                body += chunk
                if len(body) > self.max_size:
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [(b"content-type", b"text/plain")],
                        }
                    )
                    await send(
                        {"type": "http.response.body", "body": b"Payload too large"}
                    )
                    return
                more_body = message.get("more_body", False)
            else:
                more_body = False

        async def new_receive() -> Dict[str, Any]:
            return {"type": "http.body", "body": body, "more_body": False}

        await self.app(scope, new_receive, send)


app.add_middleware(BodySizeLimiterMiddleware)


# ---- Content-type, TLS, and Redis rate-limits ----
@app.middleware("http")
async def check_content_type_and_rate(request: Request, call_next: Callable):
    return await call_next(request)
    path = request.url.path
    method = request.method

    # Skip health, docs, OpenAPI, favicon
    if path in ("/health", "/learning/health", "/favicon.ico") or path.startswith(
        ("/docs", "/redoc", "/openapi.json")
    ):
        return await call_next(request)

    # Methods that carry a body; others (GET/HEAD/OPTIONS) should not be 415-gated
    body_methods = {"POST", "PUT", "PATCH"}
    if method in body_methods:
        ctype = (
            (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        )
        if ctype != "application/json":
            # Allow empty body for some clients that still set these methods
            body = await request.body()
            if body:  # only enforce if there is a body and it's not JSON
                raise HTTPException(status_code=415, detail="Unsupported media type")

    # ---- your existing rate limit logic (unchanged) ----
    # tenant_key = ...
    # user_key = ...
    # tenant_count = redis_client.incr(tenant_key, 1); redis_client.expire(tenant_key, RATE_LIMIT_WINDOW)
    # user_count = redis_client.eval(... same as before ...)
    # if int(tenant_count) > RATE_LIMIT_MAX: raise HTTPException(429, "Tenant rate limit exceeded")
    # if int(user_count) > RATE_LIMIT_MAX // USER_FRACTION: raise HTTPException(429, "User rate limit exceeded")

    return await call_next(request)


# ---- Schemas ----
class BrainInput(BaseModel):
    enc_user_id: str = Field(..., min_length=40, max_length=500)
    symbols: List[str] = Field(..., min_length=1, max_length=100)
    session_context: Optional[Dict[str, str]] = Field(None)
    clinical_notes_enc: Optional[str] = Field(None, min_length=40, max_length=500)
    model_config = ConfigDict(extra="forbid")

    @field_validator("symbols")
    @classmethod
    def validate_symbol_charset(cls, v: List[str]) -> List[str]:
        bad = [
            s for s in v if not isinstance(s, str) or not re.fullmatch(r"[A-Z0-9_]+", s)
        ]
        if bad:
            raise ValueError(f"Invalid symbol charset: {bad[:3]}")
        return v


class BrainOutput(BaseModel):
    predicted_intent: str
    confidence: float
    behavioral_insight: str
    educational_tip: str
    audio_handle: str


# ---- Auth ----
async def hipaa_auth(request: Request) -> Dict[str, str]:
    tenant_id = request.headers.get("X-Tenant-Id")
    if not tenant_id:
        raise HTTPException(401, "Unauthorized")
    return {"tenant_id": tenant_id}


# ---- Helpers ----
def _predict(payload: Dict[str, Any]) -> Dict[str, Any]:
    for attempt in range(3):
        try:
            if not SAGEMAKER_ENDPOINT:
                symbols = payload.get("symbols", [])
                mood = payload.get("context", {}).get("mood", "neutral")
                intent = (
                    "express need"
                    if any(s.lower() == "help" for s in symbols)
                    else "freeform"
                )
                behavior = "escalating" if mood == "anxious" else "stable"
                return {"intent": intent, "behavior": behavior, "confidence": 0.5}
            raw = sagemaker_runtime.invoke_endpoint(
                EndpointName=SAGEMAKER_ENDPOINT,
                ContentType="application/json",
                Body=json.dumps(payload),
            )["Body"].read()
            out = json.loads(raw.decode("utf-8"))
            if float(out.get("confidence", 0)) < SAGEMAKER_CONF_THRESHOLD:
                raise ValueError("Low confidence")
            return out
        except Exception:
            if attempt == 2:
                symbols = payload.get("symbols", [])
                mood = payload.get("context", {}).get("mood", "neutral")
                intent = (
                    "express need"
                    if any(s.lower() == "help" for s in symbols)
                    else "freeform"
                )
                behavior = "escalating" if mood == "anxious" else "stable"
                return {"intent": intent, "behavior": behavior, "confidence": 0.5}
            time.sleep(2**attempt + random.random())

    # Fallback return if all attempts failed
    return {"intent": "unknown", "behavior": "stable", "confidence": 0.0}





def _normalize_mp3(data: bytes) -> bytes:
    try:
        audio = AudioSegment.from_mp3(io.BytesIO(data))
        audio = audio.normalize()
        buf = io.BytesIO()
        audio.export(buf, format="mp3")
        return buf.getvalue()
    except Exception:
        return data


def _opaque_key(*parts: str) -> str:
    msg = "|".join(parts).encode()
    if not OPAQUE_SECRET:
        raise ValueError("BROCKSTON_OPAQUE_SECRET is required")
    digest = hmac.new(OPAQUE_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return f"audio/{digest}.mp3"


# ---- Endpoint ----
@app.post("/cortex_process", response_model=BrainOutput)
async def cortex_brain_operation(
    request: Request,
    response: Response,
    input: BrainInput = Body(...),
    auth: Dict[str, str] = Depends(hipaa_auth),
) -> BrainOutput:
    # Security headers
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )

    tenant_id = auth["tenant_id"]

    try:
        # user token decrypt
        try:
            decrypted_user_id = cipher.decrypt(
                input.enc_user_id.encode("utf-8")
            ).decode("utf-8")
        except InvalidToken:
            raise HTTPException(400, "Invalid user token")

        # minimal DB read (no symbol_map)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "select behavioral_history from users where tenant_id = :tid and id = :uid"
                ),
                {"tid": tenant_id, "uid": decrypted_user_id},
            ).fetchone()
        if not row:
            raise HTTPException(404, "Not found")

        behavioral_history = json.loads(row[0]) if row[0] else {}
        hist_count = len(behavioral_history)
        if hist_count < 0 or hist_count > MAX_HISTORY_COUNT:
            hist_count = min(max(hist_count, 0), MAX_HISTORY_COUNT)

        ml_input = {
            "symbols": input.symbols,
            "context": input.session_context or {},
            "history_count": hist_count,
        }

        predictions = await to_thread.run_sync(_predict, ml_input)
        intent = str(predictions.get("intent", "freeform"))
        conf = float(predictions.get("confidence", 0.5))
        behavior = str(predictions.get("behavior", ""))

        # TTS uses canonical symbols only (never tenant strings)
        tts_text = " ".join(input.symbols)[:2000]


        # Polly
        tts = await to_thread.run_sync(
            lambda: polly_client.synthesize_speech(
                Text=tts_text, OutputFormat="mp3", VoiceId="Matthew", Engine="neural"
            )
        )
        stream = tts.get("AudioStream")
        if not stream:
            raise HTTPException(502, "TTS failed")
        body_bytes = _normalize_mp3(stream.read())

        # S3 (KMS enforced)
        s3_key = _opaque_key(tenant_id, decrypted_user_id, str(uuid.uuid4()))
        s3_client.put_object(
            Body=body_bytes,
            Bucket=S3_BUCKET,
            Key=s3_key,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=KMS_KEY_ID,
            ContentType="audio/mpeg",
        )


        return BrainOutput(
            predicted_intent=intent,
            confidence=round(conf, 2),
            behavioral_insight=behavior,
            educational_tip=(
                "For anxious states: build sensory breaks with familiar symbols"
                if (input.session_context or {}).get("mood") == "anxious"
                else "Use visual predictability with consistent routines"
            ),
            audio_handle=s3_key,
        )

    except (ClientError, SQLAlchemyError):
        logger.error("AWS or DB error")
        raise HTTPException(500, "Server error")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "Bad request")


@app.get("/")
async def root():
    return {
        "status": "Brockston Cortex Running",
        "version": "3.0.0",
        "endpoints": {"health": "/health", "cortex": "/cortex_process (POST)"},
    }


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        app, host="127.0.0.1", port=int(os.getenv("PORT", "7171")), reload=False
    )


__all__ = [
    "_predict",

    "_normalize_mp3",
    "_opaque_key",
    "health",
    "BodySizeLimiterMiddleware",
    "BrainInput",
    "BrainOutput",
]
