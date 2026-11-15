@echo off
rem 2026-11-08 生成「拒绝方向」控制向量：正样本=该被拒的，负样本=无害的（等长配对，去长度污染）
chcp 65001 >nul
set "BIN=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\llama-cuda\src\llama.cpp-b10991\build-cvec\bin"
set "MODEL=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gemma4-gguf\gemma-4-E4B_q4_0-it.gguf"
set "STEER=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\steer"
cd /d "%STEER%"
set PATH=%BIN%;%PATH%
llama-cvector-generator.exe -m "%MODEL%" --positive-file refuse_pos.txt --negative-file refuse_neg.txt --method mean -c 1024 -o cvec_refuse_mean.gguf
echo EXIT=%errorlevel%
dir /b cvec_refuse_mean.gguf 2>nul
