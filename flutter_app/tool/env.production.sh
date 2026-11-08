# 生產後端位址——build_ios_testflight.sh 與 build_vercel_output.sh 共用（source 進來）。
# 變數名是 API_BASE / WS_BASE（不是 *_BASE_URL），值含 path 後綴；
# 呼叫端用 ${API_BASE:-${PROD_API_BASE}}，所以明確給的環境變數永遠優先。
# 注意：`api-` 開頭的域名是死的，不要用。staging 位址見 docs/ios_release_settings.md §0。
PROD_API_BASE="https://gu-voice-app-production.up.railway.app/api/v1"
PROD_WS_BASE="wss://gu-voice-app-production.up.railway.app/api/v1/ws"
# React 網頁版（醫師看報告）正式網址：醫師報告頁「在網頁開啟」用（dart-define WEB_BASE）。
PROD_WEB_BASE="https://gu-voice-chuns-projects-068de742.vercel.app"
