"""
場次超時檢查定期任務
- 將超過指定時間仍為 in_progress 的場次標記為 cancelled
- 預設超時時間為 60 分鐘

## 「終態轉移六件事」在本任務的適用性（CLAUDE.md 鐵律）

新增場次終態轉移時六件事一起做——改 status、派 SOAP、送病患端 `session_status`、
廣播 dashboard、建醫師通知、設 `_terminated`。本任務跑在 **Celery worker 行程**，
情境與 WS 路徑不同，逐項評估如下（刻意省略的都在此記載，不是漏做）：

1. **改 status**：做。改走 compare-and-set（``UPDATE ... WHERE status='in_progress'``）
   並先查 ``app.core.session_state.is_valid_transition``，見 ``_async_check``。
2. **派 SOAP**：**刻意不做**。cancelled 不派 SOAP 是既定政策（cancelled 場次
   ``soap_reports`` 為 0 列是設計行為，非缺陷）——逾時場次多半連對話都沒幾輪，
   生成的報告對醫師無診斷價值。要改此政策請連同 REST 取消路徑
   （``SessionService`` 的 cancel）一起改，別只改這裡。
3. **送病患端 `session_status`**：**刻意不做（架構限制）**。病患 WS 連線存在
   ``ConnectionManager.active_connections``——那是 **API 行程的 in-memory dict**，
   本任務所在的 Celery 行程碰不到；全碼庫唯一的跨行程 pub/sub 橋接是
   ``DASHBOARD_EVENTS_CHANNEL``（只 fan-out 給 dashboard 連線，見
   ``dashboard_handler._dispatch_dashboard_event``），沒有 per-session 的等價物。
   且逾時定義就是「60 分鐘無任何更新」，病患端幾乎必然早已離線。
   為此發明 per-session Redis 橋接屬過度工程，故以本註解記載限制後省略。
4. **廣播 dashboard**：做，本次修復的核心。每場取消後 publish
   ``session_status_changed``，整批結束後刷新一次 queue/stats。跨行程走 Redis
   publish（與 ``report_queue._publish_report_generated`` 同一機制）。
5. **建醫師通知**：**刻意不做**。``NotificationType`` 只有 red_flag /
   session_complete / report_ready / system 四種，沒有「場次逾時取消」語意的類型；
   逾時取消非紅旗、非完成，也不會有報告。新增列舉值需要 Alembic
   ``ALTER TYPE ... ADD VALUE`` 遷移 + 通知偏好欄位 + i18n 字串，屬獨立需求，
   不在本次修復範圍內發明。
6. **設 `_terminated`**：**不適用**。那是 ``conversation_handler`` 的
   ``session_context`` 行程內旗標（用來讓 WS 主迴圈知道自己該收工），
   Celery 任務沒有該 context，也沒有主迴圈要中止。
"""

import logging

from app.tasks import celery_app

logger = logging.getLogger(__name__)

# 場次超時閾值（分鐘）
SESSION_TIMEOUT_MINUTES = 60

# dashboard `session_status_changed` 的在地化 code。
# 沿用 WS 閒置逾時同一則字串（「閒置逾時（{{minutes}} 分鐘無活動），場次自動結束」）
# ——語意完全吻合本任務的判定條件（in_progress 且 updated_at 逾期），
# 不必為此在三份 locale 拷貝新增 key。
_TIMEOUT_EVENT_CODE = "events.session.idle_timeout"


@celery_app.task(
    name="app.tasks.session_timeout.check_session_timeouts",
    bind=True,
    max_retries=1,
    acks_late=True,
)
def check_session_timeouts(self) -> dict:
    """
    檢查並處理超時場次（Celery 定期任務）

    Returns:
        處理結果統計
    """
    import asyncio

    try:
        result = asyncio.get_event_loop().run_until_complete(_async_check())
        return result
    except Exception:
        result = asyncio.run(_async_check())
        return result


