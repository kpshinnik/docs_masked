# -*- coding: utf-8 -*-
"""Корень проекта в sys.path, чтобы тесты видели pii_shield и mcp_server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
