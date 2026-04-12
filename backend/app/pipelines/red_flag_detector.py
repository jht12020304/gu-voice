"""
紅旗症狀偵測器 — 雙層偵測（規則比對 + 語意分析）

提供即時紅旗症狀偵測功能，結合關鍵字規則比對與 LLM 語意分析，
確保不遺漏任何可能需要緊急處理的危險症狀。
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings

logger = logging.getLogger(__name__)

# ── 語意分析系統提示詞 ───────────────────────────────────
_SEMANTIC_SYSTEM_PROMPT = """你是一位經驗豐富的泌尿科急診醫師，負責從病患對話中偵測需要緊急處理的紅旗症狀。

## 任務
分析以下病患描述，判斷是否包含需要緊急處理的紅旗症狀。

## 泌尿科紅旗症狀列表
- **Critical（危急）**: 無法排尿超過 8 小時、大量血尿伴血塊、睪丸突然劇烈疼痛（可能睪丸扭轉）、尿路感染合併敗血症症狀（高燒+寒顫+意識改變）
- **High（嚴重）**: 腎絞痛合併發燒、肉眼可見血尿、排尿困難合併腰痛發燒、不明原因體重急速下降、骨頭疼痛（可能骨轉移）
- **Medium（中等）**: 反覆尿路感染、持續性排尿困難逐漸惡化、PSA 指數異常升高

## 回覆格式
請以 JSON 格式回覆，包含一個 alerts 陣列。若無紅旗症狀，回傳空陣列。

```json
{
  "alerts": [
    {
      "severity": "critical|high|medium",
      "title": "簡短標題",
      "description": "詳細說明為何判定為紅旗症狀",
      "trigger_reason": "觸發原因（引用病患原文）",
      "suggested_actions": ["建議處置1", "建議處置2"]
    }
  ]
}
```

