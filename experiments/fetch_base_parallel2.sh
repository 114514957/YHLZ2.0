#!/bin/bash
# 12 路并行 + 断点续传（把 .tmp 里已下的部分先收编）
set -e
D=/root/autodl-tmp/models/gemma-4-e4b-it-uncensored
F=model.safetensors
SIZE=15992595884
URL=https://hf-mirror.com/TrevorJS/gemma-4-E4B-it-uncensored/resolve/main/model.safetensors
N=12
cd "$D"

if [ "$(stat -c %s "$F" 2>/dev/null || echo 0)" = "$SIZE" ]; then echo "✅ 已完整"; exit 0; fi

# 收编 .tmp：先接回 part.i，再从断点续
for t in part.*.tmp; do
  [ -e "$t" ] || continue
  i=${t#part.}; i=${i%.tmp}
  cat "$t" >> "part.$i"
  rm -f "$t"
done

CHUNK=$(( (SIZE + N - 1) / N ))
: > ranges.txt
for i in $(seq 0 $((N-1))); do
  START=$(( i * CHUNK )); END=$(( START + CHUNK - 1 ))
  [ $END -ge $SIZE ] && END=$((SIZE-1))
  echo "$i $START $END" >> ranges.txt
done

fetch() {
  i=$1; s=$2; e=$3
  want=$(( e - s + 1 ))
  for try in $(seq 1 25); do
    got=$(stat -c %s "part.$i" 2>/dev/null || echo 0)
    [ "$got" -ge "$want" ] && return 0
    curl -sS -L --max-time 900 --speed-time 60 --speed-limit 1024 \
      -r $((s+got))-$e "$URL" >> "part.$i" || true
  done
}
export -f fetch; export URL

awk '{print $1, $2, $3}' ranges.txt | xargs -P $N -n 3 bash -c 'fetch "$@"' _

echo "== 拼装 =="
: > "$F"
for i in $(seq 0 $((N-1))); do cat "part.$i" >> "$F"; done
rm -f part.*
echo "最终 $(stat -c %s "$F")（应 $SIZE）"
[ "$(stat -c %s "$F")" = "$SIZE" ] && echo "✅ 基座完整" || { echo "❌ 不符"; exit 3; }
