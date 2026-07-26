"""
Rate limiter：Redis sliding window + 三個預設 policy。

設計：
- 核心是 `SlidingWindowLimiter.check(key, limit, window_seconds)`，用 Redis sorted set
  儲存時間戳：先 ZREMRANGEBYSCORE 清掉 window 外舊項，ZCARD 算 window 內數量，
  若未超過就 ZADD。整個序列在 pipeline 內 atomic 執行（避免兩個連線競爭）。
- 另外提供三層 wrapper：
    login_ip_rate_limit(ip)              # 每 IP 每分鐘 10 次
    login_failure_tracker(email, ok=..)  # 連續 5 次失敗鎖 10 分鐘
    llm_per_user_rate_limit(user_id)     # 每 user 每分鐘 20 次
- 超過限制一律抛 RateLimitExceededException（HTTP 429，retry_after 放 details）。
- Redis 連線類故障（redis.exceptions.RedisError）一律 fail-open：放行並 logger.warning。
  與本系統其他 Redis 消費端（紅旗去重、context 快取）的 fail-open 策略一致，
  避免 Redis 掛掉時把登入打成 500、問診 WS 斷線。RateLimitExceededException 是
  正常業務例外，不在攔截範圍（它也不是 RedisError 子類）。

與 auth_service.py 的 BLACKLIST_KEY_PREFIX 一樣不走 `_prefixed_key()`：rate limit keys
在 namespace 上自帶 `gu:rl:` 前綴，方便維運 `SCAN` 分類。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from redis.exceptions import RedisError

from app.core.exceptions import RateLimitExceededException

logger = logging.getLogger(__name__)


# ── Key 前綴 ───────────────────────────────────────────────
RL_LOGIN_IP_PREFIX = "gu:rl:login_ip:"
RL_LOGIN_FAIL_PREFIX = "gu:rl:login_fail:"
RL_LOGIN_LOCKED_PREFIX = "gu:rl:login_locked:"
RL_LLM_USER_PREFIX = "gu:rl:llm_user:"
RL_PWRESET_IP_PREFIX = "gu:rl:pwreset_ip:"
RL_REGISTER_IP_PREFIX = "gu:rl:register_ip:"
RL_REFRESH_IP_PREFIX = "gu:rl:refresh_ip:"


# ── 預設 policy 參數 ───────────────────────────────────────
LOGIN_IP_LIMIT = 10          # 10 次
LOGIN_IP_WINDOW = 60         # 每 60 秒
LOGIN_FAIL_THRESHOLD = 5     # 連續 5 次
LOGIN_LOCKOUT_SECONDS = 600  # 鎖 10 分鐘
LOGIN_FAIL_WINDOW = 600      # 失敗計數視窗（跟鎖定長度一致）
LLM_USER_LIMIT = 20          # 20 次
LLM_USER_WINDOW = 60         # 每 60 秒
# 註冊端點 per-IP：建立帳號成本高、易被當成 enumeration / spam 管道，故較嚴。
REGISTER_IP_LIMIT = 5        # 5 次
REGISTER_IP_WINDOW = 3600    # 每 1 小時
# Refresh token 端點 per-IP：正常使用頻率低，但不該被無限換發；介於登入與註冊之間。
REFRESH_IP_LIMIT = 30        # 30 次
REFRESH_IP_WINDOW = 900      # 每 15 分鐘


# ──────────────────────────────────────────────────────────
# 核心：Sliding window
# ──────────────────────────────────────────────────────────

class SlidingWindowLimiter:
    """Redis sorted-set 實作的 sliding window。"""

    @staticmethod
    async def check(
        redis: Any,
        key: str,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """
        嘗試在 `key` 下記錄一次請求。

        Returns:
            (allowed, retry_after_seconds)
            - allowed=True ：已記錄、未超限
            - allowed=False：window 內已達 limit，未記錄；retry_after 為最舊項預估釋出秒數

        Redis 連線類故障（RedisError）時 fail-open：回 (True, 0) 並 logger.warning。
        """
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        cutoff = now_ms - window_ms

        try:
            pipe = redis.pipeline(transaction=True)
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            results = await pipe.execute()
            current = int(results[1])

            if current >= limit:
                # window 內已達上限：估算最舊 timestamp → retry_after
                oldest = await redis.zrange(key, 0, 0, withscores=True)
                retry_after = 1
                if oldest:
                    # oldest[0] = (member, score)；ceil 到下一秒，確保不超過 window
                    oldest_score = int(oldest[0][1])
                    diff_ms = oldest_score + window_ms - now_ms
                    retry_after = max(1, (diff_ms + 999) // 1000)
                return False, int(retry_after)

            # 未超限：記錄本次；TTL 設 window+1 秒讓 key 自動過期（節省空間）
            pipe = redis.pipeline(transaction=True)
            # member 用 now_ms + 隨機後綴避免同毫秒併發 ZADD 被 dedup
            member = f"{now_ms}:{_random_suffix()}"
            pipe.zadd(key, {member: now_ms})
            pipe.expire(key, window_seconds + 1)
            await pipe.execute()
            return True, 0
        except RedisError as exc:
            # fail-open：rate limit 是保護機制，不該因 Redis 故障擋掉正常流量
            logger.warning(
                "rate limit fail-open: Redis unavailable key=%s error=%s",
                key, type(exc).__name__,
            )
            return True, 0


def _random_suffix() -> str:
    """短亂數字串，避免同毫秒 ZADD 因 member 重複被吃掉。"""
    import os
    return os.urandom(4).hex()


# ──────────────────────────────────────────────────────────
# Policy 1：Login per-IP
# ──────────────────────────────────────────────────────────

async def enforce_login_ip_rate_limit(redis: Any, ip: str) -> None:
    """超過 `LOGIN_IP_LIMIT/LOGIN_IP_WINDOW` → 抛 RateLimitExceededException。"""
    if not ip:
        # 沒 IP 資訊（測試、健康檢查）就不擋
        return
    key = f"{RL_LOGIN_IP_PREFIX}{ip}"
    allowed, retry_after = await SlidingWindowLimiter.check(
        redis, key, LOGIN_IP_LIMIT, LOGIN_IP_WINDOW
    )
    if not allowed:
        logger.warning("login IP rate limit hit ip=%s retry_after=%d", ip, retry_after)
        raise RateLimitExceededException(
            message="errors.login_ip_rate_limited",
            details={"retry_after": retry_after, "scope": "ip"},
            message_kwargs={"retry_after": retry_after},
        )


# ──────────────────────────────────────────────────────────
# Policy 1a：Register per-IP（註冊端點）
# ──────────────────────────────────────────────────────────

async def enforce_register_ip_rate_limit(redis: Any, ip: str) -> None:
    """註冊端點的 per-IP sliding window（預設 `REGISTER_IP_LIMIT/REGISTER_IP_WINDOW`）。

    超過上限即抛 RateLimitExceededException（HTTP 429，retry_after 放 details）。
    """
    if not ip:
        # 沒 IP 資訊（測試、健康檢查）就不擋，與 login IP policy 一致
        return
    key = f"{RL_REGISTER_IP_PREFIX}{ip}"
    allowed, retry_after = await SlidingWindowLimiter.check(
        redis, key, REGISTER_IP_LIMIT, REGISTER_IP_WINDOW
    )
    if not allowed:
        logger.warning("register IP rate limit hit ip=%s retry_after=%d", ip, retry_after)
        raise RateLimitExceededException(
            message="errors.login_ip_rate_limited",
            details={"retry_after": retry_after, "scope": "register_ip"},
            message_kwargs={"retry_after": retry_after},
        )


# ──────────────────────────────────────────────────────────
# Policy 1c：Refresh token per-IP（換發 access token 端點）
# ──────────────────────────────────────────────────────────

async def enforce_refresh_ip_rate_limit(redis: Any, ip: str) -> None:
    """Refresh token 端點的 per-IP sliding window（預設 `REFRESH_IP_LIMIT/REFRESH_IP_WINDOW`）。

    超過上限即抛 RateLimitExceededException（HTTP 429，retry_after 放 details）。
    """
    if not ip:
        # 沒 IP 資訊（測試、健康檢查）就不擋，與 login IP policy 一致
        return
    key = f"{RL_REFRESH_IP_PREFIX}{ip}"
    allowed, retry_after = await SlidingWindowLimiter.check(
        redis, key, REFRESH_IP_LIMIT, REFRESH_IP_WINDOW
    )
    if not allowed:
        logger.warning("refresh IP rate limit hit ip=%s retry_after=%d", ip, retry_after)
        raise RateLimitExceededException(
            message="errors.login_ip_rate_limited",
            details={"retry_after": retry_after, "scope": "refresh_ip"},
            message_kwargs={"retry_after": retry_after},
        )


# ──────────────────────────────────────────────────────────
# Policy 1b：Password reset per-IP（忘記 / 重設密碼端點）
# ──────────────────────────────────────────────────────────

async def enforce_password_reset_ip_rate_limit(redis: Any, ip: str) -> None:
    """忘記 / 重設密碼端點的 per-IP sliding window。

    比登入保守（預設 5 次 / 15 分鐘，見 settings.PASSWORD_RESET_IP_*）：
    這兩個端點會寄信 / 改密碼，成本高且容易被當帳號 enumeration / 暴力管道，
    超過上限即抛 RateLimitExceededException（HTTP 429，retry_after 放 details）。
    """
    if not ip:
        # 沒 IP 資訊（測試、健康檢查）就不擋，與 login IP policy 一致
        return
    from app.core.config import settings

    key = f"{RL_PWRESET_IP_PREFIX}{ip}"
    allowed, retry_after = await SlidingWindowLimiter.check(
        redis,
        key,
        settings.PASSWORD_RESET_IP_LIMIT,
        settings.PASSWORD_RESET_IP_WINDOW,
    )
    if not allowed:
        logger.warning(
            "password reset IP rate limit hit ip=%s retry_after=%d", ip, retry_after
        )
        raise RateLimitExceededException(
            message="errors.login_ip_rate_limited",
            details={"retry_after": retry_after, "scope": "password_reset_ip"},
            message_kwargs={"retry_after": retry_after},
        )


# ──────────────────────────────────────────────────────────
# Policy 2：Login failure tracker（帳號鎖定）
# ──────────────────────────────────────────────────────────

async def enforce_account_not_locked(redis: Any, email: str) -> None:
    """若帳號在鎖定中 → 抛 RateLimitExceededException。"""
    if not email:
        return
    key = f"{RL_LOGIN_LOCKED_PREFIX}{email.lower()}"
    try:
        ttl = await redis.ttl(key)
    except RedisError as exc:
        # fail-open：Redis 故障時視為未鎖定（key 含 email，log 只帶前綴避免落入使用者輸入）
        logger.warning(
            "rate limit fail-open: Redis unavailable key_prefix=%s error=%s",
            RL_LOGIN_LOCKED_PREFIX, type(exc).__name__,
        )
        return
    # redis-py 對不存在的 key 回 -2，無 TTL 的 key 回 -1
    if ttl is not None and ttl > 0:
        raise RateLimitExceededException(
            message="errors.account_locked",
            details={"retry_after": int(ttl), "scope": "account"},
            message_kwargs={"retry_after": int(ttl)},
        )


async def record_login_failure(redis: Any, email: str) -> int:
    """
    登入失敗時呼叫。回傳目前累積失敗次數。
    達到 `LOGIN_FAIL_THRESHOLD` 時自動寫鎖定 key（TTL = LOGIN_LOCKOUT_SECONDS），
    並清掉計數 key。
    """
    if not email:
        return 0
    fail_key = f"{RL_LOGIN_FAIL_PREFIX}{email.lower()}"
    try:
        count = int(await redis.incr(fail_key))
        if count == 1:
            # 新計數窗口：TTL = LOGIN_FAIL_WINDOW
            await redis.expire(fail_key, LOGIN_FAIL_WINDOW)
        if count >= LOGIN_FAIL_THRESHOLD:
            locked_key = f"{RL_LOGIN_LOCKED_PREFIX}{email.lower()}"
            await redis.setex(locked_key, LOGIN_LOCKOUT_SECONDS, "1")
            await redis.delete(fail_key)
            logger.warning(
                "account locked email=%s after %d failures, lockout=%ds",
                email, count, LOGIN_LOCKOUT_SECONDS,
            )
        return count
    except RedisError as exc:
        # fail-open：Redis 故障時不讓「記失敗」把 401 變 500（key 含 email，只 log 前綴）
        logger.warning(
            "rate limit fail-open: Redis unavailable key_prefix=%s error=%s",
            RL_LOGIN_FAIL_PREFIX, type(exc).__name__,
        )
        return 0


async def clear_login_failures(redis: Any, email: str) -> None:
    """登入成功時呼叫，清掉該帳號的失敗計數與鎖（正常不會有鎖，防禦性清除）。"""
    if not email:
        return
    try:
        await redis.delete(
            f"{RL_LOGIN_FAIL_PREFIX}{email.lower()}",
            f"{RL_LOGIN_LOCKED_PREFIX}{email.lower()}",
        )
    except RedisError as exc:
        # fail-open：清除失敗不該讓成功登入變 500（key 含 email，只 log 前綴）
        logger.warning(
            "rate limit fail-open: Redis unavailable key_prefix=%s error=%s",
            RL_LOGIN_FAIL_PREFIX, type(exc).__name__,
        )


# ──────────────────────────────────────────────────────────
# Policy 3：LLM per-user
# ──────────────────────────────────────────────────────────

async def enforce_llm_per_user_rate_limit(redis: Any, user_id: Any) -> None:
    """每 user 每 `LLM_USER_WINDOW` 秒 `LLM_USER_LIMIT` 次 LLM 呼叫。"""
    if user_id is None:
        return
    key = f"{RL_LLM_USER_PREFIX}{user_id}"
    allowed, retry_after = await SlidingWindowLimiter.check(
        redis, key, LLM_USER_LIMIT, LLM_USER_WINDOW
    )
    if not allowed:
        logger.warning("LLM rate limit hit user=%s retry_after=%d", user_id, retry_after)
        raise RateLimitExceededException(
            message="errors.llm_rate_limited",
            details={"retry_after": retry_after, "scope": "llm_user"},
            message_kwargs={"retry_after": retry_after},
        )
