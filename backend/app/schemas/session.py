"""問診場次相關 Pydantic Schema"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.models.enums import Gender, SessionStatus
from app.pipelines.prompts.shared import sanitize_for_prompt
from app.schemas.common import CursorPagination
from app.schemas.conversation import ConversationResponse
from app.utils.language import normalize_bcp47


class PromptSafeFreeText(BaseModel):
    """所有欄位皆為病患自由輸入、且會被插進 LLM system prompt 的 schema 基底。

    D-1：intake 四欄的每一筆（各 100 字）與主訴自填文字（200 字）原本零消毒直入
    system prompt。prompt 用 markdown 標題分區，多行值 + `##` 開頭在渲染後與真正的
    區段標題字面上無法區分（偽區段）。消毒放在**入口**（本層）與 **prompt 組裝層**
    （`app.pipelines.prompts.shared.sanitize_for_prompt` 的呼叫端）兩處：入口這層讓
    髒值不會落進 DB 的 `sessions.intake_data`，組裝層則涵蓋非本 schema 進來的路徑
    （`patients` 表舊資料、e2e 裸 JSON）。

    只摺疊空白 / 剝控制字元，臨床內容（「38度」「50%」「PSA 4.5」）原樣保留。
    """

    @field_validator("*", mode="after")
    @classmethod
    def _sanitize_free_text(cls, v: Any) -> Any:
        # bool（had_hospitalization / still_has）與非字串欄位原樣放行。
        return sanitize_for_prompt(v) if isinstance(v, str) else v


class SessionIntakeAllergyItem(PromptSafeFreeText):
    """本次問診 intake - 過敏史"""

    allergen: str = Field(..., min_length=1, max_length=100)
    reaction: Optional[str] = Field(None, max_length=200)
    severity: Optional[str] = Field(None, max_length=50)
    had_hospitalization: bool = False


class SessionIntakeMedicationItem(PromptSafeFreeText):
    """本次問診 intake - 目前用藥"""

    name: str = Field(..., min_length=1, max_length=100)
    frequency: Optional[str] = Field(None, max_length=100)


class SessionIntakeMedicalHistoryItem(PromptSafeFreeText):
    """本次問診 intake - 過去病史"""

    condition: str = Field(..., min_length=1, max_length=100)
    years_ago: Optional[str] = Field(None, max_length=50)
    still_has: bool = True


class SessionIntakeFamilyHistoryItem(PromptSafeFreeText):
    """本次問診 intake - 家族病史"""

    relation: str = Field(..., min_length=1, max_length=50)
    condition: str = Field(..., min_length=1, max_length=100)


class SessionIntake(BaseModel):
    """本次問診 intake snapshot"""

    no_known_allergies: bool = False
    allergies: list[SessionIntakeAllergyItem] = Field(default_factory=list)
    no_current_medications: bool = False
    current_medications: list[SessionIntakeMedicationItem] = Field(default_factory=list)
    no_past_medical_history: bool = False
    medical_history: list[SessionIntakeMedicalHistoryItem] = Field(default_factory=list)
    # `no_family_history` 與其他三個 no_* 旗標同語意：病患明確表示「沒有家族史」。
    # 缺這一欄時 patient_context.build_patient_info 的對應分支是死碼，家族史只能
    # 分辨「有填」與「沒填」，分不出「已表明沒有」→ §3b 必問的泌尿癌家族史會被
    # 重問一次。兩個前端目前都還沒有這個勾選框（送不出這個 key），預設 False
    # 等同於現行行為；e2e driver 送裸 JSON，可直接帶 snake_case 這個 key。
    no_family_history: bool = False
    family_history: list[SessionIntakeFamilyHistoryItem] = Field(default_factory=list)


class PatientInfoPayload(BaseModel):
    """場次建立時隨附的病患資料（供後端 get_or_create）"""

    name: str = Field(..., min_length=1, max_length=100)
    gender: Gender
    date_of_birth: date = Field(..., alias="dateOfBirth")
    phone: Optional[str] = Field(None, max_length=20)

    model_config = ConfigDict(populate_by_name=True)


class SessionCreate(BaseModel):
    """建立場次"""

    patient_id: Optional[UUID] = Field(None, alias="patientId")
    chief_complaint_id: UUID = Field(..., alias="chiefComplaintId")
    chief_complaint_text: Optional[str] = Field(
        None, max_length=200, alias="chiefComplaintText"
    )
    # Optional：未指定時由 router 依 user.preferred_language → Accept-Language →
    # settings default 推算（app.utils.language.resolve_language）。
    # 若顯式指定，必須落在 settings.SUPPORTED_LANGUAGES，否則 422。
    language: Optional[str] = Field(None, max_length=10)
    intake: Optional[SessionIntake] = None
    patient_info: Optional[PatientInfoPayload] = Field(None, alias="patientInfo")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("chief_complaint_text")
    @classmethod
    def _sanitize_chief_complaint_text(cls, v: Optional[str]) -> Optional[str]:
        """D-1：主訴自填文字（200 字、可多行）是最直接的偽區段載體。

        它被 `build_system_prompt` 插在 `## 主訴` 標題的**下一行行首**，多行值的
        第二行若以 `##` 起頭，渲染後與真正的區段標題無法區分。消毒只摺疊空白、
        剝掉控制字元與開頭的 `#`，不動臨床字面（長度上限仍由 max_length 把關）。
        消毒後變空字串時回 None——與「沒填」同語意，讓 router 走 ChiefComplaint 名稱。
        """
        if v is None:
            return None
        cleaned = sanitize_for_prompt(v)
        return cleaned or None

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: Optional[str]) -> Optional[str]:
        """白名單驗證 + BCP-47 大小寫正規化（zh-tw → zh-TW）。"""
        if v is None or v == "":
            return None
        normalized = normalize_bcp47(v)
        if normalized is None or normalized not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"language must be one of: {', '.join(settings.SUPPORTED_LANGUAGES)}"
            )
        return normalized


class SessionUpdateStatus(BaseModel):
    """更新場次狀態"""
    status: SessionStatus
    reason: Optional[str] = None


class SessionEndForLanguageSwitch(BaseModel):
    """
    M16：對話中切語言時用此端點結束 session。
    前端在 LanguageSwitcher 偵測到 active session 時先開 modal 取使用者
    同意，確認後帶 `to_language` 呼叫；server 會結束 session 並寫
    audit_log（action=language_switch_end_session）。
    """
    to_language: str = Field(..., min_length=2, max_length=10, alias="toLanguage")
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("to_language")
    @classmethod
    def _validate_to_language(cls, v: str) -> str:
        normalized = normalize_bcp47(v)
        if normalized is None or normalized not in settings.SUPPORTED_LANGUAGES:
            raise ValueError(
                f"to_language must be one of: {', '.join(settings.SUPPORTED_LANGUAGES)}"
            )
        return normalized


class SessionResponse(BaseModel):
    """場次回應"""
    id: UUID
    patient_id: UUID
    patient_name: Optional[str] = None
    doctor_id: Optional[UUID] = None
    chief_complaint_id: UUID
    chief_complaint_text: Optional[str] = None
    status: SessionStatus
    red_flag: bool
    red_flag_reason: Optional[str] = None
    language: str
    intake: Optional[SessionIntake] = Field(default=None, validation_alias="intake_data")
    intake_completed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _populate_patient_name(cls, data: Any) -> Any:
        # 當從 ORM 物件載入時，若 patient 關聯已被 eager-load，
        # 則把 patient.name 複製到 patient_name 屬性上，
        # 讓 from_attributes=True 的 pydantic 能讀到。
        if data is None or isinstance(data, dict):
            return data
        existing = getattr(data, "patient_name", None)
        if existing:
            return data
        try:
            patient = data.__dict__.get("patient") if hasattr(data, "__dict__") else None
        except Exception:
            patient = None
        if patient is None:
            return data
        name = getattr(patient, "name", None)
        if name:
            try:
                data.patient_name = name
            except Exception:
                pass
        return data


class SessionDetailResponse(SessionResponse):
    """場次詳細回應（含對話紀錄）"""
    conversations: list[ConversationResponse] = []


class SessionListResponse(BaseModel):
    """場次列表回應"""
    data: list[SessionResponse]
    pagination: CursorPagination


class SessionAssignRequest(BaseModel):
    """指派醫師"""
    doctor_id: UUID


class SessionStatusResponse(BaseModel):
    """狀態更新回應"""
    id: UUID
    status: SessionStatus
    previous_status: Optional[SessionStatus] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    """對話紀錄列表回應"""
    data: list[ConversationResponse]
    pagination: CursorPagination


# 別名（供 router 匯入相容）
SessionDetail = SessionDetailResponse
SessionStatusUpdate = SessionUpdateStatus
