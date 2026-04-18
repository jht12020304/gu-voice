"""chief_complaints 4 語 seed 資料 — TODO B1

Phase 3 i18n：seed 10 筆預設主訴，涵蓋 5 國語言
（zh-TW / en-US / ja-JP / ko-KR / vi-VN）。

為什麼用固定 UUID 而不是 gen_random_uuid()？
- Idempotent：migration 重跑時以 id 做 UPSERT，不會重複建立
- Downgrade 精準：只刪我們 seed 的 10 筆，不會誤刪 admin 新增的主訴
- 多環境可測：同一個 seed 在 dev / staging / prod 都是同一個 id

為什麼 legacy 欄位（name / name_en / description / category）也寫入？
- expand-migrate-contract 階段：舊讀取路徑（未走 `pick()`）還會 fallback 到 legacy
- 保險策略：即使 JSONB 解析失敗也能顯示繁中

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-04-18 19:00:00.000000+08:00
"""

import json
from typing import Sequence, Union

from alembic import op


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── 分類翻譯表（四種分類 × 5 語） ───────────────────────────────────
CATEGORY_I18N = {
    "urinary": {
        "zh-TW": "排尿症狀",
        "en-US": "Urinary symptoms",
        "ja-JP": "排尿症状",
        "ko-KR": "배뇨 증상",
        "vi-VN": "Triệu chứng tiết niệu",
    },
    "pain": {
        "zh-TW": "疼痛",
        "en-US": "Pain",
        "ja-JP": "疼痛",
        "ko-KR": "통증",
        "vi-VN": "Đau",
    },
    "abnormal": {
        "zh-TW": "檢查異常",
        "en-US": "Abnormal findings",
        "ja-JP": "検査異常",
        "ko-KR": "검사 이상",
        "vi-VN": "Kết quả xét nghiệm bất thường",
    },
    "other": {
        "zh-TW": "其他",
        "en-US": "Other",
        "ja-JP": "その他",
        "ko-KR": "기타",
        "vi-VN": "Khác",
    },
}


