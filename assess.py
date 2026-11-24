#!/usr/bin/env python3
"""项目命令行薄入口，便于在隔离模式下直接运行：

    python3 -I assess.py report

``-I`` 会隐含 ``-P``，不自动把脚本目录放上 sys.path；这里显式加入
本文件所在的项目根目录，避免从当前工作目录误导入同名模块。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from handover.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
