#!/bin/zsh
set -euo pipefail

repo_root="${0:A:h:h}"
cd "$repo_root"

for component in backend flutter_app frontend; do
  graphify update "$component"
done

if [[ ! -f docs/graphify-out/graph.json ]]; then
  print -u2 "docs/graphify-out/graph.json 不存在。請先在 Codex 執行 /graphify docs，再重跑此腳本。"
  exit 1
fi

graphify merge-graphs \
  backend/graphify-out/graph.json \
  flutter_app/graphify-out/graph.json \
  frontend/graphify-out/graph.json \
  docs/graphify-out/graph.json \
  --out graphify-out/graph.json

graphify cluster-only . --graph graphify-out/graph.json --no-viz
python3 scripts/normalize_graphify_labels.py graphify-out/.graphify_labels.json
graphify cluster-only . --graph graphify-out/graph.json --no-viz
graphify export html --graph graphify-out/graph.json

print "Graphify 圖譜已更新：$repo_root/graphify-out/graph.json"
