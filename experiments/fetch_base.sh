#!/bin/bash
# 直链下载基座（不走 HF API，绕开 429 限流）
set -e
D=/root/autodl-tmp/models/gemma-4-e4b-it-uncensored
mkdir -p "$D"
cd "$D"
BASE=https://hf-mirror.com/TrevorJS/gemma-4-E4B-it-uncensored/resolve/main
for f in config.json generation_config.json tokenizer.json tokenizer_config.json chat_template.jinja model.safetensors; do
  if [ -f "$f" ]; then
    want=$(case $f in
      model.safetensors) echo 15992595884 ;;
      tokenizer.json) echo 32169780 ;;
      config.json) echo 5175 ;;
      generation_config.json) echo 203 ;;
      tokenizer_config.json) echo 2686 ;;
      chat_template.jinja) echo 11926 ;;
      *) echo 0 ;;
    esac)
    have=$(stat -c %s "$f")
    if [ "$have" = "$want" ]; then echo "  ✓ $f 已完整（$have）"; continue; fi
    echo "  续传 $f（$have/$want）"
  else
    echo "  下载 $f …"
  fi
  curl -L -C - --retry 20 --retry-delay 5 --retry-all-errors -sS -o "$f" "$BASE/$f"
  echo "    → $(stat -c %s "$f") 字节"
done
echo "== 校验 =="
ls -l "$D"
[ "$(stat -c %s model.safetensors)" = "15992595884" ] && echo "✅ 基座完整" || { echo "❌ 基座大小不符"; exit 3; }
