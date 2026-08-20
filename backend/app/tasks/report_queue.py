"""
SOAP 報告生成 Celery 任務
- 從 Session + Patient + Conversation 取得完整上下文
- 以 SOAP_REPORT_LANGUAGE（固定 zh-TW，2026-07-19 產品決策）呼叫 SOAPGenerator
- 將結果寫回 SOAPReport（含 language 欄位）
"""

import logging

from celery import Task

from app.tasks import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在同步 Celery worker context 內安全執行 async coroutine。

    與 generate_soap_report 的執行策略一致：優先沿用既有 event loop，
    若已在運行則改用 asyncio.run 新建一個 loop。
    """
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("event loop already running")
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class _SOAPReportTask(Task):
    """
    自訂 Celery Task 基底，提供 on_failure 安全網。

    當任務在重試耗盡後仍最終失敗（或 task body 以非預期方式拋出），
    Celery 會呼叫 on_failure；此處將對應 SOAPReport 標記為 FAILED，
    確保報告不會永遠卡在 'generating' 狀態。
    """

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: D401
        session_id = None
        if args:
            session_id = args[0]
        elif kwargs:
            session_id = kwargs.get("session_id")
        if not session_id:
            logger.error(
                "SOAP 報告任務最終失敗但無法解析 session_id，無法標記 FAILED: %s",
                exc,
            )
            return
        try:
            _run_async(_mark_report_failed(str(session_id)))
            logger.error(
                "SOAP 報告任務最終失敗，已將場次 %s 報告標記為 FAILED: %s",
                session_id,
                exc,
            )
        except Exception:  # noqa: BLE001 — on_failure 內不可再向上拋
            logger.exception(
                "SOAP 報告任務 on_failure 標記 FAILED 失敗: session=%s", session_id
            )


class ReportRowNotReadyError(RuntimeError):
    """SOAP 報告列還沒出現在 DB（SO-4）。

    `_generate_soap_report_async` 的觸發器語意是「建 GENERATING row → 派 Celery」
    （不變式 #13）。這兩件事分屬**不同交易**：API 行程 commit 報告列的時間點
    與 Celery worker 撈到任務的時間點沒有先後保證，worker 快一步就會查不到列。

    舊版在這個分支直接 `return {"reason": "report_not_found"}` ——
    不重試、不標 FAILED，於是：OpenAI 的錢已經花掉、報告內容**整份丟棄**，
    而報告列隨後才出現、永遠停在 GENERATING，醫師端等不到任何東西。

    這是**時序**問題不是資料問題，重跑一次多半就好了，所以刻意做成
    可重試例外（`_is_retryable` 的預設分支即為可重試）。
    """


def _is_retryable(exc: BaseException) -> bool:
    """判斷例外是否值得重試。

    預設可重試（OpenAI 逾時／JSON 解析失敗經 ``AIServiceUnavailableException``、
    DB 連線瞬斷等都屬此類，重跑一次多半就好了）；只有「資料本身有問題」的例外
    重跑幾次結果都一樣，直接 FAILED 讓醫師端看得到並手動處理，
    不必白燒 2 次 OpenAI 呼叫與 60 秒。
    """
    from app.core.exceptions import NotFoundException, ValidationException

    return not isinstance(exc, (NotFoundException, ValidationException))


def _run_task(task, session_id: str) -> dict:
    """Celery task body：跑生成，並在失敗時決定「重試」或「標 FAILED」。

    抽成獨立函式是為了讓重試決策可用假的 task 物件單元測試——
    ``bind=True`` 的 task 無法注入 self，而直接呼叫 ``task.retry()``
    在 worker 外會走 ``called_directly`` 分支，測不到真正的生產行為。

    不變式：**重試前絕不標 FAILED**，否則重試成功也會留下錯誤狀態；
    只有重試次數用盡（或例外不值得重試）才標 FAILED。
    """
    try:
        return _run_async(_async_generate(session_id))
    except Exception as exc:
        retries = task.request.retries or 0
        max_retries = task.max_retries or 0
        if _is_retryable(exc) and retries < max_retries:
            logger.warning(
                "場次 %s SOAP 報告生成失敗，將重試（第 %d/%d 次，%s 秒後）: %s",
                session_id,
                retries + 1,
                max_retries,
                task.default_retry_delay,
                exc,
            )
            # 報告維持 GENERATING，等重試結果；retry() 會拋 Retry 中止本次執行。
            raise task.retry(exc=exc, countdown=task.default_retry_delay)

        logger.error(
            "場次 %s SOAP 報告生成最終失敗（已重試 %d 次），標記 FAILED: %s",
            session_id,
            retries,
            exc,
        )
        try:
            _run_async(_mark_report_failed(str(session_id)))
        except Exception:  # noqa: BLE001 — 標記失敗不可蓋掉原始錯誤
            logger.exception(
                "場次 %s 標記 FAILED 失敗（on_failure 會再兜底一次）", session_id
            )
        raise


@celery_app.task(
    base=_SOAPReportTask,
    name="app.tasks.report_queue.generate_soap_report",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def generate_soap_report(self, session_id: str) -> dict:
    """
    生成 SOAP 報告（同步 Celery 任務，內部以同步方式執行 async 邏輯）

    失敗時最多重試 2 次（間隔 30 秒），重試期間報告維持 GENERATING；
    重試耗盡或遇到不值得重試的錯誤才標記 FAILED。詳見 ``_run_task``。

    Args:
        session_id: 場次 ID

    Returns:
        包含報告 ID 與狀態的字典
    """
    return _run_task(self, session_id)


async def _mark_report_failed(session_id: str) -> None:
    """獨立交易：把指定場次的 SOAPReport 標記為 FAILED 並 commit，
    然後**讓人知道**（SO-2 的通知半邊）。

    供 on_failure 安全網使用——task body 內已有 except 路徑會處理多數情況，
    此函式為「最終失敗」時的兜底，獨立開一個 session 以免沿用已 rollback 的交易。

    ── 為什麼要加廣播與通知 ──────────────────────────────
    舊版只改一個 DB 欄位就結束。醫師端沒有任何 push：儀表板不會重抓、
    通知中心沒有一筆、iOS 也不響。結果是**只有正在盯著那一場的醫師、
    而且剛好手動重整**才會發現報告生不出來——實際上等於沒人知道。
    問診已經做完、病患也已經被告知「請稍候等看診」，這時報告靜默消失
    是最糟的失敗模式。
    """
    from app.core.database import async_session_factory
    from app.models.enums import ReportStatus

    async with async_session_factory() as db:
        await _update_report_status(db, session_id, ReportStatus.FAILED)
        await db.commit()
        await _announce_report_failure(db, session_id)


async def _announce_report_failure(db, session_id: str) -> None:
    """FAILED 之後的可觀測性：dashboard 事件 ＋ 醫師站內通知（皆 best-effort）。

    ── 為什麼沿用 `report_generated` 而不是新增 `report_failed` ──
    不變式 #27：WS 事件的訂閱清單在 React 與 Flutter 是**手抄兩份、沒有
    codegen**，後端加新事件而兩端沒訂閱＝靜默丟失（`resume_failed` 就是
    這樣出事的）。查過兩端的實際訂閱與處理方式：

      React  SessionListPage.tsx:96          → `handleRefresh()`，payload 不看
             ResearchAnalyticsPage.tsx:119   → debounce 後重抓 analytics
      Flutter sessions_list_controller.dart:9 → `reload()`，payload 明確忽略
             notifications_controller.dart:188 → debounce 後重抓通知列表

    四個訂閱點**全部**是「收到就用 REST 重抓」，沒有任何一處讀 payload 的
    `status`。所以帶 `status="failed"` 的 `report_generated` 會讓兩端重抓，
    而重抓拿到的報告狀態就是 `failed`（Flutter session_detail_page.dart:31
    已經有 `generating | generated | failed` 三態渲染）——**不改前端就能看到**。

    ⚠️ 記在這裡以免將來誤解：`ReportGeneratedPayload.status` 目前在兩端都是
    死欄位。若哪天要讓前端對失敗做不同的 UI（紅色 toast 之類），改法是**讓
    前端開始讀 `status`**，而不是新增一個兩端都沒訂的事件型別。
    """
    from app.models.session import Session
    from app.models.soap_report import SOAPReport
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    report_id = ""
    patient_name = ""
    try:
        row = (
            await db.execute(
                select(Session)
                .options(selectinload(Session.patient))
                .where(Session.id == session_id)
            )
        ).scalar_one_or_none()
        if row is not None and row.patient is not None:
            patient_name = getattr(row.patient, "name", "") or ""
        report = (
            await db.execute(
                select(SOAPReport).where(SOAPReport.session_id == session_id)
            )
        ).scalar_one_or_none()
        if report is not None:
            report_id = str(report.id)
    except Exception as exc:  # noqa: BLE001 — 查不到只是 payload 少幾個欄位
        logger.warning(
            "場次 %s 取得失敗通知所需資料時出錯（非致命）| error=%s", session_id, exc
        )

    try:
        await _publish_report_generated(
            report_id=report_id,
            session_id=session_id,
            patient_name=patient_name,
            status="failed",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "場次 %s report_generated(failed) 推播失敗（非致命）| error=%s",
            session_id,
            exc,
        )

    try:
        from app.services.notification_service import NotificationService

        await NotificationService.notify_report_failed(
            db, session_id=session_id, report_id=report_id or None
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "場次 %s 報告失敗通知建立失敗（非致命）| error=%s", session_id, exc
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _async_generate(session_id: str) -> dict:
    """非同步報告生成核心邏輯。

    失敗語意：可預期的資料問題（無場次／無對話／無報告列）以回傳 dict 表示，
    呼叫端不會重試；非預期例外一律 rollback 後往上拋，**不在此標記 FAILED**——
    是否重試、何時才標 FAILED 由 ``_run_task`` 依 Celery 重試次數決定。
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.core.config import settings
    from app.core.database import async_session_factory
    from app.models.enums import ReportRevisionReason, ReportStatus
    from app.models.session import Session
    from app.models.soap_report import SOAPReport
    from app.pipelines.icd10_symptom_map import resolve_symptom_id
    from app.pipelines.patient_context import build_patient_info
    from app.pipelines.soap_generator import SOAPGenerator
    from app.utils.datetime_utils import utc_now

    async with async_session_factory() as db:
        try:
            stmt = (
                select(Session)
                .options(
                    selectinload(Session.patient),
                    selectinload(Session.conversations),
                    selectinload(Session.chief_complaint),
                )
                .where(Session.id == session_id)
            )
            session_obj = (await db.execute(stmt)).scalar_one_or_none()

            if session_obj is None:
                # 早退也必須把報告列標 FAILED，否則會永遠停在 GENERATING、
                # 醫師端連「重新生成」按鈕都等不到（報告列若不存在則 no-op）。
                logger.warning("場次 %s 不存在，無法生成報告", session_id)
                await _update_report_status(db, session_id, ReportStatus.FAILED)
                await db.commit()
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "reason": "session_not_found",
                }

            conversations = list(session_obj.conversations or [])
            if not conversations:
                logger.warning("場次 %s 無對話紀錄，無法生成報告", session_id)
                await _update_report_status(db, session_id, ReportStatus.FAILED)
                await db.commit()
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "reason": "no_conversations",
                }

            transcript: list[dict[str, object]] = []
            for conv in conversations:
                role_value = conv.role.value if hasattr(conv.role, "value") else str(conv.role)
                transcript.append(
                    {
                        "role": role_value,
                        "content": conv.content_text or "",
                        "timestamp": conv.created_at.isoformat() if conv.created_at else "",
                    }
                )

            # 病患背景資訊與 WS 對話路徑共用單一來源（app/pipelines/patient_context.py）。
            # 舊版在此自行重組，只放 name/gender/age、完全不讀 sessions.intake_data，
            # 導致 soap_generator 的 past_medical_history / medications / allergies /
            # family_history 四個分支在生產路徑成為死碼（實測：intake 明載
            # 「父親：膀胱癌」，SOAP 卻寫 family_history=「未提供」）。不可再 inline。
            # patient 關聯已於上方 selectinload 預載，此處存取不會 DetachedInstanceError。
            # intake_data 用 getattr 取：真實 `Session` 一定有這個 mapped column，
            # 預設值只為了容忍不完整的測試替身，生產行為完全相同
            # （WS 路徑的呼叫點亦同）。
            patient_info: dict[str, object] = build_patient_info(
                session_obj.patient, getattr(session_obj, "intake_data", None)
            )

            chief_complaint_text = session_obj.chief_complaint_text or ""
            if not chief_complaint_text and session_obj.chief_complaint is not None:
                chief_complaint_text = getattr(session_obj.chief_complaint, "name", "") or ""

            # M3：symptom_id 供 ICD-10 validator 對映——優先取 ChiefComplaint.name_en
            # 正規化後的 snake_case slug（與 `icd10_symptom_map.SYMPTOM_TO_ICD10` 的 key 相容）。
            # B2：共用函式見 icd10_symptom_map.resolve_symptom_id（WS 路徑亦使用）。
            symptom_id = resolve_symptom_id(session_obj)

            # 取出本場次即時偵測並持久化的紅旗，注入 SOAP 生成（安全關鍵：
            # 避免 LLM 自逐字稿重新推導時把 critical 急症 under-triage）。
            from app.models.red_flag_alert import RedFlagAlert

            rf_rows = (
                await db.execute(
                    select(RedFlagAlert).where(RedFlagAlert.session_id == session_id)
                )
            ).scalars().all()
            red_flags = [
                {
                    "severity": (
                        rf.severity.value
                        if hasattr(rf.severity, "value")
                        else str(rf.severity)
                    ),
                    "canonical_id": getattr(rf, "canonical_id", None),
                    "trigger_reason": rf.trigger_reason or "",
                    "suggested_actions": rf.suggested_actions or [],
                }
                for rf in rf_rows
            ]

            # 報告固定中文，不跟 session 語言（讀者是中文醫護）
            language = settings.SOAP_REPORT_LANGUAGE
            generator = SOAPGenerator(settings)
            soap_data = await generator.generate(
                transcript=transcript,
                patient_info=patient_info,
                chief_complaint=chief_complaint_text,
                language=language,
                symptom_id=symptom_id,
                red_flags=red_flags,
            )

            # 與 WS 路徑共用單一格式來源（app/utils/transcript.py），不可再 inline。
            from app.utils.transcript import format_raw_transcript

            raw_transcript = format_raw_transcript(transcript)

            report = (
                await db.execute(
                    select(SOAPReport).where(SOAPReport.session_id == session_id)
                )
            ).scalar_one_or_none()

            if report is None:
                # SO-4：可重試。報告列可能還在 API 行程的交易裡沒 commit，
                # 直接放棄等於把已經生成好的 SOAP 內容丟掉、列永遠停在
                # GENERATING。重試耗盡才由 `_run_task` 標 FAILED。
                logger.warning(
                    "場次 %s 找不到對應的報告記錄（可能尚未 commit），將重試",
                    session_id,
                )
                raise ReportRowNotReadyError(
                    f"soap_reports row for session {session_id} not found yet"
                )

            report.subjective = soap_data.get("subjective")
            report.objective = soap_data.get("objective")
            report.assessment = soap_data.get("assessment")
            report.plan = soap_data.get("plan")
            report.raw_transcript = raw_transcript
            report.summary = soap_data.get("summary", "")
            report.icd10_codes = soap_data.get("icd10_codes", [])
            # M3：把 validator 輸出的驗證旗標同步寫入，支援前端顯示「需醫師確認」
            report.icd10_verified = bool(soap_data.get("icd10_verified", False))
            report.ai_confidence_score = soap_data.get("confidence_score")
            report.language = language
            report.status = ReportStatus.GENERATED
            report.generated_at = utc_now()

            # M15 append-only：把剛寫入的首版內容存成不可變快照
            await db.flush()
            from app.services.report_service import ReportService

            await ReportService._snapshot_revision(
                db,
                report,
                ReportRevisionReason.INITIAL,
            )

            await db.commit()
            logger.info(
                "場次 %s SOAP 報告生成完成 | language=%s",
                session_id,
                language,
            )

            # H-8：報告真正完成（已 commit）才是 report_generated 的正確語意完成點。
            # 本任務在 Celery worker 行程，與持有 dashboard WS 連線的 API 行程不同，
            # 故走 Redis publish（由 API 行程的 subscriber 收到後本地 fan-out）。
            # payload 一律 camelCase 以對齊前端 ``ReportGeneratedPayload``。
            # publish 失敗已於 helper 內 swallow + log；此處再包一層確保絕不影響任務回傳。
            try:
                patient_name = ""
                patient = session_obj.patient
                if patient is not None:
                    patient_name = getattr(patient, "name", "") or ""
                await _publish_report_generated(
                    report_id=str(report.id),
                    session_id=session_id,
                    patient_name=patient_name,
                    status="generated",
                )
            except Exception as exc:  # noqa: BLE001 — 推播失敗不可影響任務結果
                logger.warning(
                    "場次 %s report_generated 推播失敗（非致命） | error=%s",
                    session_id,
                    exc,
                )

            # 病患語言版的病患面兩欄。獨立第三段交易，跑在主報告 commit 之後，
            # 任何失敗都只留 NULL（前端 fallback 回中文原文），不影響主報告。
            await _localize_patient_facing_best_effort(
                db,
                report=report,
                session_language=getattr(session_obj, "language", None),
                soap_data=soap_data,
                settings=settings,
            )

            # REPORT_READY 站內通知（負責醫師，未指派時 fan-out 給全體在職醫師）。
            # 獨立第二段交易，失敗不可影響已 commit 的報告與任務結果。
            try:
                from app.services.notification_service import NotificationService

                await NotificationService.notify_report_ready(
                    db, session_id=session_id, report_id=report.id
                )
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "場次 %s REPORT_READY 通知建立失敗（非致命） | error=%s",
                    session_id,
                    exc,
                )
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass

            return {
                "session_id": session_id,
                "status": "generated",
                "report_id": str(report.id),
            }

        except Exception as exc:
            # 這裡刻意**不**標 FAILED：本次失敗可能還有重試機會，先標 FAILED 會讓
            # 重試成功的場次留下錯誤狀態。標記時機交給 _run_task（重試耗盡才標）。
            logger.exception("場次 %s SOAP 報告生成失敗: %s", session_id, exc)
            await db.rollback()
            raise


