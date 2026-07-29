# 达梦数据库 MCP 服务器

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![uv](https://img.shields.io/badge/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)

一个基于 FastMCP 框架的达梦数据库 Model Context Protocol (MCP) 服务器。该服务器采用环境变量驱动，深度结合达梦数据库特性，并内置严格的安全审计机制。

## 🌟 特性

- 🚀 **环境变量驱动**: 全面通过环境变量配置，无需手动调用连接工具，即插即用。
- 🛡️ **深度安全审计**:
  - 强制锁定配置的 `DAMENG_SCHEMA`。
  - 自动拦截跨模式 (Cross-Schema) 访问尝试。
  - 禁止在元数据查询中尝试过滤非本模式的信息。
  - SQL 注入风险模式检测（多语句注入、注释注入、存储过程调用等）。
  - 精细化 DDL/DCL 权限控制（允许表/索引/序列/视图管理，拦截权限变更和其他未授权 DDL）。
- 🔀 **多 Schema 支持**: 支持配置多个允许的 Schema，可在允许范围内自由切换。
- 🔒 **只读模式**: 可选开启只读模式，禁止所有写操作（INSERT/UPDATE/DELETE/DDL）。
- 📄 **分页查询**: `execute_sql` 支持 `limit` / `offset` 参数，避免大数据量一次性返回。
- 📝 **批量字段注释**: 支持一次性执行多条 `COMMENT ON COLUMN` 字段注释语句，减少 AI 与 MCP 的多轮交互。
- 🛠️ **多维工具集**: 提供从基础 SQL 执行到模式元数据管理的 9 大核心工具。
- 🌏 **编码优化**: 针对 Windows 终端及达梦 `UTF-8` 编码进行了专项适配。
- ⚡ **现代管理**: 使用 `uv` 进行依赖锁定与高性能运行时管理。

## 快速开始

### 1. 安装依赖

推荐使用 `uv` 进行环境同步：

```bash
uv sync
```

### 2. 配置环境变量

服务器在启动时会读取以下环境变量：

| 变量名 | 说明 | 必填 | 默认值 |
| :-- | :-- | :-- | :-- |
| `DAMENG_HOST` | 数据库主机地址 | **是** | - |
| `DAMENG_PORT` | 数据库端口 | 否 | 5236 |
| `DAMENG_USER` | 数据库用户名 | **是** | - |
| `DAMENG_PASSWORD` | 数据库密码 | **是** | - |
| `DAMENG_SCHEMA` | 默认操作模式 | **是** | - |
| `DAMENG_ALLOWED_SCHEMAS` | 允许访问的模式列表（逗号分隔） | 否 | 仅 `DAMENG_SCHEMA` |
| `DAMENG_READ_ONLY` | 只读模式（true/false） | 否 | false |
| `DAMENG_LOG_LEVEL` | 日志级别（DEBUG/INFO/WARNING/ERROR） | 否 | INFO |
| `DAMENG_SQL_FILE_ALLOWED_DIRS` | 允许 `execute_sql_file` 读取 SQL 文件的目录列表，多个目录按系统路径分隔符分隔 | 否 | 当前工作目录 |

> `DAMENG_SQL_FILE_ALLOWED_DIRS` 示例：Windows 单目录可写 `E:\sql`，多目录用分号分隔如 `E:\sql;D:\dm-sql`；Linux/macOS 多目录用冒号分隔如 `/data/sql:/tmp/dm-sql`。

### 3. 运行服务器

```bash
# Windows (PowerShell 示例) - 单 Schema 模式
$env:DAMENG_HOST="192.168.x.x"; $env:DAMENG_USER="SYSDBA"; $env:DAMENG_PASSWORD="your_password"; $env:DAMENG_SCHEMA="your_schema"; $env:DAMENG_SQL_FILE_ALLOWED_DIRS="E:\sql"; uv run dm-mcp-server

# Windows (PowerShell 示例) - 多 Schema + 只读模式
$env:DAMENG_HOST="192.168.x.x"; $env:DAMENG_USER="SYSDBA"; $env:DAMENG_PASSWORD="your_password"; $env:DAMENG_SCHEMA="schema_a"; $env:DAMENG_ALLOWED_SCHEMAS="schema_a,schema_b,schema_c"; $env:DAMENG_READ_ONLY="true"; $env:DAMENG_SQL_FILE_ALLOWED_DIRS="E:\sql;D:\dm-sql"; uv run dm-mcp-server
```

## 🛠️ 提供工具

服务器暴露了以下 9 个工具供 LLM 调用：

1. **`test_connection`**
   - **功能**: 验证数据库连接状态，返回当前 Schema、允许的 Schema 列表、只读模式状态。

2. **`execute_sql`**
   - **参数**: `sql` (字符串), `fetch_results` (布尔值，默认 true), `limit` (整数，可选), `offset` (整数，可选)。
   - **功能**: 执行 SQL 语句。涉及 `SELECT` 时返回字典列表。支持分页。内置多层安全审查（注入检测、跨 Schema 检测、只读模式检测）。

3. **`execute_sql_file`**
   - **参数**: `file_path` (字符串), `encoding` (字符串，默认 utf-8), `stop_on_error` (布尔值，默认 true), `fetch_results` (布尔值，默认 false), `limit` (整数，可选), `offset` (整数，可选)。
   - **功能**: 读取并执行 `.sql` 文件，适合超长 INSERT、批量初始化脚本等 MCP 单次调用无法承载的场景。文件必须位于 `DAMENG_SQL_FILE_ALLOWED_DIRS` 白名单目录内；AI 可先调用 `get_sql_file_allowed_dirs` 获取可写目录，再将文件保存到该目录。支持一个文件内包含多条 SQL；执行前会剥离 `--` 和 `/* */` 注释，再逐条复用现有只读模式与 Schema 白名单安全校验。
   - **示例**:
     ```text
     execute_sql_file(file_path="E:\\sql\\bulk_insert.sql")
     ```

4. **`get_sql_file_allowed_dirs`**
   - **功能**: 返回 `execute_sql_file` 当前允许读取的目录列表、目录是否存在、是否可写、推荐写入目录、路径分隔符和 `.sql` 扩展名要求，方便 AI 先落盘 SQL 文件再执行。

5. **`batch_comment_columns_sql`**
   - **参数**: `sql` (字符串), `stop_on_error` (布尔值，默认 true)。
   - **功能**: 批量执行字段注释 SQL。仅允许 `COMMENT ON COLUMN 表名.字段名 IS '注释内容'` 或 `COMMENT ON COLUMN SCHEMA.表名.字段名 IS '注释内容'` 语句，禁止混入其他 SQL。
   - **示例**:
     ```sql
     COMMENT ON COLUMN USER_INFO.ID IS '主键ID';
     COMMENT ON COLUMN USER_INFO.USER_NAME IS '用户名称';
     COMMENT ON COLUMN USER_INFO.PHONE IS '手机号';
     ```

6. **`list_tables`**
   - **参数**: `schema` (字符串，可选)。
   - **功能**: 列出指定模式下的所有表名。不指定则查询默认 Schema。

7. **`count_tables`**
   - **参数**: `schema` (字符串，可选)。
   - **功能**: 统计指定模式下的总表数。不指定则统计默认 Schema。

8. **`get_current_schema`**
   - **功能**: 返回当前 Schema、允许的 Schema 列表、只读模式状态。

9. **`switch_schema`**
   - **参数**: `schema` (字符串)。
   - **功能**: 切换当前操作的 Schema。仅在配置了 `DAMENG_ALLOWED_SCHEMAS` 时可用，且目标 Schema 必须在允许列表中。

## 🔒 安全性说明

为了防止非授权的数据访问，本服务器实施了以下安全策略：

- **模式隔离**: 所有 SQL 操作在执行前，都会通过 `SET SCHEMA` 显式切换到环境变量指定的模式。
- **多 Schema 白名单**: 通过 `DAMENG_ALLOWED_SCHEMAS` 配置允许访问的 Schema 列表，未在列表中的 Schema 一律拒绝。
- **SQL 注入防护**: 检测并拦截常见的 SQL 注入模式，包括多语句注入（`;`）、注释注入（`--`、`/*`）、存储过程调用（`EXEC`、`CALL`、`xp_`、`sp_`）等。
- **跨 Schema 检测**: 拦截包含点号 (`.`) 前缀且非允许模式的 SQL 标识符（例如禁止查询 `OTHER_SCHEMA.TABLE`）。
- **元数据保护**: 在查询 `ALL_TABLES` 等系统视图时，如果检测到试图查询非允许模式的 `OWNER`，将直接拦截。
- **只读模式**: 开启后，仅允许 `SELECT`、`WITH`、`EXPLAIN`、`SHOW`、`DESCRIBE` 等查询语句，禁止所有写操作和 DDL。
- **DDL/DCL 精细化控制** (v2.6.1+):
  - **允许**: `CREATE`、`ALTER`、`DROP` 的 `TABLE`、`INDEX`、`SEQUENCE`、`VIEW`，以及 `RENAME`、`COMMENT ON`、`TRUNCATE`。
  - **拦截**: `GRANT`/`REVOKE`（权限变更）、`PROCEDURE` 及其他未列入白名单的 DDL。
  - **智能识别**: 正确区分 SQL 字符串值中的关键词与实际 DDL/DCL 语句，INSERT/UPDATE 中包含如 `'DROP TABLE x'` 的字符串值不会被误拦截。

## 在 Cursor / Claude Desktop / Antigravity / Trae 中配置

### 使用 `uvx` (推荐方式)

将以下配置添加到您的 MCP 配置文件中（如 Cursor 的 `mcpServers` 设置）：

```json
{
  "mcpServers": {
    "dm_mcp_server": {
      "command": "uvx",
      "args": [
        "dm-mcp-server@latest"
      ],
      "env": {
        "DAMENG_HOST": "192.168.x.x",
        "DAMENG_PORT": "5236",
        "DAMENG_USER": "SYSDBA",
        "DAMENG_PASSWORD": "your_password",
        "DAMENG_SCHEMA": "your_schema",
        "DAMENG_SQL_FILE_ALLOWED_DIRS": "E:\\sql"
      }
    }
  }
}
```

### 多 Schema + 只读模式配置示例

```json
{
  "mcpServers": {
    "dm_mcp_server": {
      "command": "uvx",
      "args": [
        "dm-mcp-server@latest"
      ],
      "env": {
        "DAMENG_HOST": "192.168.x.x",
        "DAMENG_PORT": "5236",
        "DAMENG_USER": "SYSDBA",
        "DAMENG_PASSWORD": "your_password",
        "DAMENG_SCHEMA": "schema_a",
        "DAMENG_ALLOWED_SCHEMAS": "schema_a,schema_b,schema_c",
        "DAMENG_READ_ONLY": "false",
        "DAMENG_LOG_LEVEL": "INFO",
        "DAMENG_SQL_FILE_ALLOWED_DIRS": "E:\\sql;D:\\dm-sql"
      }
    }
  }
}
```

## 许可证

MIT License
