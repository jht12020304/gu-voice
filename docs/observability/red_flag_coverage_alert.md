# Red Flag Rule-Layer Coverage Alert (TODO-O4)

This runbook describes the Grafana / Prometheus alert that fires when a
non-`zh-TW` locale's red-flag **rule-layer coverage** drops relative to
`zh-TW`, indicating the keyword regex catalogue lacks coverage for that
language and the system is leaning on LLM-only semantic hits.

## Metric

- `urovoice_red_flag_rule_layer_coverage_total{language, confidence}`
  Counter, incremented once per merged red-flag alert in
  `RedFlagDetector.detect()` (see `backend/app/core/metrics.py` and
  `backend/app/pipelines/red_flag_detector.py`).

  `confidence` values:
  - `rule_hit` - keyword/regex layer matched (high confidence)
  - `semantic_only` - only LLM semantic layer matched (medium confidence)
  - `uncovered_locale` - fail-safe: locale has no trigger keywords for
    the matched `canonical_id`, auto-escalated for physician review

## Coverage ratio (PromQL)

Rule-layer coverage for a given `language` over the last hour:

```promql
sum by (language) (
  rate(urovoice_red_flag_rule_layer_coverage_total{confidence="rule_hit"}[1h])
)
/
sum by (language) (
  rate(urovoice_red_flag_rule_layer_coverage_total{
    confidence=~"rule_hit|semantic_only"
  }[1h])
)
```

Lower ratio means more hits are coming from the LLM semantic layer,
which is higher variance and typically suggests the locale's keyword
rules are incomplete.

## Alert rule (Prometheus / Grafana Alerting)

```yaml
groups:
  - name: urovoice_red_flag_coverage
    interval: 1m
    rules:
      - alert: RedFlagRuleCoverageDegradedVsZhTW
        expr: |
          (
            sum by (language) (
              rate(urovoice_red_flag_rule_layer_coverage_total{
                confidence="rule_hit",
                language!="zh-TW"
              }[1h])
            )
            /
            clamp_min(
              sum by (language) (
                rate(urovoice_red_flag_rule_layer_coverage_total{
                  confidence=~"rule_hit|semantic_only",
                  language!="zh-TW"
                }[1h])
              ),
              1
            )
          )
          <
          0.5 * scalar(
            sum(
              rate(urovoice_red_flag_rule_layer_coverage_total{
                confidence="rule_hit",
                language="zh-TW"
              }[1h])
            )
            /
            clamp_min(
              sum(
                rate(urovoice_red_flag_rule_layer_coverage_total{
                  confidence=~"rule_hit|semantic_only",
                  language="zh-TW"
                }[1h])
              ),
              1
            )
          )
          and
          sum by (language) (
            increase(urovoice_red_flag_rule_layer_coverage_total{
              confidence=~"rule_hit|semantic_only"
            }[1h])
          )
          >= 30
        for: 15m
        labels:
          severity: page
          team: urosense_backend
          component: red_flag_detector
          routing: pagerduty
        annotations:
          summary: >-
            Red flag rule-layer coverage for {{ $labels.language }} dropped
            below 50% of zh-TW over the last hour.
          description: >-
            Locale {{ $labels.language }} is logging <50% of zh-TW's
            rule-layer coverage ratio with at least 30 hits in the last
            rolling hour. The keyword/regex catalogue likely needs new
            triggers_by_lang entries in app/pipelines/prompts/shared.py
            or new RedFlagRule DB rows. Check the
            `urovoice_red_flag_uncovered_locale_total{language="{{ $labels.language }}"}`
            counter for specific `canonical_id`s that frequently fail
            locale coverage.
          runbook: docs/observability/red_flag_coverage_alert.md
```

## Triage checklist

1. Pull the top `canonical_id` values for the offending language from
   the `urovoice_red_flag_uncovered_locale_total{language="..."}` series
   (we may need to add a `canonical_id` label in a follow-up if we want
   a direct breakdown; today we only log the `canonical_id` at WARN
   level in `RedFlagDetector.detect()`).
2. Review backend logs with filter
   `message:"紅旗 locale 覆蓋不足 → 自動 escalate"` to pick the specific
   `canonical_id`s.
3. Add the missing locale entries to
   `URO_RED_FLAGS[*].triggers_by_lang[<lang>]` in
   `backend/app/pipelines/prompts/shared.py`, or create DB
   `RedFlagRule` rows linked to the same `canonical_id`.
4. After deploy, the ratio should recover within one rolling hour once
   traffic comes in; silence the alert during the rollout window.

## Related

- `backend/app/models/enums.py` - `RedFlagConfidence`
- `backend/app/pipelines/red_flag_detector.py` - detector writes the metric
- `backend/app/core/metrics.py` - metric registration
- `backend/app/pipelines/prompts/shared.py` - `URO_RED_FLAGS`,
  `has_locale_coverage()`, `get_display_title()`
