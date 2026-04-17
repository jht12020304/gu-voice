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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.openai_client import call_with_retry, get_openai_client
from app.pipelines.prompts.shared import (
    URO_RED_FLAGS,
    render_red_flag_titles_for_prompt,
    render_red_flags_by_severity,
)

logger = logging.getLogger(__name__)

# ── 語意分析系統提示詞 ───────────────────────────────────
# NOTE: Critical/High/Medium 情境清單與 title 對齊段落都從 shared.URO_RED_FLAGS 動態渲染,
# 避免語意層 prompt 與 _get_fallback_rules 及 DB 規則漂移(P2-E 修復)。
_SEMANTIC_SYSTEM_PROMPT = f"""你是具急診與泌尿科分流經驗的臨床安全偵測助理，任務是從病患對話中辨識需要高度警覺的紅旗症狀，協助數位問診系統提早提醒醫護優先處理。

## 你的角色
- 你是紅旗偵測器，不是最終診斷醫師。
- 目標是辨識「可能需要優先處理、急診評估、或立即提醒醫師」的訊號。
- 不可憑空推測未被對話支持的紅旗。
- 若資訊不足但高度可疑,請仍輸出該紅旗,但嚴重度降一階並在 description 中註明資訊不足。
- 若沒有足夠證據,寧可回 {{"alerts": []}},也不要誤報。

## 需重點辨識的泌尿科高風險情境（系統內建目錄）
{render_red_flags_by_severity()}

### 其他 Critical 情境（不限於上方內建目錄）
- 敗血症/嚴重感染：發燒合併寒顫、發燒合併側腹痛/腰痛、意識改變或虛弱低血壓描述
- 急性尿路阻塞：完全尿不出來、明顯脹痛且無法排尿、已知攝護腺問題急遽惡化
- 神經學警訊：會陰麻木、下肢無力合併新發尿失禁或背痛（疑馬尾症候群/脊髓壓迫）

### 其他 High 情境
- 排尿困難合併腰痛發燒
- 劇烈側腹痛放射至鼠蹊/下腹、合併噁心嘔吐（疑腎結石併感染或阻塞）
- 骨頭疼痛（可能骨轉移）
- 持續嘔吐無法進食喝水、明顯虛弱
- 高齡、吸菸史或泌尿癌症病史合併上述任一症狀（僅在對話有提及時）

### Medium（中等，需補問與人工複核）
- 反覆尿路感染
- 持續性排尿困難逐漸惡化
- 年長男性下泌尿道症狀急遽變化
- PSA 指數異常升高（若有提及）

## 判斷原則
1. 只依據對話內容判斷，不可外推至未被病人明確陳述的症狀。
2. 若症狀為病人明確陳述，可視為證據；模糊描述（「有點不舒服」）不足以直接判為高風險，除非有其他佐證。
3. 若同時出現多個中度警訊，整體風險可上修一階。
4. 若為高度可疑但資訊不足，降一階處理為 medium，並在 description 中註明需補問。
5. 寧可過度警示真正的危急情境，也不要遺漏；但不可把普通下泌尿道症狀一律判為紅旗。
6. 不可因單一模糊詞就升到 critical。

## title 命名對齊（重要，影響系統去重）
本系統的規則比對層會先偵測以下內建紅旗；若你的語意判斷落在同一類情境，**請使用完全相同的 title 名稱**，讓系統可以把規則層與語意層的命中合併為一筆：
{render_red_flag_titles_for_prompt()}

若屬於上述清單以外的新紅旗類型，請自行命名但保持簡潔明確（例如「急性副睪炎可能」）。

## 輸出格式
嚴格以下列 JSON 回覆，禁止輸出 markdown、程式碼區塊、或 JSON 以外任何文字。若未偵測到紅旗，請回 {{"alerts": []}}。

{{
  "alerts": [
    {{
      "severity": "critical|high|medium",
      "title": "簡短標題（同類情境請對齊上方內建名稱）",
      "description": "詳細說明為何判定為紅旗，包含臨床推理",
      "trigger_reason": "直接引用病患原文作為觸發根據",
      "suggested_actions": ["建議處置1", "建議處置2"]
    }}
  ]
}}

## 欄位硬性限制
- severity **只能是 "critical"、"high"、"medium"** 三者之一；禁用 "low"、"none"、"possible"、"warning"、"info" 等字串（會被系統排到最後或無法顯示）。
- title 為單一字串；若與內建規則同類情境請完全使用上方列出的名稱（影響去重合併）。
- description 為單一字串，說明臨床推理與嚴重度判定依據。
- trigger_reason 為**單一字串**，必須直接引用病患對話原文（可加引號），不可留空、不可寫「未提供」、不可寫成陣列。
- suggested_actions 為**字串陣列 list[string]**，每項為一個具體可行的建議動作；不得為單一字串或物件陣列（會觸發後端合併錯誤）。
- alerts 為陣列，即使只有一筆也必須放入陣列；若無紅旗請回空陣列 []。
- **不可輸出** alert_type、matched_rule_id、risk_level、has_red_flag、triage_recommendation、evidence、reasoning、recommended_action、label 等額外欄位；這些會被系統端忽略或覆寫，只會浪費 tokens 並可能觸發解析錯誤。
"""


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
        self._client = get_openai_client()
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
        """
        內建備援紅旗規則（當資料庫不可用時使用）

        直接從 shared.URO_RED_FLAGS 產生,保持與語意層 prompt 的知識庫
        完全一致,避免兩邊漂移(P2-E)。這裡不帶 regex_pattern,因為 shared
        catalogue 是純關鍵字;如需 regex 匹配仍應由 DB 規則主導。
        """
        return [
            {
                "id": None,
                "name": flag["title"],
                "severity": flag["severity"],
                "category": flag["title"],  # 暫用 title 當 category
                "keywords": list(flag["triggers"]),
                "regex_pattern": None,
                "description": flag["description"],
                "suggested_actions": list(flag["suggested_actions"]),
            }
            for flag in URO_RED_FLAGS
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
            response = await call_with_retry(
                lambda: self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": _SEMANTIC_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=self._temperature,
                    max_completion_tokens=1024,
                    response_format={"type": "json_object"},
                )
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