async def _async_check() -> dict:
    """非同步超時檢查核心邏輯。

    每場獨立 compare-and-set + commit，成功才推播——避免兩件事：
    - **覆寫別人的終態**：先前是 SELECT 後逐一改欄位再整批 commit，
      期間若 WS 行程把同一場次轉成 completed / aborted_red_flag，
      本任務會用 cancelled 蓋掉（抹掉醫師端的紅旗分流訊號）。
    - **推播與 DB 不一致**：CAS 未命中（row is None）就完全不推播。
    """
    from datetime import timedelta

    from sqlalchemy import Integer, func, select, update

    from app.core.database import async_session_factory
    from app.core.session_state import is_valid_transition
    from app.models.enums import SessionStatus
    from app.models.session import Session
    from app.utils.datetime_utils import utc_now

    # 單一權威狀態機把關：in_progress → cancelled 目前合法，但不硬編碼這個事實，
    # 改由 VALID_TRANSITIONS 決定。日後若狀態表收緊，本任務會自動停手而非漂移。
    if not is_valid_transition(SessionStatus.IN_PROGRESS, SessionStatus.CANCELLED):
        logger.error(
            "狀態機不允許 in_progress → cancelled，逾時清理任務停手（請檢查 VALID_TRANSITIONS）"
        )
        return {"timed_out": 0, "skipped_invalid_transition": True}

    timeout_threshold = utc_now() - timedelta(minutes=SESSION_TIMEOUT_MINUTES)

    async with async_session_factory() as db:
        # 查詢超時的 in_progress 場次（只取 id：真正的狀態判定交給下面的 CAS）
        result = await db.execute(
            select(Session.id, Session.updated_at)
            .where(Session.status == SessionStatus.IN_PROGRESS)
            .where(Session.updated_at < timeout_threshold)
        )
        stale_rows = result.all()

        if not stale_rows:
            logger.info("無超時場次需要處理")
            return {"timed_out": 0}

        timed_out_ids: list[str] = []
        skipped = 0

        for session_id, last_updated in stale_rows:
            now = utc_now()
            stmt = (
                update(Session)
                .where(Session.id == session_id)
                # compare-and-set：僅當 DB 目前仍是 in_progress 才轉移，
                # 對齊 conversation_handler._update_session_status 的語意。
                .where(Session.status == SessionStatus.IN_PROGRESS)
                .values(
                    status=SessionStatus.CANCELLED,
                    completed_at=now,
                    updated_at=now,
                    # 與 REST 取消路徑（SessionService）對稱補寫；
                    # started_at 為 NULL 時運算結果為 NULL，保持缺值不硬塞 0。
                    duration_seconds=func.cast(
                        func.extract("epoch", func.now() - Session.started_at),
                        Integer,
                    ),
                )
                .returning(Session.id)
            )
            row = (await db.execute(stmt)).first()
            await db.commit()

            if row is None:
                # 別的行程（WS 終態、REST 取消）已先一步轉移——不覆寫、不推播。
                skipped += 1
                logger.info(
                    "場次 %s 已非 in_progress（他處已轉終態），逾時清理略過",
                    session_id,
                )
                continue

            timed_out_ids.append(str(session_id))
            logger.info(
                "場次 %s 已超時（上次更新: %s），標記為 cancelled",
                session_id,
                last_updated,
            )
            await _publish_session_cancelled(str(session_id))

        if timed_out_ids:
            # 批次結束後刷新一次排隊/統計（逐場刷是白燒 DB 查詢）。
            await _broadcast_queue_and_stats(db)

        logger.info(
            "共處理 %d 個超時場次（略過 %d 個已轉終態）", len(timed_out_ids), skipped
        )
        return {
            "timed_out": len(timed_out_ids),
            "session_ids": timed_out_ids,
            "skipped": skipped,
        }


async def _publish_session_cancelled(session_id: str) -> None:
    """把 ``session_status_changed``（cancelled）publish 到 Redis 儀表板頻道。

    在 Celery worker 行程觸發，本行程沒有任何 dashboard WS 連線，故不可用
    in-memory 廣播；走 ``publish_dashboard_event`` 由 API 行程的 subscriber
    收到後本地 fan-out（與 ``report_queue._publish_report_generated`` 同一機制）。

    payload 形狀對齊 conversation_handler 的 ``broadcast_localized_dashboard``：
    canonical ``code/params/severity`` + camelCase 的結構欄位。
    推播失敗絕不可影響已 commit 的狀態轉移。
    """
    from app.websocket.connection_manager import publish_dashboard_event

    try:
        await publish_dashboard_event(
            "session_status_changed",
            {
                "code": _TIMEOUT_EVENT_CODE,
                "params": {"minutes": SESSION_TIMEOUT_MINUTES},
                "severity": "warning",
                "sessionId": session_id,
                "status": "cancelled",
                "previousStatus": "in_progress",
            },
        )
    except Exception as exc:  # noqa: BLE001 — 推播失敗不可影響任務結果
        logger.warning(
            "場次 %s session_status_changed 推播失敗（非致命） | error=%s",
            session_id,
            exc,
        )


async def _broadcast_queue_and_stats(db) -> None:
    """重算並推播 queue_updated + stats_updated。

    Redis 客戶端刻意就地建立、用完關閉，不走 ``cache.redis_client.get_redis``
    的全域連線池：Celery task body 每次可能以 ``asyncio.run`` 開新 event loop，
    而全域池會綁在第一次建立時的 loop 上，第二次執行就會踩到 loop 已關閉。
    這也是 ``ConnectionManager.publish_dashboard_event`` 採用的作法。
    """
    client = None
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings
        from app.websocket.dashboard_handler import broadcast_queue_and_stats

        client = aioredis.from_url(
            settings.REDIS_URL_CACHE,
            encoding="utf-8",
            decode_responses=True,
        )
        await broadcast_queue_and_stats(db, client)
    except Exception as exc:  # noqa: BLE001 — 推播失敗不可影響任務結果
        logger.warning("逾時清理後推播 queue/stats 失敗（非致命） | error=%s", exc)
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — 連線關閉失敗可忽略
                pass