## 注意事項
- 寧可過度警示，也不要遺漏真正的危急症狀
- 務必引用病患原文作為觸發原因
- suggested_actions 應包含具體可行的建議"""


class RedFlagDetector:
    """
    雙層紅旗症狀偵測器

    同時執行規則比對（快速、確定性高）與語意分析（彈性、覆蓋面廣），
    合併去重後回傳紅旗警示列表。
    """

    def __init__(self, settings: Settings, db_session: AsyncSession) -> None:
        """
        初始化偵測器，載入資料庫中的啟用規則

        Args:
            settings: 應用程式設定實例
            db_session: 非同步資料庫 session
        """
        self._settings = settings
        self._db = db_session
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.OPENAI_MODEL_RED_FLAG  # gpt-4o-mini
        self._temperature = settings.OPENAI_TEMPERATURE_RED_FLAG  # 0.2
        self._rules: list[dict[str, Any]] = []
        self._rules_loaded = False

        logger.info(
            "RedFlagDetector 初始化 | model=%s, temperature=%.1f",
            self._model,
            self._temperature,
        )

    async def _load_rules(self) -> None:
        """從資料庫載入啟用中的紅旗規則"""
        if self._rules_loaded:
            return

        try:
            # 延遲匯入避免循環依賴
            from app.models.red_flag_rule import RedFlagRule

            stmt = select(RedFlagRule).where(RedFlagRule.is_active.is_(True))
            result = await self._db.execute(stmt)
            db_rules = result.scalars().all()

            self._rules = []
            for rule in db_rules:
                self._rules.append(
                    {
                        "id": str(rule.id),
                        "name": rule.name,
                        "severity": rule.severity,
                        "category": rule.category,
                        "keywords": rule.keywords if rule.keywords else [],
                        "regex_pattern": rule.regex_pattern,
                        "description": rule.description,
                        "suggested_actions": (
                            rule.suggested_actions if rule.suggested_actions else []
                        ),
                    }
                )

            self._rules_loaded = True
            logger.info("已載入 %d 條紅旗規則", len(self._rules))

        except Exception as exc:
            logger.error("載入紅旗規則失敗 | error=%s", str(exc), exc_info=True)
            # 載入失敗時使用內建規則作為備援
            self._rules = self._get_fallback_rules()
            self._rules_loaded = True

    @staticmethod
    def _get_fallback_rules() -> list[dict[str, Any]]:
        """內建備援紅旗規則（當資料庫不可用時使用）"""
        return [
            {
                "id": None,
                "name": "急性尿滯留",
                "severity": "critical",
                "category": "urinary_retention",
                "keywords": ["無法排尿", "尿不出來", "完全排不出", "尿滯留", "解不出小便"],
                "regex_pattern": r"(無法|不能|沒辦法|解不出).{0,5}(排尿|尿|小便)",
                "description": "病患可能出現急性尿滯留，需要緊急處理",
                "suggested_actions": ["立即通知醫師", "準備導尿管", "安排緊急就診"],
            },
            {
                "id": None,
                "name": "大量血尿",
                "severity": "critical",
                "category": "hematuria",
                "keywords": ["大量血尿", "血塊", "整個都是血", "血尿很多", "一大堆血"],
                "regex_pattern": r"(大量|嚴重|很多|整個).{0,5}(血尿|出血|血)",
                "description": "病患可能出現嚴重血尿，需評估出血原因",
                "suggested_actions": ["立即通知醫師", "監測生命徵象", "準備血液檢查"],
            },
            {
                "id": None,
                "name": "睪丸劇痛",
                "severity": "critical",
                "category": "testicular_torsion",
                "keywords": ["睪丸劇痛", "睪丸突然痛", "蛋蛋很痛", "突然睪丸"],
                "regex_pattern": r"(睪丸|蛋蛋|陰囊).{0,5}(劇痛|突然痛|非常痛|劇烈)",
                "description": "可能為睪丸扭轉，需要在 6 小時內處理以避免壞死",
                "suggested_actions": ["立即通知泌尿科醫師", "安排緊急超音波", "準備手術可能"],
            },
            {
                "id": None,
                "name": "尿路敗血症",
                "severity": "critical",
                "category": "urosepsis",
                "keywords": ["高燒", "寒顫", "意識不清", "發燒加排尿痛"],
                "regex_pattern": r"(發燒|高燒|寒顫).{0,10}(尿|排尿|泌尿|膀胱)",
                "description": "尿路感染合併全身性感染徵象，可能為尿路敗血症",
                "suggested_actions": ["立即通知醫師", "安排血液培養", "準備抗生素"],
            },
            {
                "id": None,
                "name": "肉眼血尿",
                "severity": "high",
                "category": "gross_hematuria",
                "keywords": ["肉眼血尿", "尿是紅色", "紅色的尿", "血尿", "尿裡有血"],
                "regex_pattern": r"(尿|小便).{0,5}(紅色|血|粉紅|褐色)",
                "description": "肉眼可見血尿，需進一步檢查排除惡性腫瘤",
                "suggested_actions": ["安排尿液檢查", "考慮膀胱鏡檢查", "通知主治醫師"],
            },
            {
                "id": None,
                "name": "腎絞痛合併發燒",
                "severity": "high",
                "category": "infected_stone",
                "keywords": ["腰痛", "腎臟痛", "側腹痛", "絞痛加發燒"],
                "regex_pattern": r"(腰|側腹|腎).{0,5}(痛|絞痛).{0,10}(燒|發燒|發熱)",
                "description": "腎結石合併感染，可能需要緊急引流",
                "suggested_actions": ["安排影像檢查", "抽血檢查發炎指數", "通知泌尿科醫師"],
            },
            {
                "id": None,
                "name": "不明原因體重下降",
                "severity": "high",
                "category": "weight_loss",
                "keywords": ["體重下降", "變瘦", "吃不下", "體重減輕"],
                "regex_pattern": r"(體重|瘦).{0,5}(下降|減輕|掉|變)",
                "description": "不明原因體重急速下降，需排除惡性腫瘤",
                "suggested_actions": ["安排全面檢查", "考慮腫瘤篩檢", "通知主治醫師"],
            },
        ]

    def _rule_based_detect(self, text: str) -> list[dict[str, Any]]:
        """
        規則比對層 — 使用關鍵字與正則表達式偵測紅旗症狀

        Args:
            text: 病患描述文字

        Returns:
            比對到的紅旗警示列表
        """
        alerts: list[dict[str, Any]] = []
        text_lower = text.lower()

        for rule in self._rules:
            matched = False
            trigger_reason = ""

            # 關鍵字比對
            for keyword in rule.get("keywords", []):
                if keyword in text_lower:
                    matched = True
                    trigger_reason = f"關鍵字比對：「{keyword}」"
                    break

            # 正則表達式比對（關鍵字未命中時）
            if not matched and rule.get("regex_pattern"):
                try:
                    match = re.search(rule["regex_pattern"], text, re.IGNORECASE)
                    if match:
                        matched = True
                        trigger_reason = f"模式比對：「{match.group()}」"
                except re.error as exc:
                    logger.warning(
                        "正則表達式無效 | rule=%s, pattern=%s, error=%s",
                        rule.get("name"),
                        rule.get("regex_pattern"),
                        str(exc),
                    )

            if matched:
                alerts.append(
                    {
                        "severity": rule.get("severity", "medium"),
                        "title": rule.get("name", "未知紅旗"),
                        "description": rule.get("description", ""),
                        "trigger_reason": trigger_reason,
                        "alert_type": "rule_based",
                        "suggested_actions": rule.get("suggested_actions", []),
                        "matched_rule_id": rule.get("id"),
                    }
                )

        return alerts

    async def _semantic_detect(
        self, text: str, session_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        語意分析層 — 使用 LLM 進行深層紅旗症狀偵測

        Args:
            text: 病患描述文字
            session_context: 場次上下文（主訴、病史等）

        Returns:
            LLM 偵測到的紅旗警示列表
        """
        session_id = session_context.get("session_id", "unknown")

        # 組合上下文資訊
        context_parts: list[str] = []
        if session_context.get("chief_complaint"):
            context_parts.append(f"主訴：{session_context['chief_complaint']}")
        if session_context.get("conversation_summary"):
            context_parts.append(f"對話摘要：{session_context['conversation_summary']}")

        context_text = "\n".join(context_parts) if context_parts else ""

        user_message = f"""## 病患背景
{context_text}

## 病患最新描述
{text}

請分析以上內容是否包含紅旗症狀，並以指定 JSON 格式回覆。"""

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SEMANTIC_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=self._temperature,
                max_completion_tokens=1024,
                response_format={"type": "json_object"},
            )

            raw_content = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_content)
            raw_alerts = parsed.get("alerts", [])

            alerts: list[dict[str, Any]] = []
            for alert in raw_alerts:
                alerts.append(
                    {
                        "severity": alert.get("severity", "medium"),
                        "title": alert.get("title", "語意偵測紅旗"),
                        "description": alert.get("description", ""),
                        "trigger_reason": alert.get("trigger_reason", ""),
                        "alert_type": "semantic",
                        "suggested_actions": alert.get("suggested_actions", []),
                        "matched_rule_id": None,
                    }
                )

            logger.info(
                "語意紅旗偵測完成 | session=%s, alerts_count=%d",
                session_id,
                len(alerts),
            )

            return alerts

        except json.JSONDecodeError as exc:
            logger.error(
                "語意偵測結果 JSON 解析失敗 | session=%s, error=%s",
                session_id,
                str(exc),
            )
            return []

        except Exception as exc:
            logger.error(
                "語意紅旗偵測失敗 | session=%s, error=%s",
                session_id,
                str(exc),
                exc_info=True,
            )
            return []

    async def detect(
        self, text: str, session_context: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        執行雙層紅旗偵測 — 同時運行規則比對與語意分析

        Args:
            text: 病患描述文字
            session_context: 場次上下文資訊

        Returns:
            去重合併後的紅旗警示列表，按嚴重度排序：
            [
                {
                    "severity": "critical|high|medium",
                    "title": str,
                    "description": str,
                    "trigger_reason": str,
                    "alert_type": "rule_based|semantic|combined",
                    "suggested_actions": list[str],
                    "matched_rule_id": uuid | None,
                }
            ]
        """
        session_id = session_context.get("session_id", "unknown")

        if not text or not text.strip():
            return []

        # 確保規則已載入
        await self._load_rules()

        # 並行執行雙層偵測
        rule_alerts, semantic_alerts = await asyncio.gather(
            asyncio.to_thread(self._rule_based_detect, text),
            self._semantic_detect(text, session_context),
            return_exceptions=True,
        )

        # 處理例外情況
        if isinstance(rule_alerts, BaseException):
            logger.error("規則比對層發生例外 | error=%s", str(rule_alerts))
            rule_alerts = []
        if isinstance(semantic_alerts, BaseException):
            logger.error("語意分析層發生例外 | error=%s", str(semantic_alerts))
            semantic_alerts = []

        # 合併並去重
        merged = self._merge_and_deduplicate(rule_alerts, semantic_alerts)

        # 按嚴重度排序：critical > high > medium
        severity_order = {"critical": 0, "high": 1, "medium": 2}
        merged.sort(key=lambda a: severity_order.get(a["severity"], 99))

        if merged:
            logger.warning(
                "偵測到紅旗症狀 | session=%s, count=%d, severities=%s",
                session_id,
                len(merged),
                [a["severity"] for a in merged],
            )

        return merged

    @staticmethod
    def _merge_and_deduplicate(
        rule_alerts: list[dict[str, Any]],
        semantic_alerts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        合併兩層偵測結果並去除重複項

        若同一標題在兩層都有命中，合併為 combined 類型並保留較高嚴重度。

        Args:
            rule_alerts: 規則比對結果
            semantic_alerts: 語意分析結果

        Returns:
            去重合併後的警示列表
        """
        merged: dict[str, dict[str, Any]] = {}
        severity_priority = {"critical": 0, "high": 1, "medium": 2}

        # 先加入規則比對結果
        for alert in rule_alerts:
            key = alert["title"].lower().strip()
            merged[key] = alert.copy()

        # 合併語意分析結果
        for alert in semantic_alerts:
            key = alert["title"].lower().strip()

            if key in merged:
                # 兩層都命中 → 合併為 combined
                existing = merged[key]
                existing["alert_type"] = "combined"

                # 取較高嚴重度
                if severity_priority.get(
                    alert["severity"], 99
                ) < severity_priority.get(existing["severity"], 99):
                    existing["severity"] = alert["severity"]

                # 合併觸發原因
                existing["trigger_reason"] = (
                    f"[規則] {existing['trigger_reason']} | "
                    f"[語意] {alert['trigger_reason']}"
                )

                # 合併建議處置（去重）
                existing_actions = set(existing.get("suggested_actions", []))
                for action in alert.get("suggested_actions", []):
                    existing_actions.add(action)
                existing["suggested_actions"] = list(existing_actions)

            else:
                merged[key] = alert.copy()

        return list(merged.values())
