---
name: i18n-language-consistency
description: GU Voice 前端語言一致性不變式（URL 為唯一語言權威）與翻譯檔工作流（src/i18n/locales → public/locales build 鏡像）。Use when 動到語言切換/偵測邏輯、新增或修改翻譯字串、frontend/src/services/api/client.ts 的 Accept-Language、或任何顯示在地化資料（依語言 refetch）的頁面。
---

# 前端語言一致性與翻譯工作流

## Overview

語言狀態曾因多重來源（cookie / navigator / 後端偏好）互相打架造成跨頁不一致。現行設計：**URL 是語言的唯一權威**，其他一切派生自它。翻譯檔則有「源頭 vs build 鏡像」的雙份結構，漏一半就會生產缺字。

## When to Use

- 改語言切換、語言偵測、預設語言邏輯
- 新增/修改翻譯字串（5 locales：zh-TW、en-US、ja-JP、ko-KR、vi-VN）
- 改 API client 的 Accept-Language 行為
- 頁面顯示依語言而異的後端資料（診斷名、主訴清單等）

## 不變式

1. **URL 為語言唯一權威**：語言偏好的讀取與切換都經 URL；不得引入第二權威。
2. `frontend/src/services/api/client.ts` 的 Accept-Language 是**刻意 URL-first**——看起來繞路，不是 bug，別「修正」它。
3. 顯示在地化資料的頁面必須 keyed on `resolvedLanguage` refetch（參考 `frontend/src/screens/doctor/PatientListPage.tsx` 等既有寫法），否則切語言後殘留舊語言資料。
4. `frontend/public/locales/` 是 `frontend/src/i18n/locales/` 的 **tracked build 鏡像**：改 src 後必跑 `npm run build` 重生 public，**兩者同一個 commit**。

## 翻譯字串工作流

1. 改 `frontend/src/i18n/locales/<locale>/*.json`（5 個 locale 都要補，別只補 zh-TW）
2. `npm run i18n:extract:check` — 確認沒有漏抽的 key
3. `npm run build` — 重生 `public/locales/`
4. 在 repo 根目錄跑 `python scripts/check_translations.py` — 確認各 locale key 與鏡像完整
5. src + public 一起 commit

## Flutter iOS 與 React 網頁並行維護（2026-10-03）

上面是 React 的流程。兩端都持續維護，分工以 `docs/README.md` 為準：

1. 五份翻譯在 `flutter_app/assets/locales/<locale>/*.json`（zh-TW / en-US / ja-JP /
   ko-KR / vi-VN），**五個一起補**，別只補 zh-TW。
2. 在 repo 根目錄執行 `python scripts/check_translations.py --locales-dir flutter_app/assets/locales`，
   以 App 自己的 zh-TW 為基準檢查。CI 對 React 與 Flutter 分開執行同一個檢查器；
   beta 語系目前只阻擋 `common` 的缺漏，新增其他 namespace 字串仍需補齊五語。
   既有 `fvm flutter test` 文案守衛繼續保留，特殊顯示行為用對應測試驗證。
3. 共用功能需檢查兩端的行為與文案；平台專用功能只維護該端使用的 key。
   不把 React 的完整翻譯樹複製到 Flutter，或反向複製。React 的 `public/locales/`
   仍必須與自己的 `src/i18n/locales/` 同步。
4. ⚠️ `t()` 查不到 key 時**原樣回傳 key**（`core/i18n/loc.dart` 的刻意設計，
   讓缺字看得見）。所以「畫面上出現一串英文駝峰」就是缺 key 的徵兆——
   而且 **`t()` 的第一個 dot 段是 namespace**（＝檔名），裸字串（沒有 dot）
   永遠查不到。活例：登入頁的 `errorGeneric`（TODO §W-A）。

## Common Rationalizations

| 藉口 | 現實 |
|---|---|
| 「public/locales 是 build 產物，不用 commit」 | 它是 tracked 鏡像，生產直接吃它；只 commit src 等於生產缺字 |
| 「client.ts 這段 Accept-Language 邏輯很怪，順手重構」 | URL-first 是刻意設計（語言一致性事故的修復），重構前先讀本 skill 與 memory |
| 「先補 zh-TW，其他語言之後再說」 | check_translations 會抓，且 kiosk 有真實外語病患，缺字直接面向病患 |
| 「檢查 React 就等於檢查 App」 | 兩端各有自己的翻譯來源，Flutter 也要指定 `--locales-dir` 執行檢查 |

## Verification

- [ ] 兩端的 `check_translations.py` 皆通過；React 另跑 `i18n:extract:check`
- [ ] `public/locales/` 已重生且與 src 改動同一 commit
- [ ] 切語言後在地化資料頁面即時 refetch（手動驗證或 Playwright）
