"""ChiefComplaint fallback 翻譯字典

問題背景：
DB 中 `chief_complaints` 的 `name_by_lang / description_by_lang / category_by_lang`
並非所有記錄都完整填入 5 國語言 —— 特別是：
  1) 管理員/醫師透過 admin UI 手動新增的自訂主訴（多半只填 zh-TW 與 en-US）
  2) 舊版 migration 或手動 SQL 插入的記錄
  3) 20260418_1900 seed 之前就存在、尚未被 migration 補譯過的 legacy 資料

當 session 語言是 ja/ko/vi、而記錄的 *_by_lang 沒有對應 key 時，
`pick()` 會 fallback 到 zh-TW legacy 值，導致前端出現中文卡片（例如韓文頁面
顯示「攝護腺相關症狀」、「泌尿道結石」等）。

本模組提供 **serialize 層的翻譯安全網**：以 canonical zh-TW 字串作為 key，
查詢對應的 5 語翻譯；若命中則覆蓋 pick 回來的 zh-TW legacy 值。
這樣即使 DB 沒有填 _by_lang，常見的泌尿科主訴仍能正確以目標語言顯示，
無需強制 admin UI 補齊翻譯、也避免每次新增記錄都要寫 migration。

使用方式：
  from app.utils.complaint_fallback_i18n import fallback_translate_name
  name = fallback_translate_name(legacy_zh_name, target_lang) or legacy_zh_name

設計原則：
  - 只覆蓋常見 canonical 詞；admin 自訂的奇異名稱保留原字串（不硬翻）
  - key 使用 legacy zh-TW 字串，與 DB 中 `name / category` 欄位一致
  - 值包含全 5 語（zh-TW / en-US / ja-JP / ko-KR / vi-VN），查得到就信任
  - 新增常見主訴不需 migration —— 本檔改動 + redeploy 即可生效
"""

from __future__ import annotations

from typing import Optional


# ── 分類翻譯表 ──────────────────────────────────────────────────
# key 是 DB 儲存的 legacy `category` 欄位值（通常是 zh-TW 原字），
# value 是各語言版本。管理員在 admin UI 新增 category 時會打 zh-TW，
# 所以以 zh-TW 為主鍵即可涵蓋絕大部分情境。
CATEGORY_FALLBACK_I18N: dict[str, dict[str, str]] = {
    # ── 20260418_1900 seed 既有 4 類（與其保持對齊） ──
    "排尿症狀": {
        "zh-TW": "排尿症狀",
        "en-US": "Urinary symptoms",
        "ja-JP": "排尿症状",
        "ko-KR": "배뇨 증상",
        "vi-VN": "Triệu chứng tiết niệu",
    },
    "疼痛": {
        "zh-TW": "疼痛",
        "en-US": "Pain",
        "ja-JP": "疼痛",
        "ko-KR": "통증",
        "vi-VN": "Đau",
    },
    # admin 另用的「疼痛症狀」—— 與 seed 的「疼痛」同類,讓兩組卡片合併為一個 section
    "疼痛症狀": {
        "zh-TW": "疼痛",
        "en-US": "Pain",
        "ja-JP": "疼痛",
        "ko-KR": "통증",
        "vi-VN": "Đau",
    },
    # admin 另用的「排尿」—— 歸為 seed 的「排尿症狀」同類
    "排尿": {
        "zh-TW": "排尿症狀",
        "en-US": "Urinary symptoms",
        "ja-JP": "排尿症状",
        "ko-KR": "배뇨 증상",
        "vi-VN": "Triệu chứng tiết niệu",
    },
    "檢查異常": {
        "zh-TW": "檢查異常",
        "en-US": "Abnormal findings",
        "ja-JP": "検査異常",
        "ko-KR": "검사 이상",
        "vi-VN": "Kết quả xét nghiệm bất thường",
    },
    "其他": {
        "zh-TW": "其他",
        "en-US": "Other",
        "ja-JP": "その他",
        "ko-KR": "기타",
        "vi-VN": "Khác",
    },
    # ── admin 手動新增常見類別 ──
    "攝護腺": {
        "zh-TW": "攝護腺",
        "en-US": "Prostate",
        "ja-JP": "前立腺",
        "ko-KR": "전립선",
        "vi-VN": "Tuyến tiền liệt",
    },
    "結石": {
        "zh-TW": "結石",
        "en-US": "Stones",
        "ja-JP": "結石",
        "ko-KR": "결석",
        "vi-VN": "Sỏi",
    },
    "感染": {
        "zh-TW": "感染",
        "en-US": "Infection",
        "ja-JP": "感染症",
        "ko-KR": "감염",
        "vi-VN": "Nhiễm trùng",
    },
    "腎臟": {
        "zh-TW": "腎臟",
        "en-US": "Kidney",
        "ja-JP": "腎臓",
        "ko-KR": "신장",
        "vi-VN": "Thận",
    },
    "膀胱": {
        "zh-TW": "膀胱",
        "en-US": "Bladder",
        "ja-JP": "膀胱",
        "ko-KR": "방광",
        "vi-VN": "Bàng quang",
    },
    "腫瘤": {
        "zh-TW": "腫瘤",
        "en-US": "Tumor / Cancer",
        "ja-JP": "腫瘍",
        "ko-KR": "종양",
        "vi-VN": "Khối u",
    },
    "性功能": {
        "zh-TW": "性功能",
        "en-US": "Sexual function",
        "ja-JP": "性機能",
        "ko-KR": "성기능",
        "vi-VN": "Chức năng tình dục",
    },
    "生殖": {
        "zh-TW": "生殖",
        "en-US": "Reproductive",
        "ja-JP": "生殖",
        "ko-KR": "생식",
        "vi-VN": "Sinh sản",
    },
    "女性泌尿": {
        "zh-TW": "女性泌尿",
        "en-US": "Female urology",
        "ja-JP": "女性泌尿器",
        "ko-KR": "여성 비뇨기",
        "vi-VN": "Tiết niệu nữ",
    },
}