# ── 10 筆預設主訴（固定 UUID，冪等） ───────────────────────────────
# UUID namespace 用 00000000-cc01 ~ cc10 作為語意化的 suffix，方便人肉辨識
SEED_COMPLAINTS = [
    {
        "id": "00000000-0000-4000-8000-0000000000c1",
        "category_key": "urinary",
        "display_order": 1,
        "is_default": True,
        "name": {
            "zh-TW": "血尿",
            "en-US": "Hematuria",
            "ja-JP": "血尿",
            "ko-KR": "혈뇨",
            "vi-VN": "Tiểu máu",
        },
        "description": {
            "zh-TW": "尿液中帶血或呈紅色",
            "en-US": "Blood in urine or red-colored urine",
            "ja-JP": "尿に血が混じるか赤く見える",
            "ko-KR": "소변에 피가 섞이거나 붉게 보임",
            "vi-VN": "Nước tiểu lẫn máu hoặc có màu đỏ",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c2",
        "category_key": "urinary",
        "display_order": 2,
        "is_default": True,
        "name": {
            "zh-TW": "頻尿",
            "en-US": "Frequent urination",
            "ja-JP": "頻尿",
            "ko-KR": "빈뇨",
            "vi-VN": "Tiểu nhiều lần",
        },
        "description": {
            "zh-TW": "排尿次數異常增多",
            "en-US": "Abnormally frequent urination",
            "ja-JP": "排尿回数が異常に多い",
            "ko-KR": "배뇨 횟수가 비정상적으로 잦음",
            "vi-VN": "Đi tiểu nhiều lần bất thường",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c3",
        "category_key": "urinary",
        "display_order": 3,
        "is_default": True,
        "name": {
            "zh-TW": "排尿疼痛",
            "en-US": "Dysuria",
            "ja-JP": "排尿痛",
            "ko-KR": "배뇨통",
            "vi-VN": "Tiểu buốt",
        },
        "description": {
            "zh-TW": "排尿時感到疼痛或灼熱",
            "en-US": "Pain or burning during urination",
            "ja-JP": "排尿時に痛みや灼熱感がある",
            "ko-KR": "배뇨 시 통증이나 작열감",
            "vi-VN": "Đau hoặc rát khi đi tiểu",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c4",
        "category_key": "urinary",
        "display_order": 4,
        "is_default": False,
        "name": {
            "zh-TW": "尿失禁",
            "en-US": "Urinary incontinence",
            "ja-JP": "尿失禁",
            "ko-KR": "요실금",
            "vi-VN": "Tiểu không tự chủ",
        },
        "description": {
            "zh-TW": "無法控制排尿",
            "en-US": "Inability to control urination",
            "ja-JP": "排尿をコントロールできない",
            "ko-KR": "배뇨를 조절할 수 없음",
            "vi-VN": "Không kiểm soát được việc đi tiểu",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c5",
        "category_key": "pain",
        "display_order": 5,
        "is_default": True,
        "name": {
            "zh-TW": "腰痛",
            "en-US": "Flank pain",
            "ja-JP": "腰痛",
            "ko-KR": "옆구리 통증",
            "vi-VN": "Đau hông",
        },
        "description": {
            "zh-TW": "側腰部或後腰疼痛",
            "en-US": "Pain in the flank or lower back",
            "ja-JP": "脇腹または腰の痛み",
            "ko-KR": "옆구리 또는 허리 통증",
            "vi-VN": "Đau vùng hông hoặc thắt lưng",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c6",
        "category_key": "pain",
        "display_order": 6,
        "is_default": False,
        "name": {
            "zh-TW": "下腹痛",
            "en-US": "Lower abdominal pain",
            "ja-JP": "下腹部痛",
            "ko-KR": "하복부 통증",
            "vi-VN": "Đau bụng dưới",
        },
        "description": {
            "zh-TW": "下腹部疼痛或不適",
            "en-US": "Pain or discomfort in the lower abdomen",
            "ja-JP": "下腹部の痛みや不快感",
            "ko-KR": "하복부의 통증이나 불편감",
            "vi-VN": "Đau hoặc khó chịu vùng bụng dưới",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c7",
        "category_key": "other",
        "display_order": 7,
        "is_default": False,
        "name": {
            "zh-TW": "陰囊腫脹",
            "en-US": "Scrotal swelling",
            "ja-JP": "陰嚢腫脹",
            "ko-KR": "음낭 부종",
            "vi-VN": "Sưng bìu",
        },
        "description": {
            "zh-TW": "陰囊腫大或有硬塊",
            "en-US": "Swelling or lump in the scrotum",
            "ja-JP": "陰嚢の腫れやしこり",
            "ko-KR": "음낭 부종 또는 덩어리",
            "vi-VN": "Sưng hoặc có khối ở bìu",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c8",
        "category_key": "other",
        "display_order": 8,
        "is_default": False,
        "name": {
            "zh-TW": "勃起功能障礙",
            "en-US": "Erectile dysfunction",
            "ja-JP": "勃起不全",
            "ko-KR": "발기부전",
            "vi-VN": "Rối loạn cương dương",
        },
        "description": {
            "zh-TW": "勃起困難或無法維持",
            "en-US": "Difficulty achieving or maintaining erection",
            "ja-JP": "勃起が困難または維持できない",
            "ko-KR": "발기가 어렵거나 유지되지 않음",
            "vi-VN": "Khó cương cứng hoặc không duy trì được",
        },
    },
    {
        "id": "00000000-0000-4000-8000-0000000000c9",
        "category_key": "abnormal",
        "display_order": 9,
        "is_default": False,
        "name": {
            "zh-TW": "PSA 異常",
            "en-US": "Elevated PSA",
            "ja-JP": "PSA 異常",
            "ko-KR": "PSA 이상",
            "vi-VN": "PSA bất thường",
        },
        "description": {
            "zh-TW": "PSA 指數偏高需追蹤",
            "en-US": "Elevated PSA level requiring follow-up",
            "ja-JP": "PSA 値が高く追跡が必要",
            "ko-KR": "PSA 수치가 높아 추적 관찰이 필요",
            "vi-VN": "Chỉ số PSA tăng cao cần theo dõi",
        },
    },
    {
        "id": "00000000-0000-4000-8000-00000000000a",
        "category_key": "abnormal",
        "display_order": 10,
        "is_default": False,
        "name": {
            "zh-TW": "尿液檢查異常",
            "en-US": "Abnormal urinalysis",
            "ja-JP": "尿検査異常",
            "ko-KR": "소변 검사 이상",
            "vi-VN": "Xét nghiệm nước tiểu bất thường",
        },
        "description": {
            "zh-TW": "尿液常規檢查發現異常",
            "en-US": "Abnormal routine urinalysis findings",
            "ja-JP": "尿検査で異常が見つかった",
            "ko-KR": "소변 검사에서 이상 소견",
            "vi-VN": "Phát hiện bất thường trong xét nghiệm nước tiểu định kỳ",
        },
    },
]


def _seed_id_list() -> list[str]:
    return [c["id"] for c in SEED_COMPLAINTS]


def _sql_literal(text_value: str) -> str:
    """用 PostgreSQL 單引號 literal；內層單引號以雙引號逃逸。"""
    return "'" + text_value.replace("'", "''") + "'"


def _jsonb_literal(payload: dict) -> str:
    """把 dict 序列化成 PostgreSQL JSONB literal（'{...}'::jsonb）。
    使用 ensure_ascii=False 保留 Unicode，再轉成 SQL literal。
    """
    return _sql_literal(json.dumps(payload, ensure_ascii=False)) + "::jsonb"


def upgrade() -> None:
    # 先清掉舊的 seed（若先前曾手動插入過同 id 資料），保持 idempotent
    seed_ids = ", ".join(_sql_literal(sid) for sid in _seed_id_list())
    op.execute(f"DELETE FROM chief_complaints WHERE id IN ({seed_ids})")

    for entry in SEED_COMPLAINTS:
        category = CATEGORY_I18N[entry["category_key"]]
        values = ", ".join(
            [
                _sql_literal(entry["id"]),
                # legacy 欄位維持 zh-TW 以支援 pre-i18n 讀取路徑
                _sql_literal(entry["name"]["zh-TW"]),
                _sql_literal(entry["name"]["en-US"]),
                _sql_literal(entry["description"]["zh-TW"]),
                _sql_literal(category["zh-TW"]),
                # 權威多語 JSONB
                _jsonb_literal(entry["name"]),
                _jsonb_literal(entry["description"]),
                _jsonb_literal(category),
                "true" if entry["is_default"] else "false",
                "true",
                str(entry["display_order"]),
            ]
        )
        op.execute(
            f"""
            INSERT INTO chief_complaints (
                id, name, name_en, description, category,
                name_by_lang, description_by_lang, category_by_lang,
                is_default, is_active, display_order
            ) VALUES ({values})
            """
        )


def downgrade() -> None:
    seed_ids = ", ".join(_sql_literal(sid) for sid in _seed_id_list())
    op.execute(f"DELETE FROM chief_complaints WHERE id IN ({seed_ids})")
