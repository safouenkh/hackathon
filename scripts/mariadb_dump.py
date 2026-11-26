"""Parse a phpMyAdmin / MariaDB SQL dump without executing it.

Extracts, per table: column definitions, rows from INSERT statements, and the
PRIMARY / UNIQUE / plain keys declared by ALTER TABLE. Values are typed as in
the dump: int, Decimal (exact, never float), str, or None for NULL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

_ESCAPES = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "b": "\b"}
_CREATE_RE = re.compile(r"CREATE TABLE `(\w+)` \((.*?)\n\) ENGINE", re.S)
_COLUMN_RE = re.compile(r"^\s*`(\w+)` (.+?),?$", re.M)
_INSERT_RE = re.compile(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES")
_ALTER_RE = re.compile(r"ALTER TABLE `(\w+)`\n(.*?);", re.S)
_TOKEN_RE = re.compile(r"[^,)]+")
_INT_RE = re.compile(r"-?\d+")


@dataclass
class Column:
    name: str
    mysql_type: str
    nullable: bool


@dataclass
class Table:
    name: str
    columns: list[Column]
    rows: list[list] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    unique_keys: list[list[str]] = field(default_factory=list)
    indexes: list[list[str]] = field(default_factory=list)


def pg_type(mysql_type: str) -> str:
    """Map a MariaDB column type to the PostgreSQL type used for the copy."""
    t = mysql_type.strip().lower()
    base = re.match(r"\w+", t).group()
    unsigned = "unsigned" in t
    if base == "bigint":
        return "bigint"
    if base == "int":
        return "bigint" if unsigned else "integer"
    if base in ("tinyint", "smallint"):
        return "smallint"
    if base == "decimal":
        return "numeric" + re.search(r"\(\d+,\d+\)", t).group().replace(" ", "")
    if base == "varchar":
        return "varchar" + re.search(r"\(\d+\)", t).group()
    if base in ("text", "mediumtext", "longtext"):
        return "text"
    if base in ("date", "timestamp"):
        return base
    raise ValueError(f"type MariaDB non géré : {mysql_type!r}")


def _parse_columns(body: str) -> list[Column]:
    cols = []
    for name, rest in _COLUMN_RE.findall(body):
        mysql_type = re.match(r"\w+(\([\d,]+\))?( UNSIGNED)?", rest).group()
        cols.append(Column(name, mysql_type, "NOT NULL" not in rest))
    return cols


def _parse_values(s: str, i: int) -> tuple[list[list], int]:
    """Parse `(..),(..);` starting at s[i]. Return the rows and the index after ';'."""
    rows: list[list] = []
    n = len(s)
    while True:
        while s[i] in " \r\n\t,":
            i += 1
        if s[i] == ";":
            return rows, i + 1
        if s[i] != "(":
            raise ValueError(f"tuple attendu à la position {i}: {s[i:i + 40]!r}")
        i += 1
        row: list = []
        while True:
            while s[i] in " \r\n\t":
                i += 1
            if s[i] == "'":
                i += 1
                buf = []
                while True:
                    c = s[i]
                    if c == "\\":
                        buf.append(_ESCAPES.get(s[i + 1], s[i + 1]))
                        i += 2
                    elif c == "'":
                        if i + 1 < n and s[i + 1] == "'":
                            buf.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        buf.append(c)
                        i += 1
                row.append("".join(buf))
            else:
                m = _TOKEN_RE.match(s, i)
                tok = m.group().strip()
                i = m.end()
                if tok.upper() == "NULL":
                    row.append(None)
                elif _INT_RE.fullmatch(tok):
                    row.append(int(tok))
                else:
                    row.append(Decimal(tok))
            while s[i] in " \r\n\t":
                i += 1
            if s[i] == ",":
                i += 1
                continue
            if s[i] != ")":
                raise ValueError(f"')' attendu à la position {i}: {s[i:i + 40]!r}")
            i += 1
            rows.append(row)
            break


def _key_columns(spec: str) -> list[str]:
    return re.findall(r"`(\w+)`", spec)


def parse_dump(text: str) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for m in _CREATE_RE.finditer(text):
        tables[m.group(1)] = Table(m.group(1), _parse_columns(m.group(2)))

    for m in _INSERT_RE.finditer(text):
        table = tables[m.group(1)]
        insert_cols = _key_columns(m.group(2))
        if insert_cols != [c.name for c in table.columns]:
            raise ValueError(f"colonnes de l'INSERT différentes du CREATE pour {table.name}")
        rows, _ = _parse_values(text, m.end())
        for r in rows:
            if len(r) != len(insert_cols):
                raise ValueError(f"ligne de {len(r)} valeurs pour {len(insert_cols)} colonnes dans {table.name}")
        table.rows.extend(rows)

    for m in _ALTER_RE.finditer(text):
        table = tables[m.group(1)]
        for line in m.group(2).splitlines():
            line = line.strip().rstrip(",")
            if line.startswith("ADD PRIMARY KEY"):
                table.primary_key = _key_columns(line)
            elif line.startswith("ADD UNIQUE KEY"):
                table.unique_keys.append(_key_columns(line.split("(", 1)[1]))
            elif line.startswith("ADD KEY"):
                table.indexes.append(_key_columns(line.split("(", 1)[1]))
    return tables
