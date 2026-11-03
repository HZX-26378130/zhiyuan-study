# -*- coding: utf-8 -*-
"""粗定位 app.js 语法失衡行：跟踪 {} 与 ` 计数（忽略模板串内的 ${} 不完美，但能找到异常跳变）。"""
import io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
src = open("frontend/app.js", encoding="utf-8").read().splitlines()
opens = 0
backticks = 0
btline = 0
for i, l in enumerate(src, 1):
    j = 0
    in_s = None
    while j < len(l):
        ch = l[j]
        if in_s:
            if ch == '\\':
                j += 2
                continue
            if ch == in_s:
                in_s = None
        elif ch in ('"', "'", '`'):
            in_s = ch
            if ch == '`':
                backticks += 1
                btline = i
        elif ch == '{':
            opens += 1
        elif ch == '}':
            opens -= 1
        j += 1
    if 843 <= i <= 868:
        print(i, "opens=%d" % opens, "bt=%d" % backticks, l[:64])
print("END opens=", opens, "backticks=", backticks, "last-backtick-line=", btline)
