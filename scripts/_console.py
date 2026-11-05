# -*- coding: utf-8 -*-
"""Windows 控制台 UTF-8 输出辅助：各测试脚本开头调用 utf8()，
避免中文输出在 GBK 控制台上乱码或抛 UnicodeEncodeError。"""
import io
import sys


def utf8():
    """将 stdout / stderr 重新包装为 UTF-8（替换原缓冲区，errors=replace 兜底）。"""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
