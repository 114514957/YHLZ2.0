@echo off
rem 生成 v2 控制向量：等长正负样本（去掉长度污染）
chcp 65001 >nul
set "BIN=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\llama-cuda\src\llama.cpp-b10991\build-cvec\bin"
set "MODEL=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\models\gemma4-gguf\gemma-4-E4B_q4_0-it.gguf"
set "STEER=C:\Users\ACE_WAN——PROJECT\YHLZ\YH\llm_workbench\steer"
cd /d "%STEER%"
set PATH=%BIN%;%PATH%
llama-cvector-generator.exe -m "%MODEL%" --positive-file positive2.txt --negative-file negative2.txt --method mean -c 1024 -o cvec_v2_mean.gguf
echo EXIT=%errorlevel%
dir /b cvec_v2_mean.gguf 2>nul
