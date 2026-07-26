# flutter_app — GU Voice 單一碼庫前端

取代 `frontend/`（React + Vite）的 Flutter 實作，一份碼庫出 **web + iOS + Android**。**backend 完全不動**，打的是同一組 REST / WebSocket API。

兩套前端目前並存：`frontend/` 仍是生產在跑的版本，這裡尚未經生產驗證。

## 現況

26 條路由與 React 版對齊（病患問診、醫師 dashboard／SOAP／紅旗／research、admin 四頁、auth 四頁）。語音管線核心（VAD 決策矩陣、TTS epoch 世代取消、PCM ring buffer）已移植並有單元測試。

已知缺口（2 blocker + 11 high，含 kiosk 閒置登出、醫師端全域紅旗提示、家族史欄位）見 [`docs/TODO.md`](../docs/TODO.md) §G。

## 跑法

```bash
flutter pub get
flutter run -d chrome                     # web，預設打 http://localhost:8000
flutter run                               # 接上的 iOS / Android 裝置
flutter analyze && flutter test           # 合併前必跑
```

後端位址用 `--dart-define` 覆寫（預設值見 `lib/core/config/env.dart`）：

```bash
flutter run --dart-define=API_BASE_URL=https://<host> --dart-define=WS_BASE_URL=wss://<host>
```

## 注意

- `assets/locales/` 是 5 語言翻譯檔，**與 `frontend/src/i18n/locales/` 逐檔位元相同**。切換期新增 key 要同步改兩份；React 下線後這裡才成為唯一來源。
- 語言唯一權威是 URL 路徑段（`/zh-TW/...`），與 React 版同一條鐵律。裝置語系只在 URL 無語言段時當 seed。
