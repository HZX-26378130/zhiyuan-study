@echo off
chcp 65001 >nul
title 知源学伴 · AI辅助学习系统
cd /d "%~dp0"
echo 正在启动服务...
py -3 server.py
pause