def _flatten_patient_education(value) -> str:
    """把 `plan.patient_education` 併成單一字串（轉述層的輸入）。

    LLM 吐 list 是常態、吐 str 也發生過（`_validate_and_fill` 兩種都容忍），
    所以這裡兩種都吃。非字串項目照樣轉字串——`_sanitize_patient_facing_fields`
    刻意保留它們（不丟資料），這裡跟著保留。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if item is not None)
    if value is None:
        return ""
    return str(value)


async def _localize_patient_facing_best_effort(
    db,
    *,
    report,
    session_language,
    soap_data: dict,
    settings,
) -> None:
    """把病患面兩欄轉述成場次語言並寫入 `patient_facing_localized`。

    不變式 #12 不變：主報告與 `report.language` 仍固定 zh-TW；本欄是**附加**
    產物，只給病患自己的畫面用。

    設計上的三個「絕不」：
      - 絕不在主報告 commit 之前跑（多一次 LLM 呼叫 ＝ 多一個讓報告生不出來的理由）；
      - 絕不讓失敗往上冒（留 NULL，前端 fallback 回中文原文）；
      - 絕不在 rollback 後留下髒 session（失敗一律先 rollback 再返回）。

    zh-TW 場次直接 no-op：報告本來就是中文，沒有轉述的必要。
    """
    language = (session_language or "").strip()
    if not language or language == settings.SOAP_REPORT_LANGUAGE:
        return

    try:
        from app.pipelines.soap_generator import SOAPGenerator

        summary = soap_data.get("summary")
        education = _flatten_patient_education(
            (soap_data.get("plan") or {}).get("patient_education")
            if isinstance(soap_data.get("plan"), dict)
            else None
        )
        generator = SOAPGenerator(settings)
        localized = await generator.localize_patient_facing(
            summary=summary if isinstance(summary, str) else "",
            patient_education=education,
            target_language=language,
        )
        report.patient_facing_localized = localized
        await db.commit()
        logger.info(
            "場次 %s 病患語言版摘要已寫入 | language=%s",
            getattr(report, "session_id", None),
            language,
        )
    except Exception as exc:  # noqa: BLE001 — 附加欄位失敗不可影響主報告
        logger.warning(
            "病患語言版摘要生成失敗（非致命，欄位留 NULL）| language=%s error=%s",
            language,
            exc,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def _publish_report_generated(
    report_id: str,
    session_id: str,
    patient_name: str,
    status: str,
) -> None:
    """把 ``report_generated`` 事件 publish 到 Redis 儀表板頻道（跨行程）。

    在 Celery worker 行程觸發，無法用 in-memory 廣播觸及 API 行程的 WS 連線，
    故走 ``ConnectionManager.publish_dashboard_event``（內部已對 Redis 故障做韌性處理）。
    payload 鍵名為 camelCase 以對齊前端 ``ReportGeneratedPayload``。
    """
    from app.websocket.connection_manager import publish_dashboard_event

    await publish_dashboard_event(
        "report_generated",
        {
            "reportId": report_id,
            "sessionId": session_id,
            "patientName": patient_name or "",
            "status": status,
        },
    )


async def _update_report_status(db, session_id: str, status) -> None:
    """更新報告狀態"""
    from sqlalchemy import select

    from app.models.soap_report import SOAPReport

    report = (
        await db.execute(
            select(SOAPReport).where(SOAPReport.session_id == session_id)
        )
    ).scalar_one_or_none()
    if report is not None:
        report.status = status
