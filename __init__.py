#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
达梦数据库 MCP 服务器

一个基于 FastMCP 框架的达梦数据库 Model Context Protocol (MCP) 服务器，
提供完整的达梦数据库操作功能。

Author: CleanCode
Version: 2.6.4
"""

__version__ = "2.6.4"
__author__ = "CleanCode"
__email__ = "15706058532@163.com"
__description__ = "达梦数据库 Model Context Protocol (MCP) 服务器"

try:
    from .dm_mcp_server import main
    __all__ = ['main']
except ImportError:
    __all__ = []
