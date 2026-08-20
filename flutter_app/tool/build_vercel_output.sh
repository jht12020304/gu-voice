#!/usr/bin/env bash
set -euo pipefail

app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_base="${API_BASE:-https://gu-voice-app-production.up.railway.app/api/v1}"
ws_base="${WS_BASE:-wss://gu-voice-app-production.up.railway.app/api/v1/ws}"
web_test_email="${WEB_TEST_EMAIL:-}"
web_test_password="${WEB_TEST_PASSWORD:-}"
static_dir="${app_dir}/.vercel/output/static"
config_file="${app_dir}/.vercel/output/config.json"

if [[ -n "${E2E_EMAIL:-}" || -n "${E2E_PASSWORD:-}" ]]; then
  echo "Use WEB_TEST_EMAIL/WEB_TEST_PASSWORD for an explicitly public, patient-only test account." >&2
  exit 1
fi
if [[ -n "${web_test_email}" && -z "${web_test_password}" ]] ||
   [[ -z "${web_test_email}" && -n "${web_test_password}" ]]; then
  echo "WEB_TEST_EMAIL and WEB_TEST_PASSWORD must be supplied together." >&2
  exit 1
fi

case "${static_dir}" in
  "${app_dir}/.vercel/output/static") ;;
  *) echo "Unexpected Vercel output path: ${static_dir}" >&2; exit 1 ;;
esac

cd "${app_dir}"
if command -v fvm >/dev/null 2>&1; then
  flutter_cmd=(fvm flutter)
else
  installed_version="$(flutter --version | sed -n '1s/^Flutter \([^ ]*\).*/\1/p')"
  if [[ "${installed_version}" != "3.41.3" ]]; then
    echo "Flutter 3.41.3 is required (found ${installed_version:-unknown}); install FVM or the pinned SDK." >&2
    exit 1
  fi
  flutter_cmd=(flutter)
fi

"${flutter_cmd[@]}" pub get --enforce-lockfile
"${flutter_cmd[@]}" analyze --no-pub
"${flutter_cmd[@]}" test --no-pub
"${flutter_cmd[@]}" build web \
  --release \
  --no-pub \
  --csp \
  --no-web-resources-cdn \
  --output "${static_dir}" \
  --dart-define="API_BASE=${api_base}" \
  --dart-define="WS_BASE=${ws_base}" \
  --dart-define="E2E_EMAIL=${web_test_email}" \
  --dart-define="E2E_PASSWORD=${web_test_password}"

dart run tool/prepare_vercel_output.dart "${config_file}"

test -s "${static_dir}/index.html"
test -s "${static_dir}/main.dart.js"
test -s "${config_file}"
echo "Prepared Vercel Build Output API bundle at ${app_dir}/.vercel/output"
