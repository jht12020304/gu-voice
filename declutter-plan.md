# 原生 iOS declutter 現況盤點與第一階段計畫

狀態：第一階段，尚未改產品碼，等待使用者核准。

基準：`ios_native/` 目前程式與既有合成資料截圖。現有基準截圖位於 `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/`。本輪根目錄 Docker backend 因 5432 被既有服務占用而未使用；未停止或覆蓋該服務。

本輪隔離 fixture 已用 project name `gu-voice-declutter` 啟動，DB／Redis 不暴露主機埠，backend 使用 `127.0.0.1:18083`，完成後已執行 `docker compose ... down -v`。新增截圖位於 `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/artifacts/declutter-before/`：`00-login.png` 與 `ui-flow/000.png`–`ui-flow/028.png`、`final.png`。UI flow log 位於 `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/artifacts/declutter-before/ui-flow/xcodebuild.log`。因既有測試未輸出 case summary，不能把這批定時截圖宣稱為完整逐畫面矩陣；它們是隔離 fixture 執行期間的現況證據。

## 共用規則

- 每個畫面只保留一個可見主要動作。其他導覽、重新整理、匯出、編輯、刪除、標記已讀等動作收進右上角 `⋯`，破壞性動作仍保留 confirmation dialog。
- 刪除副標題、說明段落、重複標題與操作提示，只保留 navigation title、欄位名稱、資料值與必要的狀態／錯誤文字。
- 載入失敗、錯誤、retry 與必要驗證錯誤不刪。
- 互動式輸入欄位不是「主要按鈕」；流程頁只保留一個前進／送出 CTA。
- 五語同步修改 `Localizable.xcstrings` 與 `en-US`、`zh-Hant`、`ja`、`ko`、`vi` 的 kiosk strings；刪除 key 前先確認全域無引用。

## 醫師／臨床管理畫面

| 畫面 | 刪除文字 | 收進 `⋯` | 留下的主要按鈕 | 必留 |
|---|---|---|---|---|
| 臨床首頁／報告清單 | 重複歡迎語、篩選說明、空狀態的非錯誤解釋 | 語言、主題、重新整理、通知、登出及次要入口 | 開啟報告／進入目前清單 | 載入失敗與 retry、空狀態必要文字 |
| 報告詳情 | 區段副標、重複病患／場次提示 | 核准、退回、PDF、開啟 web 報告、分享等非主要操作 | 依狀態保留唯一審核主動作 | 退回理由欄位、空白／全空白理由錯誤與 confirmation |
| SOAP／逐字稿 | 重複區段說明、資料來源提示 | 匯出、開啟 web、次要跳轉 | 查看或返回清單中的主要導向 | 載入／錯誤文字 |
| 場次清單／場次詳情 | 日期範圍與篩選教學、重複狀態說明 | 重新整理、月份切換、研究／通知等次要入口 | 開啟場次 | 錯誤與 retry |
| 病患清單 | 搜尋／篩選教學、空清單解釋 | 重新整理、篩選、次要匯出 | 開啟病患 | 錯誤與 retry |
| 紅旗清單／詳情 | 重複警示說明 | 全部確認、單筆確認、重新整理、次要跳轉 | 開啟警示詳情或唯一確認動作 | 紅旗狀態與錯誤 |
| 通知 | 已讀操作提示、重複空狀態標題 | 全部已讀、重新整理 | 開啟通知 | 錯誤與 retry |
| 臨床設定 | 設定說明與重複帳號提示 | 語言、主題、登出 | 儲存／完成唯一主要設定動作 | 登出卡住時「請聯絡系統管理員」 |
| 研究 | 統計解釋段落與重複標題 | 重新整理、篩選／日期切換 | 開啟統計或唯一主要查詢 | 錯誤與 retry |
| 快速開單 | 操作教學、重複欄位說明 | 清除、重新開啟上一張等次要操作 | 提交醫囑 | 空清單／送出錯誤 |

## 管理員畫面

