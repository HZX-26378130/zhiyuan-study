# -*- coding: utf-8 -*-
"""脚本控制台编码兼容：Windows 默认 cp936 控制台打印 ✓/中文会抛 UnicodeEncodeError，
导致测试脚本明明全过却以 exit 1 结束。所有测试脚本开头调用 utf8() 即可。"""


def utf8():
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
