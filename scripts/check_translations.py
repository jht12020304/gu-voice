#!/usr/bin/env python3
"""Translation staleness checker for UroSense i18n.

兩個獨立的檢查:

1. Coverage — 比對各 locale / namespace 的 JSON key 覆蓋率,以 zh-TW 為
   reference(source of truth)。
2. Mirror — 同一份 i18n JSON 在倉庫裡有多份拷貝(`frontend/public/locales`
   是 vite build 鏡像、`flutter_app/assets/locales` 是 Flutter 的 asset),
   這些鏡像沒有任何工具強制同步,靠人手維持。這裡比對「檔案集合」與
   「每個檔的 key 集合」是否與 source of truth 一致。

支援 human-readable、JSON 與 GitHub Actions Markdown summary 三種輸出,
並以 exit code 反映檢查結果,供 CI 掛鉤。

Exit code 慣例(CI 依賴,勿改):
    0 = 全數通過
    1 = 檢查不通過(active locale 低於閾值,或 mirror 有缺檔/缺 key)
    2 = 無法執行(reference locale 目錄不存在或沒有任何 namespace)

使用方式:
    python scripts/check_translations.py
    python scripts/check_translations.py --json
    python scripts/check_translations.py --github-summary
    python scripts/check_translations.py --threshold 90
    python scripts/check_translations.py --mirrors ""          # 只跑 coverage

設計備忘:
- 盡量用 Python 3.12 標準庫(argparse / json / pathlib),不引入外部依賴。
- beta locale 預設為 `ja-JP,ko-KR,vi-VN`,這些語言只檢查 common.json,其他
  namespace 缺 key 不計入 fail 判定(因為有 fallbackLng chain)。同一條規則
  也套用在 mirror 檢查上,beta 的非 common namespace 只 WARN 不 fail,兩邊
  的 skip 行為保持一致。
- reference 的多餘 key 不會被當成 missing,但會在 extra_keys 欄位列出,
  方便 PR reviewer 發現 typo。mirror 檢查沿用同一個不對稱慣例:mirror
  「缺」檔案或 key 才 fail,「多」出來的只 WARN — 因為 Flutter 有自己獨立
  的畫面(例如 PNG 匯出、主訴顯示順序),那些 key 本來就只存在於 Flutter 側。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_LOCALES_DIR = "frontend/src/i18n/locales"
DEFAULT_REFERENCE = "zh-TW"
DEFAULT_THRESHOLD = 95.0
DEFAULT_BETA_LOCALES = "ja-JP,ko-KR,vi-VN"
BETA_ALLOWED_NAMESPACES = {"common"}  # beta locale 只檢查這些 namespace

# 必須與 DEFAULT_LOCALES_DIR 逐檔同步的拷貝。前者是 vite build 產出的鏡像,
# 後者是 Flutter 的 asset;兩者都沒有工具強制同步,所以在這裡把它擋住。
DEFAULT_MIRROR_DIRS = (
    "frontend/public/locales",
    "flutter_app/assets/locales",
)


# ---------------------------------------------------------------------------
# Key extraction helpers
# ---------------------------------------------------------------------------


def flatten_keys(data: Any, prefix: str = "") -> set[str]:
    """把巢狀 dict 攤平成以 `.` 串接的 leaf key 集合。

    - `{a: {b: "x"}}` -> `{"a.b"}`
    - list / primitive 視為 leaf,不再往下展開
    - `{}` 空物件視為 leaf(用 prefix 自身表示)
    """
    keys: set[str] = set()
    if isinstance(data, dict):
        if not data and prefix:
            keys.add(prefix)
            return keys
        for k, v in data.items():
            child_prefix = f"{prefix}.{k}" if prefix else k
            keys |= flatten_keys(v, child_prefix)
    else:
        if prefix:
            keys.add(prefix)
    return keys


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def flatten_file_keys(path: Path) -> tuple[set[str], str | None]:
    """讀檔並攤平 key,壞掉的 JSON 回傳錯誤訊息而不是往外炸。

    mirror 檢查會掃到 coverage 檢查不會碰的檔(reference 沒有的 namespace),
    這些檔如果壞了應該當成一筆 finding 報出來,而不是讓整個腳本 traceback。
    """
    try:
        return flatten_keys(load_json(path)), None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        return set(), f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class NamespaceReport:
    namespace: str
    reference_count: int
    target_count: int
    missing_keys: list[str]
    extra_keys: list[str]
    skipped: bool = False  # beta namespace 直接跳過計入
    target_exists: bool = True

    @property
    def coverage(self) -> float:
        if self.reference_count == 0:
            return 100.0
        present = self.reference_count - len(self.missing_keys)
        return round(present * 100.0 / self.reference_count, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": self.namespace,
            "reference_count": self.reference_count,
            "target_count": self.target_count,
            "missing_keys": sorted(self.missing_keys),
            "extra_keys": sorted(self.extra_keys),
            "coverage_pct": self.coverage,
            "skipped": self.skipped,
            "target_exists": self.target_exists,
        }


@dataclass
class LocaleReport:
    locale: str
    is_beta: bool
    namespaces: list[NamespaceReport] = field(default_factory=list)

    @property
    def counted_namespaces(self) -> list[NamespaceReport]:
        return [ns for ns in self.namespaces if not ns.skipped]

    @property
    def total_reference(self) -> int:
        return sum(ns.reference_count for ns in self.counted_namespaces)

    @property
    def total_missing(self) -> int:
        return sum(len(ns.missing_keys) for ns in self.counted_namespaces)

    @property
    def coverage(self) -> float:
        ref = self.total_reference
        if ref == 0:
            return 100.0
        present = ref - self.total_missing
        return round(present * 100.0 / ref, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "is_beta": self.is_beta,
            "coverage_pct": self.coverage,
            "reference_total": self.total_reference,
            "missing_total": self.total_missing,
            "namespaces": [ns.to_dict() for ns in self.namespaces],
        }


@dataclass
class MirrorFileDrift:
    """一個 (locale, namespace) 檔案在 mirror 與 source 之間的差異。"""

    locale: str
    namespace: str
    missing_file: bool = False  # source 有、mirror 沒有
    extra_file: bool = False  # mirror 有、source 沒有
    missing_keys: list[str] = field(default_factory=list)
    extra_keys: list[str] = field(default_factory=list)
    parse_error: str | None = None
    skipped: bool = False  # beta 的非 common namespace:報但不影響 exit code

    @property
    def is_failure(self) -> bool:
        # 「缺」才 fail、「多」只 WARN,和 coverage 檢查對 extra_keys 的處理一致。
        if self.skipped:
            return False
        return bool(self.missing_file or self.missing_keys or self.parse_error)

    @property
    def label(self) -> str:
        return f"{self.locale}/{self.namespace}.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "namespace": self.namespace,
            "missing_file": self.missing_file,
            "extra_file": self.extra_file,
            "missing_keys": self.missing_keys,
            "extra_keys": self.extra_keys,
            "parse_error": self.parse_error,
            "skipped": self.skipped,
            "is_failure": self.is_failure,
        }


@dataclass
class MirrorReport:
    """一份 mirror 目錄相對 source of truth 的比對結果。"""

    path: str
    source_path: str
    root_missing: bool = False
    file_count: int = 0
    drifts: list[MirrorFileDrift] = field(default_factory=list)  # 只收有差異的

    @property
    def failures(self) -> list[MirrorFileDrift]:
        return [d for d in self.drifts if d.is_failure]

    @property
    def warnings(self) -> list[MirrorFileDrift]:
        return [d for d in self.drifts if not d.is_failure]

    @property
    def ok(self) -> bool:
        return not self.root_missing and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source_path": self.source_path,
            "root_missing": self.root_missing,
            "file_count": self.file_count,
            "ok": self.ok,
            "failure_count": len(self.failures),
            "warning_count": len(self.warnings),
            "drifts": [d.to_dict() for d in self.drifts],
        }


@dataclass
class FullReport:
    reference: str
    threshold: float
    beta_locales: list[str]
    locales: list[LocaleReport] = field(default_factory=list)
    mirrors: list[MirrorReport] = field(default_factory=list)

    def failed_locales(self) -> list[LocaleReport]:
        failed = []
        for loc in self.locales:
            if loc.locale == self.reference:
                continue
            if loc.is_beta:
                continue  # beta 不綁閾值
            if loc.coverage < self.threshold:
                failed.append(loc)
        return failed

    def failed_mirrors(self) -> list[MirrorReport]:
        return [m for m in self.mirrors if not m.ok]

    @property
    def ok(self) -> bool:
        return not self.failed_locales() and not self.failed_mirrors()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "threshold_pct": self.threshold,
            "beta_locales": list(self.beta_locales),
            "locales": [loc.to_dict() for loc in self.locales],
            "failed_locales": [loc.locale for loc in self.failed_locales()],
            "mirrors": [m.to_dict() for m in self.mirrors],
            "failed_mirrors": [m.path for m in self.failed_mirrors()],
            "ok": self.ok,
        }


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------


def discover_namespaces(reference_dir: Path) -> list[str]:
    if not reference_dir.exists():
        raise FileNotFoundError(
            f"Reference locale directory not found: {reference_dir}"
        )
    namespaces = sorted(p.stem for p in reference_dir.glob("*.json"))
    if not namespaces:
        raise FileNotFoundError(
            f"No JSON namespaces found in reference locale: {reference_dir}"
        )
    return namespaces


def discover_target_locales(
    locales_dir: Path, reference: str
) -> list[str]:
    if not locales_dir.exists():
        raise FileNotFoundError(f"Locales dir not found: {locales_dir}")
    locales = sorted(
        p.name
        for p in locales_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    # reference 放最前面以確保輸出順序穩定
    if reference in locales:
        locales.remove(reference)
        locales.insert(0, reference)
    return locales


def build_namespace_report(
    namespace: str,
    reference_keys: set[str],
    target_path: Path,
    skipped: bool,
) -> NamespaceReport:
    target_exists = target_path.exists()
    if not target_exists:
        return NamespaceReport(
            namespace=namespace,
            reference_count=len(reference_keys),
            target_count=0,
            missing_keys=sorted(reference_keys),
            extra_keys=[],
            skipped=skipped,
            target_exists=False,
        )
    target_data = load_json(target_path)
    target_keys = flatten_keys(target_data)
    missing = sorted(reference_keys - target_keys)
    extra = sorted(target_keys - reference_keys)
    return NamespaceReport(
        namespace=namespace,
        reference_count=len(reference_keys),
        target_count=len(target_keys),
        missing_keys=missing,
        extra_keys=extra,
        skipped=skipped,
        target_exists=True,
    )


def scan_locale_files(root: Path) -> dict[tuple[str, str], Path]:
    """掃出 `<locale>/<namespace>.json`,回傳 (locale, namespace) -> path。"""
    found: dict[tuple[str, str], Path] = {}
    if not root.is_dir():
        return found
    for locale_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if locale_dir.name.startswith("."):
            continue
        for json_path in sorted(locale_dir.glob("*.json")):
            found[(locale_dir.name, json_path.stem)] = json_path
    return found


def build_mirror_report(
    source_dir: Path,
    mirror_dir: Path,
    display_path: str,
    beta_set: set[str],
) -> MirrorReport:
    """比對 mirror 目錄與 source of truth 的檔案集合與各檔 key 集合。"""
    source_files = scan_locale_files(source_dir)
    report = MirrorReport(
        path=display_path,
        source_path=str(source_dir),
        root_missing=not mirror_dir.is_dir(),
        file_count=len(source_files),
    )
    if report.root_missing:
        # 整個目錄不見了就不必逐檔報,root_missing 已經足以說明問題。
        return report

    mirror_files = scan_locale_files(mirror_dir)
    for locale, namespace in sorted(set(source_files) | set(mirror_files)):
        # beta locale 的非 common namespace 依 fallbackLng 慣例只 WARN。
        skipped = locale in beta_set and namespace not in BETA_ALLOWED_NAMESPACES
        src_path = source_files.get((locale, namespace))
        mir_path = mirror_files.get((locale, namespace))

        if src_path is None:
            report.drifts.append(
                MirrorFileDrift(
                    locale=locale,
                    namespace=namespace,
                    extra_file=True,
                    skipped=skipped,
                )
            )
            continue
        if mir_path is None:
            report.drifts.append(
                MirrorFileDrift(
                    locale=locale,
                    namespace=namespace,
                    missing_file=True,
                    skipped=skipped,
                )
            )
            continue

        src_keys, src_err = flatten_file_keys(src_path)
        mir_keys, mir_err = flatten_file_keys(mir_path)
        errors = [
            f"source {locale}/{namespace}.json — {src_err}" if src_err else "",
            f"mirror {locale}/{namespace}.json — {mir_err}" if mir_err else "",
        ]
        parse_error = "; ".join(e for e in errors if e) or None
        missing = sorted(src_keys - mir_keys)
        extra = sorted(mir_keys - src_keys)
        if not (missing or extra or parse_error):
            continue
        report.drifts.append(
            MirrorFileDrift(
                locale=locale,
                namespace=namespace,
                missing_keys=missing,
                extra_keys=extra,
                parse_error=parse_error,
                skipped=skipped,
            )
        )
    return report


def check_translations(
    locales_dir: Path,
    reference: str,
    beta_locales: Iterable[str],
    mirror_dirs: Iterable[str] = (),
) -> FullReport:
    locales_dir = locales_dir.resolve()
    reference_dir = locales_dir / reference
    namespaces = discover_namespaces(reference_dir)

    # 預載 reference 的 key 集合,避免重複解析
    reference_keys_by_ns: dict[str, set[str]] = {}
    for ns in namespaces:
        reference_keys_by_ns[ns] = flatten_keys(load_json(reference_dir / f"{ns}.json"))

    beta_set = {b.strip() for b in beta_locales if b.strip()}
    all_locales = discover_target_locales(locales_dir, reference)

    report = FullReport(
        reference=reference,
        threshold=0.0,  # 由 caller 設定
        beta_locales=sorted(beta_set),
    )

    for locale in all_locales:
        is_beta = locale in beta_set
        loc_report = LocaleReport(locale=locale, is_beta=is_beta)
        for ns in namespaces:
            skip = is_beta and ns not in BETA_ALLOWED_NAMESPACES
            target_path = locales_dir / locale / f"{ns}.json"
            if locale == reference:
                # reference 自身永遠 100%
                loc_report.namespaces.append(
                    NamespaceReport(
                        namespace=ns,
                        reference_count=len(reference_keys_by_ns[ns]),
                        target_count=len(reference_keys_by_ns[ns]),
                        missing_keys=[],
                        extra_keys=[],
                        skipped=False,
                        target_exists=True,
                    )
                )
                continue
            loc_report.namespaces.append(
                build_namespace_report(
                    namespace=ns,
                    reference_keys=reference_keys_by_ns[ns],
                    target_path=target_path,
                    skipped=skip,
                )
            )
        report.locales.append(loc_report)

    for raw_mirror in mirror_dirs:
        mirror = raw_mirror.strip()
        if not mirror:
            continue
        report.mirrors.append(
            build_mirror_report(
                source_dir=locales_dir,
                mirror_dir=Path(mirror).resolve(),
                display_path=mirror,
                beta_set=beta_set,
            )
        )

    return report


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_human(report: FullReport) -> str:
    lines: list[str] = []
    lines.append("Translation coverage report")
    lines.append("")
    lines.append(f"Reference: {report.reference}")
    lines.append(f"Threshold (active locales): >= {report.threshold:g}%")
    if report.beta_locales:
        lines.append(
            "Beta locales (only common.json counted): "
            + ", ".join(report.beta_locales)
        )
    lines.append("")

    for loc in report.locales:
        if loc.locale == report.reference:
            lines.append(f"[REF] {loc.locale}  (source of truth)")
            lines.append("")
            continue

        tag = "BETA" if loc.is_beta else "ACTIVE"
        status = "PASS"
        if not loc.is_beta and loc.coverage < report.threshold:
            status = f"FAIL (< {report.threshold:g}%)"

        header = (
            f"[{tag}] {loc.locale}  {loc.coverage:g}% "
            f"({loc.total_reference - loc.total_missing}/{loc.total_reference} keys, "
            f"{loc.total_missing} missing)  {status}"
        )
        lines.append(header)

        for ns in loc.namespaces:
            if ns.skipped:
                lines.append(
                    f"  - {ns.namespace}.json: skipped (beta, uses fallback)"
                )
                continue
            status_bits: list[str] = []
            if not ns.target_exists:
                status_bits.append("file missing")
            summary = (
                f"  - {ns.namespace}.json: {ns.coverage:g}% "
                f"({ns.reference_count - len(ns.missing_keys)}/{ns.reference_count})"
            )
            if status_bits:
                summary += " [" + ", ".join(status_bits) + "]"
            lines.append(summary)
            if ns.missing_keys:
                preview = ns.missing_keys[:10]
                lines.append("      Missing keys:")
                for k in preview:
                    lines.append(f"        - {k}")
                if len(ns.missing_keys) > len(preview):
                    lines.append(
                        f"        ... +{len(ns.missing_keys) - len(preview)} more"
                    )
            if ns.extra_keys:
                preview = ns.extra_keys[:5]
                lines.append(
                    f"      WARN: {len(ns.extra_keys)} extra key(s) not in reference "
                    "(possible typo):"
                )
                for k in preview:
                    lines.append(f"        + {k}")
                if len(ns.extra_keys) > len(preview):
                    lines.append(
                        f"        ... +{len(ns.extra_keys) - len(preview)} more"
                    )
        lines.append("")

    lines.extend(render_human_mirrors(report))

    failed = report.failed_locales()
    failed_mirrors = report.failed_mirrors()
    if failed or failed_mirrors:
        lines.append("Result: FAIL")
        if failed:
            lines.append(
                "  Below-threshold locales: "
                + ", ".join(f"{l.locale} ({l.coverage:g}%)" for l in failed)
            )
        if failed_mirrors:
            lines.append(
                "  Out-of-sync mirrors: " + ", ".join(m.path for m in failed_mirrors)
            )
    else:
        lines.append("Result: OK")
    return "\n".join(lines) + "\n"


def render_human_mirrors(report: FullReport) -> list[str]:
    if not report.mirrors:
        return []
    lines: list[str] = []
    lines.append("Mirror consistency (files + key sets must match the source dir)")
    lines.append("")
    for mirror in report.mirrors:
        if mirror.root_missing:
            lines.append(f"[MIRROR] {mirror.path}  FAIL (directory not found)")
            lines.append("")
            continue
        if mirror.ok and not mirror.drifts:
            lines.append(
                f"[MIRROR] {mirror.path}  OK ({mirror.file_count} file(s) in sync)"
            )
            lines.append("")
            continue
        status = "OK (warnings only)" if mirror.ok else "FAIL"
        lines.append(
            f"[MIRROR] {mirror.path}  {status} — "
            f"{len(mirror.failures)} blocking, {len(mirror.warnings)} warning(s)"
        )
        for drift in mirror.drifts:
            tag = "FAIL" if drift.is_failure else "WARN"
            note = " (beta, uses fallback)" if drift.skipped else ""
            if drift.missing_file:
                lines.append(
                    f"  - {drift.label}: [{tag}] file missing in mirror{note}"
                )
                continue
            if drift.extra_file:
                lines.append(
                    f"  - {drift.label}: [WARN] file only exists in mirror{note}"
                )
                continue
            lines.append(f"  - {drift.label}: [{tag}]{note}")
            if drift.parse_error:
                # 檔案讀不起來時 key 差異只是雜訊(整份都會算成 missing),先修 JSON。
                lines.append(f"      invalid JSON: {drift.parse_error}")
                continue
            if drift.missing_keys:
                preview = drift.missing_keys[:10]
                lines.append(
                    f"      Missing in mirror ({len(drift.missing_keys)}):"
                )
                for k in preview:
                    lines.append(f"        - {k}")
                if len(drift.missing_keys) > len(preview):
                    lines.append(
                        f"        ... +{len(drift.missing_keys) - len(preview)} more"
                    )
            if drift.extra_keys:
                preview = drift.extra_keys[:5]
                lines.append(
                    f"      WARN: {len(drift.extra_keys)} key(s) only in mirror:"
                )
                for k in preview:
                    lines.append(f"        + {k}")
                if len(drift.extra_keys) > len(preview):
                    lines.append(
                        f"        ... +{len(drift.extra_keys) - len(preview)} more"
                    )
        lines.append("")
    if report.failed_mirrors():
        lines.append(
            "  Fix: re-sync the mirror from the source dir. Only files/keys the "
            "mirror is MISSING block; mirror-only ones just warn."
        )
        lines.append("")
    return lines


def render_github_summary(report: FullReport) -> str:
    lines: list[str] = []
    lines.append("## Translation staleness report")
    lines.append("")
    lines.append(f"- Reference: `{report.reference}`")
    lines.append(f"- Threshold (active locales): **>= {report.threshold:g}%**")
    if report.beta_locales:
        lines.append(
            "- Beta locales (only `common.json` counted): "
            + ", ".join(f"`{b}`" for b in report.beta_locales)
        )
    lines.append("")

    lines.append("### Overview")
    lines.append("")
    lines.append("| Locale | Type | Coverage | Missing / Total | Status |")
    lines.append("| --- | --- | --- | --- | --- |")
    for loc in report.locales:
        if loc.locale == report.reference:
            lines.append(
                f"| `{loc.locale}` | reference | 100% | 0 / {loc.total_reference} | - |"
            )
            continue
        tag = "beta" if loc.is_beta else "active"
        if not loc.is_beta and loc.coverage < report.threshold:
            status = "FAIL"
        else:
            status = "OK"
        lines.append(
            f"| `{loc.locale}` | {tag} | {loc.coverage:g}% | "
            f"{loc.total_missing} / {loc.total_reference} | {status} |"
        )
    lines.append("")

    lines.append("### Per-namespace detail")
    lines.append("")
    for loc in report.locales:
        if loc.locale == report.reference:
            continue
        lines.append(f"#### `{loc.locale}`")
        lines.append("")
        lines.append("| Namespace | Coverage | Missing | Extra | Note |")
        lines.append("| --- | --- | --- | --- | --- |")
        for ns in loc.namespaces:
            note_parts: list[str] = []
            if ns.skipped:
                note_parts.append("skipped (beta)")
            if not ns.target_exists:
                note_parts.append("file missing")
            note = ", ".join(note_parts) or "-"
            lines.append(
                f"| `{ns.namespace}` | {ns.coverage:g}% | "
                f"{len(ns.missing_keys)} | {len(ns.extra_keys)} | {note} |"
            )
        lines.append("")

        has_missing = any(ns.missing_keys and not ns.skipped for ns in loc.namespaces)
        if has_missing:
            lines.append("<details><summary>Missing keys</summary>")
            lines.append("")
            for ns in loc.namespaces:
                if ns.skipped or not ns.missing_keys:
                    continue
                lines.append(f"**`{ns.namespace}`** ({len(ns.missing_keys)})")
                lines.append("")
                lines.append("```")
                for k in ns.missing_keys[:200]:
                    lines.append(k)
                if len(ns.missing_keys) > 200:
                    lines.append(f"... +{len(ns.missing_keys) - 200} more")
                lines.append("```")
                lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.extend(render_github_mirrors(report))

    failed = report.failed_locales()
    failed_mirrors = report.failed_mirrors()
    if failed or failed_mirrors:
        reasons: list[str] = []
        if failed:
            reasons.append(
                "below-threshold locales: "
                + ", ".join(f"`{l.locale}` ({l.coverage:g}%)" for l in failed)
            )
        if failed_mirrors:
            reasons.append(
                "out-of-sync mirrors: "
                + ", ".join(f"`{m.path}`" for m in failed_mirrors)
            )
        lines.append("**Result: FAIL** — " + "; ".join(reasons))
    else:
        lines.append("**Result: OK**")
    lines.append("")
    return "\n".join(lines)


def render_github_mirrors(report: FullReport) -> list[str]:
    if not report.mirrors:
        return []
    lines: list[str] = []
    lines.append("### Mirror consistency")
    lines.append("")
    lines.append(
        "These directories must carry the exact same files and keys as the "
        "source locales dir. Missing files/keys block; mirror-only ones only warn."
    )
    lines.append("")
    lines.append("| Mirror | Status | Blocking | Warnings |")
    lines.append("| --- | --- | --- | --- |")
    for mirror in report.mirrors:
        if mirror.root_missing:
            status = "FAIL (dir not found)"
        elif not mirror.ok:
            status = "FAIL"
        elif mirror.drifts:
            status = "OK (warnings)"
        else:
            status = "OK"
        lines.append(
            f"| `{mirror.path}` | {status} | {len(mirror.failures)} | "
            f"{len(mirror.warnings)} |"
        )
    lines.append("")

    for mirror in report.mirrors:
        if not mirror.drifts:
            continue
        lines.append(f"<details><summary>Drift in <code>{mirror.path}</code></summary>")
        lines.append("")
        lines.append("```")
        for drift in mirror.drifts:
            tag = "FAIL" if drift.is_failure else "WARN"
            note = " (beta, uses fallback)" if drift.skipped else ""
            if drift.missing_file:
                lines.append(f"[{tag}] {drift.label}: file missing in mirror{note}")
                continue
            if drift.extra_file:
                lines.append(f"[WARN] {drift.label}: file only in mirror{note}")
                continue
            if drift.parse_error:
                lines.append(f"[FAIL] {drift.label}: {drift.parse_error}")
                continue
            for k in drift.missing_keys:
                lines.append(f"[{tag}] {drift.label}: missing in mirror -> {k}")
            for k in drift.extra_keys:
                lines.append(f"[WARN] {drift.label}: only in mirror -> {k}")
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check translation coverage across locales relative to a reference "
            "(default zh-TW)."
        )
    )
    parser.add_argument(
        "--locales-dir",
        default=DEFAULT_LOCALES_DIR,
        help="Directory containing <locale>/<namespace>.json (default: %(default)s)",
    )
    parser.add_argument(
        "--reference",
        default=DEFAULT_REFERENCE,
        help="Reference locale used as source of truth (default: %(default)s)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="Minimum coverage percent for active locales (default: %(default)s)",
    )
    parser.add_argument(
        "--beta-locales",
        default=DEFAULT_BETA_LOCALES,
        help=(
            "Comma-separated beta locales (only common.json checked, other "
            "namespaces use fallback). Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--mirrors",
        default=None,
        help=(
            "Comma-separated dirs that must mirror --locales-dir file-for-file and "
            "key-for-key. Defaults to '"
            + ",".join(DEFAULT_MIRROR_DIRS)
            + "' when --locales-dir is left at its default; pass an empty string to "
            "skip the mirror check."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Emit machine-readable JSON report.",
    )
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="Emit a Markdown report suitable for $GITHUB_STEP_SUMMARY.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    locales_dir = Path(args.locales_dir)
    beta_locales = [b.strip() for b in args.beta_locales.split(",") if b.strip()]

    if args.mirrors is None:
        # 內建 mirror 清單是相對倉庫根目錄的固定路徑,只有在用預設 source dir
        # 時才成立;有人指定 --locales-dir(測試或臨時目錄)就不比,否則會拿
        # 臨時目錄去對撞倉庫裡的鏡像。
        mirror_dirs = (
            list(DEFAULT_MIRROR_DIRS)
            if args.locales_dir == DEFAULT_LOCALES_DIR
            else []
        )
    else:
        mirror_dirs = [m.strip() for m in args.mirrors.split(",") if m.strip()]

    try:
        report = check_translations(
            locales_dir=locales_dir,
            reference=args.reference,
            beta_locales=beta_locales,
            mirror_dirs=mirror_dirs,
        )
    except FileNotFoundError as exc:
        message = f"Error: {exc}"
        if args.json_out:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(message, file=sys.stderr)
        return 2

    report.threshold = float(args.threshold)

    if args.json_out:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif args.github_summary:
        print(render_github_summary(report))
    else:
        print(render_human(report))

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
