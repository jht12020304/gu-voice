#!/usr/bin/env python3
"""Translation staleness checker for UroSense i18n.

比對各 locale / namespace 的 JSON key 覆蓋率,以 zh-TW 為 reference(source
of truth)。支援 human-readable、JSON 與 GitHub Actions Markdown summary
三種輸出,並以 exit code 反映閾值檢查結果,供 CI 掛鉤。

使用方式:
    python scripts/check_translations.py
    python scripts/check_translations.py --json
    python scripts/check_translations.py --github-summary
    python scripts/check_translations.py --threshold 90

設計備忘:
- 盡量用 Python 3.12 標準庫(argparse / json / pathlib),不引入外部依賴。
- beta locale 預設為 `ja-JP,ko-KR,vi-VN`,這些語言只檢查 common.json,其他
  namespace 缺 key 不計入 fail 判定(因為有 fallbackLng chain)。
- reference 的多餘 key 不會被當成 missing,但會在 extra_keys 欄位列出,
  方便 PR reviewer 發現 typo。
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
class FullReport:
    reference: str
    threshold: float
    beta_locales: list[str]
    locales: list[LocaleReport] = field(default_factory=list)

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference,
            "threshold_pct": self.threshold,
            "beta_locales": list(self.beta_locales),
            "locales": [loc.to_dict() for loc in self.locales],
            "failed_locales": [loc.locale for loc in self.failed_locales()],
            "ok": not self.failed_locales(),
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


def check_translations(
    locales_dir: Path,
    reference: str,
    beta_locales: Iterable[str],
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

    failed = report.failed_locales()
    if failed:
        lines.append("Result: FAIL")
        lines.append(
            "  Below-threshold locales: "
            + ", ".join(f"{l.locale} ({l.coverage:g}%)" for l in failed)
        )
    else:
        lines.append("Result: OK")
    return "\n".join(lines) + "\n"


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

    failed = report.failed_locales()
    if failed:
        lines.append(
            "**Result: FAIL** — below-threshold locales: "
            + ", ".join(f"`{l.locale}` ({l.coverage:g}%)" for l in failed)
        )
    else:
        lines.append("**Result: OK**")
    lines.append("")
    return "\n".join(lines)


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

    try:
        report = check_translations(
            locales_dir=locales_dir,
            reference=args.reference,
            beta_locales=beta_locales,
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

    return 0 if not report.failed_locales() else 1


if __name__ == "__main__":
    sys.exit(main())
