# 推播不通時，照這個順序查

> **這份只講「怎麼定位斷點」。設定值不在這裡**：APNs／ASC 金鑰與 Key ID 見
> [`ios_release_settings.md`](ios_release_settings.md)，架構見
> [`app_architecture.md`](app_architecture.md) §2.3／§5，通知落地見
> [`session_data_inventory.md`](session_data_inventory.md) §5.3。

## 先破除一個假象

**「App 內有跳通知，鎖定畫面沒有」不代表推播壞了。**

站內通知走 **WebSocket**（dashboard 事件）＋ `notifications` 表，推播走 **Celery → APNs／FCM**。
兩條路完全獨立，**推播整條斷掉，站內照樣會跳**。2026-09-08 花了很久才發現真因是
「那支 App 打的根本不是這個後端」——正式環境從 09-03 07:38 到 09-09 之間一場問診都沒有。

⇒ **第 0 步永遠是：確認那支 App 打的是哪一個後端**，再往下查。

## 一條鏈，六個斷點

```
App 取得 APNs/FCM token
  → POST /notifications/fcm-token（寫入 fcm_devices）
    → 問診完成／報告完成 → notifications 表建立一列
      → _dispatch_push_best_effort → Celery .delay()
        → worker: 有 apns_token 就直送 api.push.apple.com，失敗才回退 FCM
          → Apple 投遞 → 裝置顯示
```

**每一段都是 best-effort、失敗只留 warning**，所以「沒有錯誤」不等於「有送出」。

送到了但**專注模式下不亮**是第七種：見 §7。

### 1. 後端環境變數有沒有設

```bash
railway variables --json | python3 -c "
import json,sys; d=json.load(sys.stdin)
for k in ['FCM_CREDENTIALS_JSON','APNS_AUTH_KEY_BASE64','APNS_KEY_ID','APNS_TEAM_ID','APNS_TOPIC']:
    print(k, 'PRESENT' if d.get(k) else 'MISSING')"
```

⚠️ **「有設」不等於「值是對的」**（2026-08-22 生產 OPENAI_API_KEY 是死 key 的同一類教訓）。
要證明值可用，跳到第 5 步直接對 Apple 發一則。

### 2. Celery worker 在不在

推播是 `send_push_notification_task.delay()`，worker 沒跑 = 任務永遠在佇列裡。

```bash
railway logs -d | grep -i celery | tail
```

看得到 `check-session-timeouts ... succeeded` 就表示 worker 活著。
（worker 與 beat 跑在 API 同一個容器，`RUN_CELERY_IN_API` 預設 true，見 `scripts/start.sh`。）

### 3. 那位醫師有沒有 active 的裝置

**最常見的斷點。** `_async_send` 只取 `is_active=True`，撈不到就直接 `{"skipped": true}` 返回。

```bash
railway run --service gu-voice-app -- ./venv/bin/python - <<'PY'
import asyncio, os, re, asyncpg
url = re.sub(r'^postgresql\+asyncpg','postgresql',os.environ["DATABASE_URL"])
async def main():
    c = await asyncpg.connect(url, statement_cache_size=0)
    for r in await c.fetch("""select u.email, d.platform, d.device_name, d.is_active,
                                     (d.apns_token is not null) as apns, d.updated_at
                              from fcm_devices d join users u on u.id=d.user_id
                              order by d.updated_at desc limit 20"""):
        print(dict(r))
    await c.close()
asyncio.run(main())
PY
```

判讀：

- `is_active=False` → 最後一次寫入是**登出**（`remove_fcm_token`）。重新登入會由
  `register_fcm_token` 設回 True 並更新 `updated_at`；`updated_at` 沒動 = 那支 App 根本沒重新註冊。
- `device_name='localhost'` = 真 iPhone；`*.local`（如 `chundeMac-mini.local`）= 模擬器。
  **模擬器拿不到 APNs token，推播在架構上就不可能送達。**
- 完全沒有列 = App 端註冊失敗，回頭看 `push_service.dart` 的 debugPrint 或後端 access log
  有沒有 `POST /api/v1/notifications/fcm-token`。

### 4. 通知有沒有被建立、推播任務有沒有跑

```bash
railway logs -d | grep -E "send_push_notification_task|無已註冊裝置|推播"
```

成功長這樣（`apns_sent` 等於 `sent` 表示全走直送、沒退到 FCM）：

```
send_push_notification_task[...] succeeded: {'user_id': '...', 'sent': 2, 'apns_sent': 2, 'failed': 0}
```

`{'skipped': True}` → 回第 3 步。完全沒有這行 → 通知那一層就沒建立（查 `notifications` 表，
可能被 `NotificationPreference` 的類型偏好或 `push_enabled` 抑制了）。

### 5. 直接對 Apple 發一則（決定性）

繞過整個後端邏輯，只驗「金鑰＋topic＋device token」這一組。回 **HTTP 200** 就代表
後端這一側完全沒有嫌疑，斷點在裝置上。

