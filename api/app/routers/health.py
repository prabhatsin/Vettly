import redis
from fastapi import APIRouter
from sqlalchemy import create_engine, text

from app.config import settings

router = APIRouter()

engine = create_engine(settings.database_url, pool_pre_ping=True)
redis_client = redis.Redis.from_url(
    settings.redis_url,
    socket_connect_timeout=1,
    socket_timeout=1,
)


@router.get("/health")
def health():
    result = {"status": "ok", "postgres": "ok", "redis": "ok"}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        result["postgres"] = "down"

    try:
        redis_client.ping()
    except Exception:
        result["redis"] = "down"
    if "down" in (result["postgres"], result["redis"]):
        result["status"] = "degraded"
    return result


#! Learning 
# SELECT 1
'''
SQL also lets you select a constant value with no table at all:

SELECT 1;        -- returns the number 1
SELECT 'hello';  -- returns the text hello
SELECT 2 + 3;    -- returns 5
SELECT now();    -- returns the current time

we can use these for health checks 
'''

#! Question : Why not livekit server not included in the  health check , ?? 

'''
=>In this layer0 execution we are checking the health of api endpoints i.e checking are api's working fine
or not ,
why only postgres/ redis is included:
=>Postgres/Redis: every API request that touches users, jobs or applications needs them. If they're down,
 the API is broken, so /health must say so.

=> LiveKit: the API only creates a signed token (a JWT built from the key and secret) and hands it to the
 browser. That is local math, with no network call to the LiveKit server. The browser and the agent are 
 the ones that connect to LiveKit.

#? will do it in the layer 2

'''