| 畫面 | 刪除文字 | 收進 `⋯` | 留下的主要按鈕 | 必留 |
|---|---|---|---|---|
| 管理員首頁／使用者 | 歡迎語、權限說明、重複標題 | 重新整理、編輯、停用／啟用、密碼重置、登出 | 新增使用者或開啟使用者 | 錯誤與 retry |
| 系統健康 | 健康指標說明與重複提示 | 重新整理 | 重新整理結果 | 載入失敗與 retry |
| 稽核 | 篩選教學與重複說明 | 重新整理、篩選、分頁次要操作 | 開啟稽核列 | 錯誤與 retry |
| 主訴模板 | 狀態說明、重複操作提示 | 新增、編輯、刪除、重新整理 | 開啟或儲存模板 | 刪除 confirmation、錯誤與 retry |
| 模板編輯 | 欄位說明、副標題 | 取消 | 儲存 | 驗證錯誤與儲存錯誤 |

## 病患 kiosk

| 畫面 | 刪除文字 | 收進 `⋯` | 留下的主要按鈕 | 必留 |
|---|---|---|---|---|
| Kiosk 登入／首頁 | 歡迎與流程說明、重複入口標題 | 歷史、設定、登出 | 開始／繼續問診 | 錯誤與載入失敗 |
| 主訴選擇 | 多選教學、字數提示（驗證錯誤除外）、重複副標 | 返回、次要歷史入口 | 下一步 | 載入失敗、必填與上限錯誤 |
| 病患資料／病史 | 步驟說明、選填教學、重複標題 | 上一步、取消 | 下一步／開始 AI 問診 | 欄位錯誤、醫師清單載入失敗 |
| 問診對話 | 重複語音提示、非必要狀態描述 | TTS、重播、語音／文字切換等次要操作 | 送出文字或結束問診 | 連線／麥克風錯誤、問診結束 confirmation |
| 問診完成／病患紀錄 | 後續注意事項中非必要重複說明、重複標題 | 歷史、返回首頁等次要入口 | 回到首頁或唯一查看主要結果 | 載入失敗、報告未產生狀態 |
| 紅旗完成／中止 | 非必要解釋 | 歷史／返回等次要入口 | 返回／完成唯一主動作 | 「請稍候等看診」、「請告知現場醫護」 |
| 病患設定 | 設定教學與重複帳號提示 | 語言、登出 | 儲存／完成 | 登出卡住時「請聯絡系統管理員」 |
| 閒置登出 | 非錯誤倒數說明若與標題重複 | 取消（若有） | 重新登入／返回登入 | 登出失敗與管理員聯絡提示 |

## 現況截圖矩陣

已存在的合成基準：

- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/02-native-after-upgrade.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/03-native-report.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/04-native-soap.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/05-native-transcript.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/06-native-second-doctor.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/07-native-admin.png`
- `/Users/chun/.herdr/worktrees/gu-voice/req/ios-native-declutter/ios_native/Screenshots/08-native-kiosk.png`

仍缺逐一命名與補拍：醫師／管理員每個 route、kiosk 主訴／病史／對話／完成／紅旗、錯誤／載入失敗、問診結束確認、退回理由驗證、登出卡住提示。隔離 fixture 沒有 worker，無法自然產生報告核准／退回／PDF／快速開單狀態；Claude 建議在隔離 DB 直接寫入合成 generated report 後再拍。不得使用 production backend 或停止目前占用 5432 的服務。

## Claude review 未決事項

Claude 審查結論為「不通過，改完後再審」。保護 key、動態 key、UI test identifiers、錯誤恢復出口、既有 `account-menu` 與共用 `⋯` 元件要求已回寫 git dir 的 `req-plan.md`。需總管先取得使用者對下列六項決定：報告核准／退回的可見性、退回說明文字、音訊控制收納範圍、完成頁兩段提示、`native.kioskPlaceholder` 是否保留、重複次要按鈕是否可直接刪除。未取得決定前不改產品碼。

## 等待核准

這份計畫只描述現況與預計改動，尚未修改 `ios_native/App`、String Catalog 或測試。收到使用者核准後才進入第二段。
