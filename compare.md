# Declutter before/after capture

Capture device: `GUVoice-Kiosk-QA` simulator (`6CB888D6-359C-4546-8539-DC00B5E0E00B`). Both runs used the isolated `gu-voice-declutter` Compose project and synthetic kiosk data. The after run captured 32 time-sliced frames while the two existing kiosk UI tests executed.

## Pair map

| State / frame | Before | After |
|---|---|---|
| Login | [before](artifacts/declutter-before/00-login.png) | [after](artifacts/declutter-after/00-login.png) |
| Kiosk flow frame 000 | [before](artifacts/declutter-before/ui-flow/000.png) | [after](artifacts/declutter-after/ui-flow/000.png) |
| Kiosk flow frame 001 | [before](artifacts/declutter-before/ui-flow/001.png) | [after](artifacts/declutter-after/ui-flow/001.png) |
| Kiosk flow frame 002 | [before](artifacts/declutter-before/ui-flow/002.png) | [after](artifacts/declutter-after/ui-flow/002.png) |
| Kiosk flow frame 003 | [before](artifacts/declutter-before/ui-flow/003.png) | [after](artifacts/declutter-after/ui-flow/003.png) |
| Kiosk flow frame 004 | [before](artifacts/declutter-before/ui-flow/004.png) | [after](artifacts/declutter-after/ui-flow/004.png) |
| Kiosk flow frames 005–028 | `artifacts/declutter-before/ui-flow/005.png`–`028.png` | `artifacts/declutter-after/ui-flow/005.png`–`028.png` |
| Kiosk flow final | [before](artifacts/declutter-before/ui-flow/final.png) | [after](artifacts/declutter-after/ui-flow/final.png) |

The numbered flow frames are time-sliced simulator captures, not stable semantic screen identifiers. The UI test log is next to the after frames at `artifacts/declutter-after/ui-flow/xcodebuild.log`.

## Required screen coverage audit

The repository contains only `KioskFlowTests.swift` under `ios_native/UITests`; no `LocalDoctorTests`, admin UI test, report-detail UI test, or fixture navigation driver exists. The isolated Compose fixture seeds only a kiosk patient and doctor. It has no report worker, generated-report seed, clinical-admin seed, or system-admin seed. Therefore doctor, administrator, report-detail, opened-menu, return-reason, export, and quick-order semantic screenshots cannot be honestly produced by the existing test harness without adding a new fixture/test driver or synthetic report data.

The existing before screenshots for the available clinical states remain in `ios_native/Screenshots/` and are linked from `declutter-plan.md`. This gap is reported explicitly instead of relabeling unrelated kiosk frames as doctor/admin screens.

## Test result

- Isolated kiosk fixture: the prior non-quiet run passed both `KioskFlowTests` cases with 0 failures. The after capture rerun used the same opt-in environment and completed the capture; its quiet log only emitted simulator launch diagnostics and no case summary.
- Doctor/admin UI tests: not present in this checkout, so there are no such tests to run. This is a repository limitation, not a skipped test claim.