# ── 主訴名稱翻譯表 ──────────────────────────────────────────────
# 覆蓋常見泌尿科主訴；key 是 legacy zh-TW `name`。
NAME_FALLBACK_I18N: dict[str, dict[str, str]] = {
    # ── 20260418_1900 seed 10 筆（與其對齊） ──
    "血尿": {
        "zh-TW": "血尿", "en-US": "Hematuria",
        "ja-JP": "血尿", "ko-KR": "혈뇨", "vi-VN": "Tiểu máu",
    },
    "頻尿": {
        "zh-TW": "頻尿", "en-US": "Frequent urination",
        "ja-JP": "頻尿", "ko-KR": "빈뇨", "vi-VN": "Tiểu nhiều lần",
    },
    "排尿疼痛": {
        "zh-TW": "排尿疼痛", "en-US": "Dysuria",
        "ja-JP": "排尿痛", "ko-KR": "배뇨통", "vi-VN": "Tiểu buốt",
    },
    "尿失禁": {
        "zh-TW": "尿失禁", "en-US": "Urinary incontinence",
        "ja-JP": "尿失禁", "ko-KR": "요실금", "vi-VN": "Tiểu không tự chủ",
    },
    "腰痛": {
        "zh-TW": "腰痛", "en-US": "Flank pain",
        "ja-JP": "腰痛", "ko-KR": "옆구리 통증", "vi-VN": "Đau hông",
    },
    # admin 變體：全形括號 + 腎臟區域
    "腰痛（腎臟區域）": {
        "zh-TW": "腰痛（腎臟區域）", "en-US": "Flank Pain / Renal Area Pain",
        "ja-JP": "腰痛（腎臓部）", "ko-KR": "옆구리 통증 (신장 부위)",
        "vi-VN": "Đau hông (vùng thận)",
    },
    "腰痛(腎臟區域)": {  # 半形括號版本
        "zh-TW": "腰痛（腎臟區域）", "en-US": "Flank Pain / Renal Area Pain",
        "ja-JP": "腰痛（腎臓部）", "ko-KR": "옆구리 통증 (신장 부위)",
        "vi-VN": "Đau hông (vùng thận)",
    },
    "下腹痛": {
        "zh-TW": "下腹痛", "en-US": "Lower abdominal pain",
        "ja-JP": "下腹部痛", "ko-KR": "하복부 통증", "vi-VN": "Đau bụng dưới",
    },
    "陰囊腫脹": {
        "zh-TW": "陰囊腫脹", "en-US": "Scrotal swelling",
        "ja-JP": "陰嚢腫脹", "ko-KR": "음낭 부종", "vi-VN": "Sưng bìu",
    },
    # admin 變體:疼痛或腫脹
    "陰囊疼痛或腫脹": {
        "zh-TW": "陰囊疼痛或腫脹", "en-US": "Scrotal Pain or Swelling",
        "ja-JP": "陰嚢痛または腫脹", "ko-KR": "음낭 통증 또는 부종",
        "vi-VN": "Đau hoặc sưng bìu",
    },
    "陰囊疼痛": {
        "zh-TW": "陰囊疼痛", "en-US": "Scrotal pain",
        "ja-JP": "陰嚢痛", "ko-KR": "음낭 통증",
        "vi-VN": "Đau bìu",
    },
    "背部不適": {
        "zh-TW": "背部不適", "en-US": "Back discomfort",
        "ja-JP": "背部不快感", "ko-KR": "허리 불편감",
        "vi-VN": "Khó chịu ở lưng",
    },
    "勃起功能障礙": {
        "zh-TW": "勃起功能障礙", "en-US": "Erectile dysfunction",
        "ja-JP": "勃起不全", "ko-KR": "발기부전", "vi-VN": "Rối loạn cương dương",
    },
    "PSA 異常": {
        "zh-TW": "PSA 異常", "en-US": "Elevated PSA",
        "ja-JP": "PSA 異常", "ko-KR": "PSA 이상", "vi-VN": "PSA bất thường",
    },
    "尿液檢查異常": {
        "zh-TW": "尿液檢查異常", "en-US": "Abnormal urinalysis",
        "ja-JP": "尿検査異常", "ko-KR": "소변 검사 이상", "vi-VN": "Xét nghiệm nước tiểu bất thường",
    },
    # ── 20260418_2300 backfill 3 筆 ──
    "排尿困難": {
        "zh-TW": "排尿困難", "en-US": "Dysuria / Difficulty urinating",
        "ja-JP": "排尿困難", "ko-KR": "배뇨 곤란", "vi-VN": "Khó tiểu",
    },
    "夜尿": {
        "zh-TW": "夜尿", "en-US": "Nocturia",
        "ja-JP": "夜間頻尿", "ko-KR": "야간뇨", "vi-VN": "Tiểu đêm",
    },
    "尿道灼熱感": {
        "zh-TW": "尿道灼熱感", "en-US": "Burning sensation during urination",
        "ja-JP": "排尿時の灼熱感", "ko-KR": "배뇨 시 작열감", "vi-VN": "Cảm giác rát khi đi tiểu",
    },
    # ── admin 手動新增常見主訴（從實際畫面補上） ──
    "攝護腺相關症狀": {
        "zh-TW": "攝護腺相關症狀", "en-US": "Prostate-related symptoms",
        "ja-JP": "前立腺関連症状", "ko-KR": "전립선 관련 증상", "vi-VN": "Triệu chứng liên quan đến tuyến tiền liệt",
    },
    "攝護腺肥大": {
        "zh-TW": "攝護腺肥大", "en-US": "Benign prostatic hyperplasia",
        "ja-JP": "前立腺肥大症", "ko-KR": "전립선 비대증", "vi-VN": "Phì đại tuyến tiền liệt",
    },
    "攝護腺炎": {
        "zh-TW": "攝護腺炎", "en-US": "Prostatitis",
        "ja-JP": "前立腺炎", "ko-KR": "전립선염", "vi-VN": "Viêm tuyến tiền liệt",
    },
    "泌尿道結石": {
        "zh-TW": "泌尿道結石", "en-US": "Urinary tract stones",
        "ja-JP": "尿路結石", "ko-KR": "요로 결석", "vi-VN": "Sỏi đường tiết niệu",
    },
    "腎結石": {
        "zh-TW": "腎結石", "en-US": "Kidney stones",
        "ja-JP": "腎結石", "ko-KR": "신장 결석", "vi-VN": "Sỏi thận",
    },
    "輸尿管結石": {
        "zh-TW": "輸尿管結石", "en-US": "Ureteral stones",
        "ja-JP": "尿管結石", "ko-KR": "요관 결석", "vi-VN": "Sỏi niệu quản",
    },
    "膀胱結石": {
        "zh-TW": "膀胱結石", "en-US": "Bladder stones",
        "ja-JP": "膀胱結石", "ko-KR": "방광 결석", "vi-VN": "Sỏi bàng quang",
    },
    "泌尿道感染": {
        "zh-TW": "泌尿道感染", "en-US": "Urinary tract infection",
        "ja-JP": "尿路感染症", "ko-KR": "요로 감염", "vi-VN": "Nhiễm trùng đường tiết niệu",
    },
    "膀胱炎": {
        "zh-TW": "膀胱炎", "en-US": "Cystitis",
        "ja-JP": "膀胱炎", "ko-KR": "방광염", "vi-VN": "Viêm bàng quang",
    },
    "腎盂腎炎": {
        "zh-TW": "腎盂腎炎", "en-US": "Pyelonephritis",
        "ja-JP": "腎盂腎炎", "ko-KR": "신우신염", "vi-VN": "Viêm đài bể thận",
    },
    "腎功能異常": {
        "zh-TW": "腎功能異常", "en-US": "Abnormal kidney function",
        "ja-JP": "腎機能異常", "ko-KR": "신장 기능 이상", "vi-VN": "Chức năng thận bất thường",
    },
    "急尿": {
        "zh-TW": "急尿", "en-US": "Urinary urgency",
        "ja-JP": "尿意切迫", "ko-KR": "요절박", "vi-VN": "Tiểu gấp",
    },
    "尿流細弱": {
        "zh-TW": "尿流細弱", "en-US": "Weak urinary stream",
        "ja-JP": "尿勢低下", "ko-KR": "소변 줄기 약화", "vi-VN": "Tia nước tiểu yếu",
    },
    "解不乾淨": {
        "zh-TW": "解不乾淨", "en-US": "Incomplete emptying",
        "ja-JP": "残尿感", "ko-KR": "잔뇨감", "vi-VN": "Cảm giác tiểu không hết",
    },
    "睪丸疼痛": {
        "zh-TW": "睪丸疼痛", "en-US": "Testicular pain",
        "ja-JP": "睾丸痛", "ko-KR": "고환 통증", "vi-VN": "Đau tinh hoàn",
    },
    "會陰痛": {
        "zh-TW": "會陰痛", "en-US": "Perineal pain",
        "ja-JP": "会陰痛", "ko-KR": "회음부 통증", "vi-VN": "Đau đáy chậu",
    },
    "血精": {
        "zh-TW": "血精", "en-US": "Hematospermia",
        "ja-JP": "血精液症", "ko-KR": "혈정액증", "vi-VN": "Xuất tinh ra máu",
    },
    "早洩": {
        "zh-TW": "早洩", "en-US": "Premature ejaculation",
        "ja-JP": "早漏", "ko-KR": "조루", "vi-VN": "Xuất tinh sớm",
    },
    "不孕": {
        "zh-TW": "不孕", "en-US": "Infertility",
        "ja-JP": "不妊症", "ko-KR": "불임", "vi-VN": "Vô sinh",
    },
}


