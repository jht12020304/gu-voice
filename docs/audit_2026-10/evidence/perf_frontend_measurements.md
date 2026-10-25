# Frontend measurements (vite preview build, Chromium headless, local)

## Cold-load locale JSON requests (script: locale_requests.mjs; counts /locales/* responses until networkidle)

| stored urosense:lng | URL | before | after |
|---|---|---|---|
| zh-TW | /en-US/login | 20 (en-US 10 + zh-TW 10) 15.0 KB | 20, 15.0 KB (unchanged: zh-TW is en-US's fallback by design) |
| en-US | /en-US/login | 20, 15.0 KB | 20, 15.0 KB (same reason) |
| none | /zh-TW/login | 10, 7.2 KB | 10, 7.2 KB |
| en-US | /zh-TW/login | 20, 15.0 KB | **10, 7.2 KB** |
| ja-JP | /zh-TW/dashboard | 30 (ja+en+zh), 29.2 KB | **10, 7.2 KB** |

Change: i18n init takes `lng` from the URL path (URL is the language authority per CLAUDE.md); LanguageDetector only used when the path has no language prefix.

## Static asset
| asset | before | after |
|---|---|---|
| /logo.png (favicon + 32/80 px logo) | 1,077,339 B (1024×1024) | 85,686 B (256×256, covers 3× DPI at 80 px) |

## Bundle (gzip, all JS chunks)
| before | after dead-code removal + perf batch |
|---|---|
| 212,611 B | 212,524 B (dead exports were already tree-shaken; removal is maintainability, not bytes) |

## Not measured (structural only, stated as such)
- ThemeToggle / ReportListPage selector subscriptions, PatientListPage useMemo: render-count reduction not profiled headless.
