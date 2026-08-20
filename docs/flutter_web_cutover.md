# Flutter Web staged production runbook

Flutter Web is deployed as a staged production deployment first. The existing React
deployment remains on the public domain until microphone, STT, TTS, VAD, login, and
deep-link checks pass in a real browser.

## Current status (2026-08-17)

- Fixed staged URL: `https://gu-voice-flutter-preview.vercel.app`
- React production URL: `https://gu-voice-chuns-projects-068de742.vercel.app`
- React rollback deployment: `gu-voice-ktox9rgon-chuns-projects-068de742.vercel.app`
- Verified: Flutter 3.41.3 release build, analyze, 78 tests, five locale deep links,
  security headers, Railway health/CORS, and dedicated patient test login
- Pending blocker: real browser microphone, STT, TTS, VAD, transcript, and session completion
- The fill button uses a dedicated public patient account with no real patient data.
  Its password is deployment input and must not be committed or written in docs.

## Build

Use the pinned Flutter SDK. A normal public build contains no credentials. To show
the fill button, supply `WEB_TEST_EMAIL` and `WEB_TEST_PASSWORD` for a dedicated,
patient-only public test account. Never use doctor or administrator credentials.

```bash
cd flutter_app
fvm install
./tool/build_vercel_output.sh
```

The button only fills the form and never submits it automatically. Public test
credentials are necessarily visible in the downloaded web bundle, so the account
must contain no real patient data.

## Deploy without changing the public domain

```bash
vercel link --yes --project gu-voice --scope chuns-projects-068de742
vercel deploy --prebuilt --prod --skip-domain --scope chuns-projects-068de742
```

Vercel CLI may still move the team-scoped production alias even with
`--skip-domain`. Record the current deployment before this command and immediately
restore that alias with `vercel alias set <previous-deployment> <team-alias>`; use
only the new immutable deployment URL for staged validation. The primary custom
alias must remain on React until promotion.

Add the exact staged deployment origin to Railway's CORS allowlist without removing
the current production origin. Test the five locale deep links, doctor/admin/patient
roles, password reset links, REST/WebSocket connectivity, and browser console CSP or
CORS errors.

For the patient voice check, use the dedicated production test patient created through
the normal registration flow. Verify microphone permission, speech recognition, AI TTS,
VAD mute while TTS plays, transcript creation, interruption recovery, and session
completion. Never use doctor/admin credentials or real patient data in the web build.

## Promote or roll back

Before promotion, confirm there are no sessions with status `in_progress`, record the
current React deployment URL, and set Railway `FRONTEND_BASE_URL` to the public URL.

```bash
vercel promote <staged-deployment-url> --scope chuns-projects-068de742
```

Smoke-test the public URL immediately. To roll back, promote the recorded React
deployment again; do not delete either deployment during the validation window.
