"""Per-device bearer tokens (no passwords, no email). Token is shown once at registration; only its hash is stored."""
import collections
import hashlib
import secrets
import time
import uuid

from fastapi import Depends, Header, Request

from .config import cfg
from .db import get_db
from .errors import ApiError

_hits: dict[tuple[str, str], collections.deque] = collections.defaultdict(collections.deque)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def hash_token(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def create_user(db, name: str | None) -> tuple[str, str]:
    uid, token = uuid.uuid4().hex, "hb_" + secrets.token_urlsafe(32)
    db.execute("INSERT INTO users(id,name,token_hash,created_at) VALUES (?,?,?,?)", (uid, (name or "")[:60], hash_token(token), now_iso()))
    db.commit()
    return uid, token


def _limit(user_id: str, bucket: str, per_min: int):
    q = _hits[(user_id, bucket)]
    now = time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_min:
        raise ApiError(429, "rate_limited", "Too many requests. Slow down.", retry_after=int(60 - (now - q[0])) + 1)
    q.append(now)


def current_user(request: Request, authorization: str | None = Header(None), db=Depends(get_db)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "missing_token", "Send 'Authorization: Bearer <token>' (get one from POST /api/v1/auth/register).")
    row = db.execute("SELECT id, name FROM users WHERE token_hash=?", (hash_token(authorization[7:].strip()),)).fetchone()
    if not row:
        raise ApiError(401, "invalid_token", "Unknown token.")
    _limit(row["id"], "api", cfg.rate_per_min)
    request.state.user_id = row["id"]
    return {"id": row["id"], "name": row["name"]}


def gnani_user(user: dict = Depends(current_user)) -> dict:
    """Stricter bucket for routes that spend Gnani credits."""
    _limit(user["id"], "gnani", cfg.gnani_rate_per_min)
    return user


def reset_rate_limits():
    _hits.clear()
