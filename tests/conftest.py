"""pytest 公共配置：把后端应用目录加入模块搜索路径（相对本文件定位，不依赖工作目录）。"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))