```bash
railway run --service gu-voice-app -- ./venv/bin/python - <<'PY'
import asyncio, base64, os, re, time, asyncpg, httpx, jwt
url = re.sub(r'^postgresql\+asyncpg','postgresql',os.environ["DATABASE_URL"])
async def main():
    c = await asyncpg.connect(url, statement_cache_size=0)
    rows = await c.fetch("""select d.apns_token, d.is_active, u.email from fcm_devices d
                            join users u on u.id=d.user_id
                            where u.email like $1 and d.apns_token is not null""", "改成目標醫師email前綴%")
    await c.close()
    tok = jwt.encode({"iss": os.environ["APNS_TEAM_ID"], "iat": int(time.time())},
                     base64.b64decode(os.environ["APNS_AUTH_KEY_BASE64"]).decode(),
                     algorithm="ES256", headers={"kid": os.environ["APNS_KEY_ID"]})
    payload = {"aps": {"alert": {"title": "推播測試", "body": "看得到＝鏈路正常"},
                       "sound": "default", "interruption-level": "time-sensitive"}}
    headers = {"authorization": f"bearer {tok}", "apns-topic": os.environ["APNS_TOPIC"],
               "apns-push-type": "alert", "apns-priority": "10"}
    async with httpx.AsyncClient(http2=True, timeout=15) as cl:
        for r in rows:
            for env, host in (("production","api.push.apple.com"),("sandbox","api.sandbox.push.apple.com")):
                resp = await cl.post(f"https://{host}/3/device/{r['apns_token']}",
                                     headers=headers, json=payload)
                print(r["apns_token"][:8], env, resp.status_code, resp.text[:120])
                if resp.status_code == 200: break
asyncio.run(main())
PY
```

常見 reason：

| 回應 | 意思 |
|---|---|
| `200` | Apple 收下了。收不到就是裝置端問題（見第 6 步） |
| `400 BadDeviceToken` | token 的環境與端點不符。**Xcode 直接跑真機＝sandbox token**，而後端直送寫死 production；TestFlight 才是 production |
| `400 DeviceTokenNotForTopic` | token 不屬於這個 bundle id |
| `410 Unregistered` | App 已被移除，token 該作廢 |
| `403` | 金鑰／Team ID／Key ID 有一個對不上 |

⚠️ **Apple 對「App 已卸載」的 token 也可能回 200 然後靜靜丟掉**，所以 200 之後仍要看裝置。

### 6. 裝置端

1. 設定 → 通知 → UroSense：「允許通知」之外，**「鎖定畫面」那個勾也要開**——只勾橫幅
   的症狀正好是「App 內看得到、鎖定畫面沒有」。
2. 專注模式／勿擾。
3. token 屬於已被覆蓋的舊安裝 → 在裝置上重開 App 並重新登入，寫入新 token。

### 7. time-sensitive 沒生效（醫師開專注／睡眠模式時不亮）

**症狀**：後端 log 一切正常、Apple 回 200、白天沒開專注模式的人收得到，但開著睡眠／專注模式的
醫師鎖定畫面不亮，只在通知摘要裡看得到。2026-09-09 凌晨對三位測試員實測就是這樣。

**成因**：`interruption-level: time-sensitive` 要 App 宣告 entitlement
`com.apple.developer.usernotifications.time-sensitive` 才有效；**沒宣告時 iOS 不報錯，安靜降級成
一般通知**。build `202609081800` 以前的每一顆都沒有這個 entitlement，所以後端一直以為紅旗會
穿透勿擾，實際上從來沒有。

**驗法**（對 export 出來的 .ipa，不是看 repo 的 entitlements 檔）：

```bash
unzip -q build/ios/ipa/gu_voice.ipa -d /tmp/ipa && codesign -d --entitlements :- /tmp/ipa/Payload/Runner.app
# 期望看到 <key>com.apple.developer.usernotifications.time-sensitive</key><true/>
```

打包腳本第 6 關已會擋（2026-09-09 起）。⚠️ 用 `plutil -extract` 讀這個 key 要把點跳脫成
`com\.apple\.developer\.…`，否則 plutil 把點當 key path 分隔符、永遠讀到空。

**修法**（兩邊都要）：
1. `flutter_app/ios/Runner/Runner.entitlements` 宣告該 key（已於 2026-09-09 加入）。
2. App ID `com.guvoice.guVoice` 要有 **Time Sensitive Notifications** capability。專案是自動簽章且
   `flutter build ipa` 帶 `-allowProvisioningUpdates`，Xcode 通常會在打包時自動把它加到 App ID；
   若簽章報 provisioning profile 缺該 entitlement，就到 developer.apple.com → Identifiers 手動勾。

**限制**：就算修好，使用者仍可在「設定 → 通知 → UroSense」關掉「時效性通知」；它是提高送達
機率，不是保證。要「靜音也響」得申請 Apple 的 Critical Alerts entitlement（需送審，醫療 App 是
合格類別），另案處理。

## 已知的設計限制

- **`_send_apns()` 只打 `api.push.apple.com`。** development profile 簽的包拿到的是 sandbox
  token，直送必回 `BadDeviceToken`，程式會把 `apns_token` 清成 NULL 再退回 FCM——會動，
  但每次都白走一趟且悄悄掉資料。要在 Xcode 真機開發流程用推播的話，得先補 sandbox 備援。
- **kiosk iPad 不註冊推播**（`shouldEnablePush` 對病患帳號恆 false）。共用機不得成為任何人的
  推播端點——這是刻意的，不是缺陷。
