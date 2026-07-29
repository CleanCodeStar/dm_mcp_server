#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
达梦数据库 MCP 服务器 - PyPI 包配置
"""

from setuptools import setup, find_packages
import os

# 读取 README 文件
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# 读取 requirements.txt
def read_requirements():
    with open("requirements.txt", "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="dm-mcp-server",
    version="2.6.4",
    author="CleanCode",
    author_email="15706058532@163.com",
    description="达梦数据库 Model Context Protocol (MCP) 服务器",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/CleanCodeStar/dm_mcp_server",
    py_modules=["dm_mcp_server"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Database",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=read_requirements(),
    entry_points={
        "console_scripts": [
            "dm-mcp-server=dm_mcp_server:main",
        ],
    },
    keywords="dameng database mcp model-context-protocol dmPython",
    project_urls={
        "Bug Reports": "https://github.com/CleanCodeStar/dm_mcp_server/issues",
        "Source": "https://github.com/CleanCodeStar/dm_mcp_server",
        "Documentation": "https://github.com/CleanCodeStar/dm_mcp_server#readme",
    },
    include_package_data=True,
    zip_safe=False,
)