# ── 常見 description 翻譯表（可選） ─────────────────────────────
# description 通常是管理員自由輸入，難以全面命中；只收錄少數固定句。
DESCRIPTION_FALLBACK_I18N: dict[str, dict[str, str]] = {
    "攝護腺肥大或發炎相關症狀，如排尿費力、尿流變細、殘尿感等": {
        "zh-TW": "攝護腺肥大或發炎相關症狀，如排尿費力、尿流變細、殘尿感等",
        "en-US": "Prostate enlargement or inflammation-related symptoms such as straining to urinate, weak stream, and residual urine sensation",
        "ja-JP": "前立腺肥大や炎症に関連する症状（排尿時のいきみ、尿勢低下、残尿感など）",
        "ko-KR": "전립선 비대나 염증 관련 증상(배뇨 시 힘주기, 약한 소변 줄기, 잔뇨감 등)",
        "vi-VN": "Các triệu chứng liên quan đến phì đại hoặc viêm tuyến tiền liệt như tiểu khó, tia yếu, cảm giác còn nước tiểu",
    },
    "腎臟、輸尿管或膀胱結石引起的症狀": {
        "zh-TW": "腎臟、輸尿管或膀胱結石引起的症狀",
        "en-US": "Symptoms caused by kidney, ureteral, or bladder stones",
        "ja-JP": "腎臓・尿管・膀胱の結石によって引き起こされる症状",
        "ko-KR": "신장, 요관 또는 방광 결석으로 인한 증상",
        "vi-VN": "Triệu chứng do sỏi thận, niệu quản hoặc bàng quang gây ra",
    },
    "泌尿道細菌感染，常見症狀包括頻尿、灼熱感、混濁尿液等": {
        "zh-TW": "泌尿道細菌感染，常見症狀包括頻尿、灼熱感、混濁尿液等",
        "en-US": "Bacterial infection of the urinary tract with symptoms including frequency, burning, and cloudy urine",
        "ja-JP": "尿路の細菌感染。頻尿、灼熱感、混濁尿などの症状を伴う",
        "ko-KR": "요로 세균 감염. 빈뇨, 작열감, 혼탁뇨 등의 증상이 동반됨",
        "vi-VN": "Nhiễm khuẩn đường tiết niệu, triệu chứng thường gặp gồm tiểu nhiều lần, rát, nước tiểu đục",
    },
    "腰部兩側或單側疼痛，可能與腎臟、輸尿管疾病相關": {
        "zh-TW": "腰部兩側或單側疼痛，可能與腎臟、輸尿管疾病相關",
        "en-US": "Bilateral or unilateral flank pain, possibly related to kidney or ureteral disease",
        "ja-JP": "両側または片側の腰痛で、腎臓や尿管の疾患と関連する可能性がある",
        "ko-KR": "양쪽 또는 한쪽 옆구리 통증으로 신장이나 요관 질환과 관련될 수 있음",
        "vi-VN": "Đau hông hai bên hoặc một bên, có thể liên quan đến bệnh lý thận hoặc niệu quản",
    },
    "陰囊區域疼痛或腫大，需排除睪丸扭轉等緊急狀況": {
        "zh-TW": "陰囊區域疼痛或腫大，需排除睪丸扭轉等緊急狀況",
        "en-US": "Pain or swelling in the scrotal area; must rule out emergencies such as testicular torsion",
        "ja-JP": "陰嚢部の痛みや腫脹で、精巣捻転などの緊急事態を除外する必要がある",
        "ko-KR": "음낭 부위의 통증이나 부종으로, 고환 염전 등 응급 상황을 배제해야 함",
        "vi-VN": "Đau hoặc sưng vùng bìu, cần loại trừ tình huống cấp cứu như xoắn tinh hoàn",
    },
}


def _lookup(table: dict[str, dict[str, str]], zh_key: Optional[str], target_lang: Optional[str]) -> Optional[str]:
    """以 legacy zh-TW 字串 + 目標語言查字典；找不到回 None。"""
    if not zh_key or not target_lang:
        return None
    entry = table.get(zh_key.strip())
    if not entry:
        return None
    value = entry.get(target_lang)
    return value if isinstance(value, str) and value else None


def fallback_translate_name(zh_name: Optional[str], target_lang: Optional[str]) -> Optional[str]:
    """查 name fallback 字典；命中回目標語言字串，否則 None。"""
    return _lookup(NAME_FALLBACK_I18N, zh_name, target_lang)


def fallback_translate_category(zh_category: Optional[str], target_lang: Optional[str]) -> Optional[str]:
    """查 category fallback 字典；命中回目標語言字串，否則 None。"""
    return _lookup(CATEGORY_FALLBACK_I18N, zh_category, target_lang)


def fallback_translate_description(zh_desc: Optional[str], target_lang: Optional[str]) -> Optional[str]:
    """查 description fallback 字典；命中回目標語言字串，否則 None。"""
    return _lookup(DESCRIPTION_FALLBACK_I18N, zh_desc, target_lang)
