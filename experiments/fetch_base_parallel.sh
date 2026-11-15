#!/bin/bash
# 8 路并行分块下基座（单连接 1-5MB/s，并行吃满带宽）
set -e
D=/root/autodl-tmp/models/gemma-4-e4b-it-uncensored
F=model.safetensors
SIZE=15992595884
URL=https://hf-mirror.com/TrevorJS/gemma-4-E4B-it-uncensored/resolve/main/model.safetensors
N=8
cd "$D"

have=$(stat -c %s "$F" 2>/dev/null || echo 0)
if [ "$have" = "$SIZE" ]; then echo "✅ 已完整"; exit 0; fi

# 把单文件当第 0 块，直接截断重下（避免续传边界错乱）
rm -f "$F"
rm -f part.*

CHUNK=$(( (SIZE + N - 1) / N ))
echo "总 $SIZE 字节，每块 $CHUNK，共 $N 路"

for i in $(seq 0 $((N-1))); do
  START=$(( i * CHUNK ))
  END=$(( START + CHUNK - 1 ))
  [ $END -ge $SIZE ] && END=$((SIZE-1))
  echo "$i $START $END"
done > ranges.txt

fetch() {
  read -r i s e <<< "$1"
  for try in 1 2 3 4 5 6 7 8; do
    want=$(( e - s + 1 ))
    got=$(stat -c %s "part.$i" 2>/dev/null || echo 0)
    [ "$got" = "$want" ] && return 0
    curl -sS -L --max-time 1800 -r $((s+got))-$e -o "part.$i.tmp" "$URL" || true
    if [ -f "part.$i.tmp" ]; then
      cat "part.$i.tmp" >> "part.$i"
      rm -f "part.$i.tmp"
    fi
  done
}
export -f fetch
export URL

for i in $(seq 0 $((N-1))); do
  grep "^$i " ranges.txt
done | xargs -P $N -I{} bash -c 'fetch "{}"'

echo "== 拼装 =="
for i in $(seq 0 $((N-1))); do cat "part.$i" >> "$F"; done
rm -f part.*
echo "最终 $(stat -c %s "$F") 字节（应 $SIZE）"
[ "$(stat -c %s "$F")" = "$SIZE" ] && echo "✅ 基座完整" || { echo "❌ 大小不符"; exit 3; }
