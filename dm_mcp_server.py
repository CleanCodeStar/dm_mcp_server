#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
达梦数据库 MCP 服务器
遵循 FastMCP 规范实现，通过环境变量进行配置。
"""

import os
import re
import sys
import datetime
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from contextlib import contextmanager
from mcp.server.fastmcp import FastMCP

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    import dmPython
    DM_PYTHON_AVAILABLE = True
except ImportError:
    DM_PYTHON_AVAILABLE = False

LOG_LEVEL = os.environ.get("DAMENG_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("dm-mcp-server")

mcp = FastMCP("Dameng-MCP")

READONLY_KEYWORDS = {"SELECT", "WITH", "EXPLAIN", "SHOW", "DESC", "DESCRIBE"}

Token = Tuple[str, str]
IDENT_TOKEN_KINDS = {"IDENT", "QUOTED_IDENT"}
RELATION_KEYWORDS = {"FROM", "JOIN", "UPDATE", "INTO", "USING"}
JOIN_MODIFIERS = {
    "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS", "NATURAL",
    "STRAIGHT_JOIN",
}
CLAUSE_KEYWORDS = {
    "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET", "FETCH",
    "UNION", "INTERSECT", "EXCEPT", "MINUS", "CONNECT", "START",
    "MODEL", "QUALIFY", "WINDOW", "RETURNING", "VALUES", "SET", "ON",
    "USING", "WHEN", "ELSE", "END",
}
RESERVED_ALIAS_WORDS = CLAUSE_KEYWORDS | JOIN_MODIFIERS | {
    "AS", "SELECT", "WITH", "FROM", "JOIN", "UPDATE", "INSERT", "INTO",
    "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "TABLE",
    "VIEW", "INDEX", "BY", "AND", "OR", "NOT", "NULL", "IS", "IN",
}
METADATA_OWNER_VIEWS = {
    "ALL_TABLES", "ALL_TAB_COLUMNS", "ALL_OBJECTS", "ALL_VIEWS",
    "ALL_INDEXES", "ALL_CONSTRAINTS", "ALL_CONS_COLUMNS",
    "DBA_TABLES", "DBA_TAB_COLUMNS", "DBA_OBJECTS", "DBA_VIEWS",
    "DBA_INDEXES", "USER_TABLES", "USER_TAB_COLUMNS", "USER_OBJECTS",
}


def _parse_bool(val: str) -> bool:
    return val.strip().upper() in ("TRUE", "1", "YES", "ON")


def _parse_allowed_schemas() -> Optional[List[str]]:
    raw = os.environ.get("DAMENG_ALLOWED_SCHEMAS", "").strip()
    if not raw:
        return None
    schemas = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return schemas if schemas else None


def _parse_sql_file_allowed_dirs() -> List[Path]:
    raw = os.environ.get("DAMENG_SQL_FILE_ALLOWED_DIRS", "").strip()
    if not raw:
        return [Path.cwd().resolve()]
    dirs = [Path(p.strip()).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return dirs if dirs else [Path.cwd().resolve()]


def get_config():
    config = {
        'host': os.environ.get("DAMENG_HOST"),
        'port': os.environ.get("DAMENG_PORT"),
        'user': os.environ.get("DAMENG_USER"),
        'password': os.environ.get("DAMENG_PASSWORD"),
        'schema': os.environ.get("DAMENG_SCHEMA"),
        'read_only': _parse_bool(os.environ.get("DAMENG_READ_ONLY", "false")),
        'allowed_schemas': _parse_allowed_schemas(),
    }
    if not all([config['host'], config['user'], config['password']]):
        return None

    try:
        config['port'] = int(config['port']) if config['port'] else 5236
    except (ValueError, TypeError):
        config['port'] = 5236

    if config['allowed_schemas'] and config['schema']:
        if config['schema'].upper() not in config['allowed_schemas']:
            logger.warning(
                "DAMENG_SCHEMA '%s' 不在 DAMENG_ALLOWED_SCHEMAS 列表中，已自动追加",
                config['schema'],
            )
            config['allowed_schemas'].append(config['schema'].upper())

    return config


DB_CONFIG = get_config()
SQL_FILE_ALLOWED_DIRS = _parse_sql_file_allowed_dirs()


def _resolve_schema(requested_schema: Optional[str]) -> Optional[str]:
    if not DB_CONFIG:
        return None
    default_schema = DB_CONFIG.get('schema')
    allowed = DB_CONFIG.get('allowed_schemas')

    if not requested_schema:
        return default_schema

    if not allowed:
        if requested_schema.upper() == default_schema.upper():
            return default_schema
        return None

    if requested_schema.upper() in allowed:
        return requested_schema
    return None


@contextmanager
def get_db_connection(schema: Optional[str] = None):
    if not DM_PYTHON_AVAILABLE:
        raise ImportError("缺少 dmPython 库，请先安装：pip install dmPython")
    if not DB_CONFIG:
        raise ValueError("数据库配置不完整，请设置 DAMENG_HOST/USER/PASSWORD 环境变量")

    target_schema = schema or DB_CONFIG.get('schema')

    conn = dmPython.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
    )
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SET CHAR_CODE UTF-8")
            if target_schema:
                cursor.execute(f"SET SCHEMA \"{target_schema}\"")
                logger.debug("会话已切换到 Schema: %s", target_schema)
        except Exception as e:
            logger.warning("初始化会话失败: %s", e)
        finally:
            cursor.close()
        yield conn
    finally:
        conn.close()


def resp(status: str, **kwargs):
    return {
        "status": status,
        "timestamp": datetime.datetime.now().isoformat(),
        **kwargs,
    }


def _split_sql_statements(sql: str) -> List[str]:
    statements: List[str] = []
    start = 0
    i = 0
    length = len(sql)
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False

    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_single_quote:
            if ch == "'":
                if nxt == "'":
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            if ch == '"':
                if nxt == '"':
                    i += 2
                    continue
                in_double_quote = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        if ch == "'":
            in_single_quote = True
            i += 1
            continue

        if ch == '"':
            in_double_quote = True
            i += 1
            continue

        if ch == ";":
            statement = sql[start:i].strip()
            if statement:
                statements.append(statement)
            start = i + 1

        i += 1

    tail = sql[start:].strip()
    if tail:
        statements.append(tail)
    return statements


def _strip_sql_comments(sql: str) -> str:
    chars: List[str] = []
    i = 0
    length = len(sql)
    in_single_quote = False
    in_double_quote = False

    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""

        if in_single_quote:
            chars.append(ch)
            if ch == "'":
                if nxt == "'":
                    chars.append(nxt)
                    i += 2
                    continue
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            chars.append(ch)
            if ch == '"':
                if nxt == '"':
                    chars.append(nxt)
                    i += 2
                    continue
                in_double_quote = False
            i += 1
            continue

        if ch == "'":
            in_single_quote = True
            chars.append(ch)
            i += 1
            continue

        if ch == '"':
            in_double_quote = True
            chars.append(ch)
            i += 1
            continue

        if ch == "-" and nxt == "-":
            i += 2
            while i < length and sql[i] not in "\r\n":
                i += 1
            if i < length:
                chars.append(sql[i])
                i += 1
            continue

        if ch == "/" and nxt == "*":
            chars.append(" ")
            i += 2
            while i < length:
                if sql[i] == "*" and i + 1 < length and sql[i + 1] == "/":
                    i += 2
                    break
                if sql[i] in "\r\n":
                    chars.append(sql[i])
                else:
                    chars.append(" ")
                i += 1
            chars.append(" ")
            continue

        chars.append(ch)
        i += 1

    return "".join(chars)


def _path_is_under(path: Path, parent: Path) -> bool:
    try:
        os.path.commonpath([str(path), str(parent)])
    except ValueError:
        return False
    return os.path.commonpath([str(path), str(parent)]) == str(parent)


def _resolve_sql_file_path(file_path: str) -> Path:
    if not file_path or not str(file_path).strip():
        raise ValueError("SQL file path is required")

    path = Path(str(file_path).strip()).expanduser().resolve()
    if path.suffix.lower() != ".sql":
        raise ValueError("SQL file path must point to a .sql file")
    if not path.is_file():
        raise ValueError(f"SQL file path does not exist or is not a file: {path}")
    if not any(_path_is_under(path, allowed_dir) for allowed_dir in SQL_FILE_ALLOWED_DIRS):
        allowed_text = ", ".join(str(p) for p in SQL_FILE_ALLOWED_DIRS)
        raise ValueError(f"SQL file path is outside allowed directories: {allowed_text}")
    return path


def _is_identifier_start(ch: str) -> bool:
    return ch == "_" or ch.isalpha()


def _is_identifier_part(ch: str) -> bool:
    return ch == "_" or ch == "$" or ch == "#" or ch.isalnum()


def _tokenize_sql(sql: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    length = len(sql)

    while i < length:
        ch = sql[i]

        if ch.isspace():
            i += 1
            continue

        if ch == "'":
            i += 1
            value = []
            while i < length:
                if sql[i] == "'":
                    if i + 1 < length and sql[i + 1] == "'":
                        value.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                value.append(sql[i])
                i += 1
            tokens.append(("STRING", "".join(value)))
            continue

        if ch == '"':
            i += 1
            value = []
            while i < length:
                if sql[i] == '"':
                    if i + 1 < length and sql[i + 1] == '"':
                        value.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                value.append(sql[i])
                i += 1
            tokens.append(("QUOTED_IDENT", "".join(value)))
            continue

        if ch == "-" and i + 1 < length and sql[i + 1] == "-":
            end = sql.find("\n", i + 2)
            if end == -1:
                end = length
            tokens.append(("COMMENT", sql[i:end]))
            i = end
            continue

        if ch == "/" and i + 1 < length and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                end = length - 2
            tokens.append(("COMMENT", sql[i:end + 2]))
            i = end + 2
            continue

        if _is_identifier_start(ch):
            start = i
            i += 1
            while i < length and _is_identifier_part(sql[i]):
                i += 1
            tokens.append(("IDENT", sql[start:i]))
            continue

        if ch.isdigit():
            start = i
            i += 1
            while i < length and (sql[i].isdigit() or sql[i] == "."):
                i += 1
            tokens.append(("NUMBER", sql[start:i]))
            continue

        token_type = {
            ".": "DOT",
            ",": "COMMA",
            "(": "LPAREN",
            ")": "RPAREN",
            ";": "SEMICOLON",
        }.get(ch, "SYMBOL")
        tokens.append((token_type, ch))
        i += 1

    return tokens


def _token_upper(token: Token) -> str:
    return token[1].upper()


def _is_identifier(token: Token) -> bool:
    return token[0] in IDENT_TOKEN_KINDS


def _identifier_chain(tokens: List[Token], index: int) -> Tuple[List[str], int]:
    if index >= len(tokens) or not _is_identifier(tokens[index]):
        return [], index

    names = [tokens[index][1]]
    index += 1
    while (
        index + 1 < len(tokens)
        and tokens[index][0] == "DOT"
        and _is_identifier(tokens[index + 1])
    ):
        names.append(tokens[index + 1][1])
        index += 2
    return names, index


def _find_matching_paren(tokens: List[Token], index: int) -> int:
    depth = 0
    for i in range(index, len(tokens)):
        if tokens[i][0] == "LPAREN":
            depth += 1
        elif tokens[i][0] == "RPAREN":
            depth -= 1
            if depth == 0:
                return i
    return len(tokens) - 1


def _maybe_alias(tokens: List[Token], index: int) -> Tuple[Optional[str], int]:
    if index < len(tokens) and _token_upper(tokens[index]) == "AS":
        index += 1

    if index < len(tokens) and _is_identifier(tokens[index]):
        alias = tokens[index][1]
        if alias.upper() not in RESERVED_ALIAS_WORDS:
            return alias, index + 1
    return None, index


def _collect_cte_names(tokens: List[Token]) -> Set[str]:
    ctes: Set[str] = set()
    i = 0
    while i < len(tokens):
        if _token_upper(tokens[i]) != "WITH":
            i += 1
            continue

        i += 1
        if i < len(tokens) and _token_upper(tokens[i]) == "RECURSIVE":
            i += 1

        while i < len(tokens):
            if not _is_identifier(tokens[i]):
                break

            cte_name = tokens[i][1].upper()
            next_index = i + 1
            if next_index < len(tokens) and tokens[next_index][0] == "LPAREN":
                next_index = _find_matching_paren(tokens, next_index) + 1

            if next_index >= len(tokens) or _token_upper(tokens[next_index]) != "AS":
                break

            ctes.add(cte_name)
            next_index += 1
            if next_index >= len(tokens) or tokens[next_index][0] != "LPAREN":
                break

            i = _find_matching_paren(tokens, next_index) + 1
            if i < len(tokens) and tokens[i][0] == "COMMA":
                i += 1
                continue
            break

        break

    return ctes


def _collect_local_qualifiers(tokens: List[Token]) -> Set[str]:
    qualifiers = _collect_cte_names(tokens)
    i = 0
    expect_relation = False

    while i < len(tokens):
        upper = _token_upper(tokens[i])

        if upper == "COMMENT" and i + 2 < len(tokens) and _token_upper(tokens[i + 1]) == "ON":
            target_type = _token_upper(tokens[i + 2])
            if target_type in {"TABLE", "COLUMN", "INDEX"}:
                ni = i + 3
                names, ni = _identifier_chain(tokens, ni)
                for n in names:
                    qualifiers.add(n.upper())
            i += 3
            continue

        if upper == "RENAME" and i + 1 < len(tokens):
            names, ni = _identifier_chain(tokens, i + 1)
            for n in names:
                qualifiers.add(n.upper())
            if ni < len(tokens) and _token_upper(tokens[ni]) == "TO":
                ni += 1
                names2, ni = _identifier_chain(tokens, ni)
                for n in names2:
                    qualifiers.add(n.upper())
            i = ni
            continue

        if upper in JOIN_MODIFIERS:
            i += 1
            continue

        if upper in RELATION_KEYWORDS or (expect_relation and tokens[i][0] == "COMMA"):
            expect_relation = False
            i += 1

            if i < len(tokens) and tokens[i][0] == "LPAREN":
                close_index = _find_matching_paren(tokens, i)
                alias, next_index = _maybe_alias(tokens, close_index + 1)
                if alias:
                    qualifiers.add(alias.upper())
                i = next_index
                expect_relation = i < len(tokens) and tokens[i][0] == "COMMA"
                continue

            names, next_index = _identifier_chain(tokens, i)
            if names:
                qualifiers.add(names[-1].upper())
                alias, next_index = _maybe_alias(tokens, next_index)
                if alias:
                    qualifiers.add(alias.upper())
                i = next_index
                expect_relation = i < len(tokens) and tokens[i][0] == "COMMA"
                continue

        if upper == "FROM":
            expect_relation = True
        i += 1

    return qualifiers


def _outside_literal_danger(tokens: List[Token]) -> Optional[str]:
    for index, token in enumerate(tokens):
        kind, value = token
        upper = value.upper()

        if kind == "COMMENT":
            return "安全性限制：SQL 包含潜在的注入风险模式，已被拦截"

        if kind == "SEMICOLON":
            if any(t[0] not in {"COMMENT"} for t in tokens[index + 1:]):
                return "安全性限制：SQL 包含潜在的注入风险模式，已被拦截"

        if kind == "IDENT":
            if upper in {"EXEC", "EXECUTE", "CALL", "INJECTION"}:
                return "安全性限制：SQL 包含潜在的注入风险模式，已被拦截"
            if upper.startswith("XP_") or upper.startswith("SP_"):
                return "安全性限制：SQL 包含潜在的注入风险模式，已被拦截"

    return None


def _metadata_owner_filter_error(
    tokens: List[Token],
    allowed_schemas: Optional[List[str]],
) -> Optional[str]:
    references_metadata = any(
        _is_identifier(token) and _token_upper(token) in METADATA_OWNER_VIEWS
        for token in tokens
    )
    if not references_metadata:
        return None

    allowed = allowed_schemas
    default = (DB_CONFIG or {}).get('schema', '').upper()

    for i, token in enumerate(tokens):
        if not (_is_identifier(token) and _token_upper(token) == "OWNER"):
            continue
        if i + 2 >= len(tokens) or tokens[i + 2][0] != "STRING":
            continue
        if tokens[i + 1][1] not in {"=", "<", ">"}:
            continue

        found_owner = tokens[i + 2][1].strip().upper()
        if allowed:
            if found_owner not in allowed:
                return f"安全性限制：禁止查询非允许SCHEMA ({', '.join(allowed)}) 的元数据"
        elif found_owner != default:
            return f"安全性限制：禁止查询非本SCHEMA ({default}) 的元数据"

    return None


def _qualified_identifier_error(
    tokens: List[Token],
    allowed_schemas: Optional[List[str]],
) -> Optional[str]:
    local_qualifiers = _collect_local_qualifiers(tokens)
    default = (DB_CONFIG or {}).get('schema', '').upper()

    checked = set()
    for i, token in enumerate(tokens[:-2]):
        if not _is_identifier(token):
            continue
        if tokens[i + 1][0] != "DOT" or not _is_identifier(tokens[i + 2]):
            continue

        qualifier = token[1]
        qualifier_upper = qualifier.upper()
        if qualifier_upper in checked:
            continue
        checked.add(qualifier_upper)

        if qualifier_upper in local_qualifiers:
            continue

        if allowed_schemas:
            if qualifier_upper not in allowed_schemas:
                return f"安全性限制：禁止跨SCHEMA操作，'{qualifier}' 不在允许列表中"
        elif qualifier_upper != default:
            return f"安全性限制：禁止跨SCHEMA操作。仅允许操作模式: {default}"

    return None


BLOCKED_STATEMENT_STARTS = {"GRANT", "REVOKE"}
ALLOWED_CREATE_TYPES = {"TABLE", "INDEX", "SEQUENCE", "VIEW"}
ALLOWED_ALTER_TYPES = {"TABLE", "INDEX", "SEQUENCE", "VIEW"}
ALLOWED_DROP_TYPES = {"TABLE", "INDEX", "SEQUENCE", "VIEW"}


def _ddl_dcl_check(tokens: List[Token]) -> Optional[str]:
    if not tokens:
        return None
    first_upper = _token_upper(tokens[0])

    if first_upper in BLOCKED_STATEMENT_STARTS:
        return f"安全性限制：禁止执行 {first_upper} 操作，该语句已被拦截"

    if first_upper == "CREATE":
        second = _token_upper(tokens[1]) if len(tokens) > 1 else ""
        if second not in ALLOWED_CREATE_TYPES:
            return f"安全性限制：禁止执行 CREATE {second} 操作，仅允许 CREATE TABLE / CREATE INDEX"

    if first_upper == "ALTER":
        second = _token_upper(tokens[1]) if len(tokens) > 1 else ""
        if second not in ALLOWED_ALTER_TYPES:
            return f"安全性限制：禁止执行 ALTER {second} 操作，仅允许 ALTER TABLE / ALTER INDEX"

    if first_upper == "DROP":
        second = _token_upper(tokens[1]) if len(tokens) > 1 else ""
        if second not in ALLOWED_DROP_TYPES:
            return f"安全性限制：禁止执行 DROP {second} 操作，仅允许 DROP TABLE / DROP INDEX"

    return None


def _validate_sql_security(sql: str, allowed_schemas: Optional[List[str]]) -> Optional[str]:
    tokens = _tokenize_sql(sql)

    ddl_err = _ddl_dcl_check(tokens)
    if ddl_err:
        logger.warning("SQL 安全拦截: %s | SQL: %.200s", ddl_err, sql)
        return ddl_err

    dangerous_err = _outside_literal_danger(tokens)
    if dangerous_err:
        logger.warning("SQL 安全拦截: %s | SQL: %.200s", dangerous_err, sql)
        return dangerous_err

    metadata_err = _metadata_owner_filter_error(tokens, allowed_schemas)
    if metadata_err:
        return metadata_err

    qualified_err = _qualified_identifier_error(tokens, allowed_schemas)
    if qualified_err:
        return qualified_err

    return None


def _validate_column_comment_statement(
    statement: str,
    allowed_schemas: Optional[List[str]],
) -> Optional[str]:
    tokens = _tokenize_sql(statement)
    dangerous_err = _outside_literal_danger(tokens)
    if dangerous_err:
        return dangerous_err

    if len(tokens) < 8:
        return "仅允许 COMMENT ON COLUMN 表名.字段名 IS '注释内容' 语句"

    if (
        _token_upper(tokens[0]) != "COMMENT"
        or _token_upper(tokens[1]) != "ON"
        or _token_upper(tokens[2]) != "COLUMN"
    ):
        return "仅允许批量执行 COMMENT ON COLUMN 字段注释语句"

    names, next_index = _identifier_chain(tokens, 3)
    if len(names) not in {2, 3}:
        return "字段注释目标必须是 表名.字段名 或 SCHEMA.表名.字段名"

    if next_index >= len(tokens) or _token_upper(tokens[next_index]) != "IS":
        return "字段注释语句缺少 IS 关键字"

    if next_index + 1 >= len(tokens) or tokens[next_index + 1][0] != "STRING":
        return "字段注释内容必须使用字符串字面量"

    if next_index + 2 != len(tokens):
        return "字段注释语句包含不允许的额外内容"

    if len(names) == 3:
        schema_name = names[0].upper()
        if allowed_schemas:
            if schema_name not in allowed_schemas:
                return f"安全性限制：禁止跨SCHEMA操作，'{names[0]}' 不在允许列表中"
        else:
            default = (DB_CONFIG or {}).get('schema', '').upper()
            if schema_name != default:
                return f"安全性限制：禁止跨SCHEMA操作。仅允许操作模式: {default}"

    return None


def _check_read_only(sql: str) -> Optional[str]:
    if not DB_CONFIG or not DB_CONFIG.get('read_only'):
        return None
    sql_upper = sql.upper().strip()
    first_word = sql_upper.split()[0] if sql_upper.split() else ""
    if first_word not in READONLY_KEYWORDS:
        return f"只读模式已开启，仅允许查询操作（SELECT/WITH/EXPLAIN/SHOW/DESCRIBE），当前语句类型: {first_word}"
    return None


@mcp.tool()
def test_connection() -> Dict[str, Any]:
    """测试数据库连接状态"""
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")
    try:
        with get_db_connection():
            schema_info = DB_CONFIG.get('schema', '未指定')
            read_only = "是" if DB_CONFIG.get('read_only') else "否"
            allowed = DB_CONFIG.get('allowed_schemas')
            allowed_info = ', '.join(allowed) if allowed else schema_info
            return resp(
                "success",
                message="数据库连接成功",
                schema=schema_info,
                allowed_schemas=allowed_info,
                read_only=read_only,
            )
    except Exception as e:
        logger.error("数据库连接测试失败: %s", e)
        return resp("error", message=str(e))


@mcp.tool()
def batch_comment_columns_sql(
    sql: str,
    stop_on_error: bool = True,
) -> Dict[str, Any]:
    """批量执行字段注释 SQL，仅允许 COMMENT ON COLUMN 语句

    参数:
        sql: 多条 COMMENT ON COLUMN 语句，可用分号分隔
        stop_on_error: 执行阶段遇到错误是否停止
    """
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    schema = DB_CONFIG.get('schema')
    if not schema:
        return resp("error", message="安全性错误：必须设置 DAMENG_SCHEMA 环境变量")

    if DB_CONFIG.get('read_only'):
        return resp("error", message="只读模式已开启，禁止执行字段注释修改")

    statements = _split_sql_statements(sql)
    if not statements:
        return resp("error", message="未提供可执行的字段注释 SQL")

    for index, statement in enumerate(statements):
        err = _validate_column_comment_statement(statement, DB_CONFIG.get('allowed_schemas'))
        if err:
            return resp(
                "error",
                message=err,
                failed_index=index,
                statement_count=len(statements),
            )

    results = []
    has_error = False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SET SCHEMA \"{schema}\"")

            for index, statement in enumerate(statements):
                try:
                    cursor.execute(statement)
                    results.append(
                        {
                            "statement_index": index,
                            "status": "success",
                            "affected_rows": cursor.rowcount,
                        }
                    )
                except Exception as e:
                    logger.error("字段注释语句执行失败: %s", e)
                    has_error = True
                    results.append(
                        {
                            "statement_index": index,
                            "status": "error",
                            "message": str(e),
                        }
                    )
                    if stop_on_error:
                        break

        return resp(
            "error" if has_error and stop_on_error else "success",
            statement_count=len(statements),
            results=results,
        )
    except Exception as e:
        logger.error("批量字段注释执行失败: %s", e)
        return resp("error", message=str(e))


@mcp.tool()
def execute_sql_file(
    file_path: str,
    encoding: str = "utf-8",
    stop_on_error: bool = True,
    fetch_results: bool = False,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """读取并执行 SQL 文件，用于处理超长 SQL。

    文件路径必须位于 DAMENG_SQL_FILE_ALLOWED_DIRS 白名单目录内。
    文件中的 SQL 注释会在校验和执行前剥离，字符串字面量内的内容不受影响。
    """
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    schema = DB_CONFIG.get('schema')
    if not schema:
        return resp("error", message="安全性错误：必须设置 DAMENG_SCHEMA 环境变量")

    try:
        sql_path = _resolve_sql_file_path(file_path)
        sql_text = sql_path.read_text(encoding=encoding)
    except Exception as e:
        return resp("error", message=str(e))

    file_size = sql_path.stat().st_size
    stripped_sql = _strip_sql_comments(sql_text)
    statements = _split_sql_statements(stripped_sql)
    if not statements:
        return resp(
            "error",
            message="SQL 文件中未找到可执行的 SQL 语句",
            file_path=str(sql_path),
            file_size=file_size,
            statement_count=0,
        )

    for index, statement in enumerate(statements):
        read_only_err = _check_read_only(statement)
        if read_only_err:
            return resp(
                "error",
                message=read_only_err,
                failed_index=index,
                file_path=str(sql_path),
                file_size=file_size,
                statement_count=len(statements),
            )

        security_err = _validate_sql_security(statement, DB_CONFIG.get('allowed_schemas'))
        if security_err:
            return resp(
                "error",
                message=security_err,
                failed_index=index,
                file_path=str(sql_path),
                file_size=file_size,
                statement_count=len(statements),
            )

    results = []
    has_error = False
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SET SCHEMA \"{schema}\"")

            for index, statement in enumerate(statements):
                sql_to_execute = statement
                statement_upper = statement.upper().strip()
                is_select = statement_upper.startswith(('SELECT', 'WITH'))

                if is_select and fetch_results and (limit is not None or offset is not None):
                    effective_limit = limit if limit is not None else 1000
                    effective_offset = offset if offset is not None else 0
                    sql_to_execute = f"SELECT * FROM ({statement}) LIMIT {effective_limit} OFFSET {effective_offset}"

                try:
                    cursor.execute(sql_to_execute)
                    item = {
                        "statement_index": index,
                        "status": "success",
                    }
                    if fetch_results and is_select:
                        rows = cursor.fetchall()
                        cols = [d[0] for d in cursor.description] if cursor.description else []
                        item["data"] = [dict(zip(cols, r)) for r in rows]
                        item["count"] = len(item["data"])
                        if limit is not None or offset is not None:
                            item["pagination"] = {
                                "limit": limit,
                                "offset": offset,
                            }
                    else:
                        item["affected_rows"] = cursor.rowcount
                    results.append(item)
                except Exception as e:
                    logger.error("SQL 文件语句执行失败: %s", e)
                    has_error = True
                    results.append(
                        {
                            "statement_index": index,
                            "status": "error",
                            "message": str(e),
                        }
                    )
                    if stop_on_error:
                        break

        return resp(
            "error" if has_error and stop_on_error else "success",
            file_path=str(sql_path),
            file_size=file_size,
            statement_count=len(statements),
            results=results,
        )
    except Exception as e:
        logger.error("SQL 文件执行失败: %s", e)
        return resp(
            "error",
            message=str(e),
            file_path=str(sql_path),
            file_size=file_size,
            statement_count=len(statements),
        )


@mcp.tool()
def get_sql_file_allowed_dirs() -> Dict[str, Any]:
    """获取 execute_sql_file 允许读取的 SQL 文件目录。"""
    directories = []
    recommended_dir = None

    for allowed_dir in SQL_FILE_ALLOWED_DIRS:
        exists = allowed_dir.exists()
        is_dir = allowed_dir.is_dir()
        writable = exists and is_dir and os.access(allowed_dir, os.W_OK)
        item = {
            "path": str(allowed_dir),
            "exists": exists,
            "is_dir": is_dir,
            "writable": writable,
        }
        directories.append(item)
        if recommended_dir is None and writable:
            recommended_dir = str(allowed_dir)

    return resp(
        "success",
        allowed_dirs=[str(path) for path in SQL_FILE_ALLOWED_DIRS],
        directories=directories,
        recommended_dir=recommended_dir,
        required_extension=".sql",
        path_separator=os.pathsep,
        usage="将 SQL 内容保存为 .sql 文件到 recommended_dir 或任一 writable=true 的目录后，再调用 execute_sql_file(file_path=完整文件路径)",
    )


@mcp.tool()
def execute_sql(
    sql: str,
    fetch_results: bool = True,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """执行 SQL 语句（强制限定配置下的SCHEMA操作）

    参数:
        sql: 要执行的 SQL 语句
        fetch_results: 是否返回查询结果（默认 True）
        limit: 限制返回的行数，用于分页（可选）
        offset: 跳过的行数，用于分页（可选）
    """
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    schema = DB_CONFIG.get('schema')
    if not schema:
        return resp("error", message="安全性错误：必须设置 DAMENG_SCHEMA 环境变量")

    read_only_err = _check_read_only(sql)
    if read_only_err:
        return resp("error", message=read_only_err)

    security_err = _validate_sql_security(sql, DB_CONFIG.get('allowed_schemas'))
    if security_err:
        return resp("error", message=security_err)

    sql_upper = sql.upper().strip()
    is_select = sql_upper.startswith(('SELECT', 'WITH'))

    if is_select and fetch_results and (limit is not None or offset is not None):
        effective_limit = limit if limit is not None else 1000
        effective_offset = offset if offset is not None else 0
        sql = f"SELECT * FROM ({sql}) LIMIT {effective_limit} OFFSET {effective_offset}"
        logger.info("分页查询: LIMIT=%d OFFSET=%d", effective_limit, effective_offset)

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SET SCHEMA \"{schema}\"")
            cursor.execute(sql)
            if fetch_results and is_select:
                if limit is None and offset is None:
                    res = cursor.fetchall()
                else:
                    res = cursor.fetchall()
                cols = [d[0] for d in cursor.description] if cursor.description else []
                data = [dict(zip(cols, r)) for r in res]
                result = resp("success", data=data, count=len(data))
                if limit is not None or offset is not None:
                    result["pagination"] = {
                        "limit": limit,
                        "offset": offset,
                    }
                return result
            return resp("success", affected_rows=cursor.rowcount)
    except Exception as e:
        logger.error("SQL 执行失败: %s", e)
        return resp("error", message=str(e))


@mcp.tool()
def list_tables(schema: Optional[str] = None) -> Dict[str, Any]:
    """查询指定SCHEMA下的所有表，不指定则查询默认SCHEMA"""
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    target_schema = _resolve_schema(schema)
    if target_schema is None:
        allowed = DB_CONFIG.get('allowed_schemas') or [DB_CONFIG.get('schema', '')]
        return resp("error", message=f"安全性限制：禁止查询非允许SCHEMA的数据。允许的SCHEMA: {', '.join(allowed)}")

    try:
        with get_db_connection(schema=target_schema) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT TABLE_NAME FROM USER_TABLES ORDER BY TABLE_NAME")
            res = cursor.fetchall()
            tables = [r[0] for r in res]
            return resp("success", data=tables, count=len(tables), schema=target_schema)
    except Exception as e:
        logger.error("列出表失败: %s", e)
        return resp("error", message=str(e))


@mcp.tool()
def count_tables(schema: Optional[str] = None) -> Dict[str, Any]:
    """统计指定SCHEMA下的表数量，不指定则统计默认SCHEMA"""
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    target_schema = _resolve_schema(schema)
    if target_schema is None:
        allowed = DB_CONFIG.get('allowed_schemas') or [DB_CONFIG.get('schema', '')]
        return resp("error", message=f"安全性限制：禁止统计非允许SCHEMA的数据。允许的SCHEMA: {', '.join(allowed)}")

    try:
        with get_db_connection(schema=target_schema) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM USER_TABLES")
            res = cursor.fetchone()
            return resp("success", count=res[0] if res else 0, schema=target_schema)
    except Exception as e:
        logger.error("统计表数量失败: %s", e)
        return resp("error", message=str(e))


@mcp.tool()
def get_current_schema() -> Dict[str, Any]:
    """获取当前配置的数据库的SCHEMA及允许的SCHEMA列表"""
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")
    schema = DB_CONFIG.get('schema')
    if not schema:
        return resp("error", message="安全性错误：尚未配置SCHEMA")
    allowed = DB_CONFIG.get('allowed_schemas')
    return resp(
        "success",
        schema=schema,
        allowed_schemas=allowed if allowed else [schema],
        read_only=DB_CONFIG.get('read_only', False),
    )


@mcp.tool()
def switch_schema(schema: str) -> Dict[str, Any]:
    """切换当前操作的SCHEMA（仅在配置了DAMENG_ALLOWED_SCHEMAS时可用）"""
    if not DB_CONFIG:
        return resp("error", message="缺失环境变量配置")

    allowed = DB_CONFIG.get('allowed_schemas')
    if not allowed:
        return resp("error", message="未启用多SCHEMA模式。请设置 DAMENG_ALLOWED_SCHEMAS 环境变量以启用")

    if schema.upper() not in allowed:
        return resp("error", message=f"安全性限制：'{schema}' 不在允许的SCHEMA列表中。允许: {', '.join(allowed)}")

    DB_CONFIG['schema'] = schema
    logger.info("SCHEMA 已切换为: %s", schema)
    return resp("success", schema=schema, message=f"已切换到SCHEMA: {schema}")


def main():
    if not DB_CONFIG:
        logger.error("数据库配置缺失，请确保 DAMENG_HOST / DAMENG_USER / DAMENG_PASSWORD 环境变量已设置")
        return

    logger.info(
        "达梦 MCP 服务器启动 | Schema: %s | 只读: %s | 允许Schema: %s",
        DB_CONFIG.get('schema'),
        "是" if DB_CONFIG.get('read_only') else "否",
        ', '.join(DB_CONFIG['allowed_schemas']) if DB_CONFIG.get('allowed_schemas') else DB_CONFIG.get('schema'),
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
