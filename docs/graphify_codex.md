# Graphify × Codex 專案設定

本專案已把 Graphify 設為專案層級的 Codex MCP。只要以受信任專案開啟 repository 根目錄，Codex 桌面版、CLI 或 IDE 擴充功能都會讀取 `.codex/config.toml`，並啟動 `graphify` MCP。

## 已設定的檔案

- `.codex/config.toml`：啟動 `graphify-mcp`，讀取根目錄的 `graphify-out/graph.json`。
- `.codex/hooks.json`：Graphify 的 Codex `PreToolUse` 檢查。
- `.codex/skills/graphify/`：專案內的 Graphify skill 與參考流程。
- `AGENTS.md`：要求 Codex 遇到程式庫問題時優先查詢知識圖譜。
- `scripts/refresh_graphify.sh`：更新三個程式子專案、合併文件圖譜並重建互動圖。
- `graphify-out/`：本機產物，已由 `.gitignore` 排除，可隨時重建。

Graphify 已安裝在獨立的 uv tool 環境。為避免部分 uv 版本只安裝 Graphify 指令、卻漏掉 Python MCP runtime，重裝時使用：

```bash
uv tool install --force --with 'mcp<3,>=1' 'graphifyy[mcp]'
```

`graphify` 與 `graphify-mcp` 必須能從 shell 的 `PATH` 找到。

## 每次開啟後使用

在 repository 根目錄開啟 Codex；第一次開啟時要把專案與 hooks 標示為受信任。重新啟動後，可在支援指令選單的 Codex 用 `/mcp`，或在終端執行 `codex mcp list`，確認 `graphify` 已連線。接著直接詢問架構、影響範圍或呼叫關係即可。常用的本機等價指令：

```bash
graphify query "登入流程如何串接前後端？"
graphify explain "red flag"
graphify path "節點 A" "節點 B"
```

## 更新圖譜

程式碼異動後，在 repository 根目錄執行：

```bash
./scripts/refresh_graphify.sh
```

此腳本只做本機 AST 更新，不需要 API key。文件異動後，先在 Codex 執行 `/graphify docs` 重新做文件語意抽取，再執行同一支腳本完成合併。若已設定 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`，也可以用 Graphify CLI 的 Gemini backend 重建文件圖譜。

## 驗證與疑難排解

```bash
command -v graphify graphify-mcp
codex mcp list
graphify-mcp graphify-out/graph.json
```

最後一個指令會啟動 STDIO server；手動測試時按 `Ctrl-C` 結束。若 `/mcp` 沒顯示 `graphify`，確認目前開啟的是 repository 根目錄、專案已受信任，然後重新啟動 Codex。

Graphify 的程式碼 AST 解析在本機完成，掃描時會遵守 `.gitignore` 並略過疑似敏感檔；目前的 `frontend/.env.production` 不會進入圖譜。文件語意抽取在未設定 Gemini key 時由目前的 Codex 工作階段處理。
