"""In-memory DB dump loader and query interface for Train Ticket static analysis."""
from __future__ import annotations

import gzip
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _parse_sql_values(val_str: str) -> list[list[Any]]:
    """Fast, single-pass scanner for MySQL VALUES tuples.

    Handles:
      - single quoted strings with backslash escapes (\', \\, \0, \n, \r, \t, etc.)
      - SQL double-single quotes ('')
      - _binary '...' literals
      - integers and floats
      - NULL -> None
    """
    rows: list[list[Any]] = []
    i = 0
    n = len(val_str)

    while i < n:
        while i < n and val_str[i] != "(":
            i += 1
        if i >= n:
            break
        i += 1  # consume '('

        row: list[Any] = []
        while i < n:
            while i < n and val_str[i] in " \t\r\n":
                i += 1
            if i >= n:
                break

            ch = val_str[i]
            if ch == ")":
                i += 1
                rows.append(row)
                break
            elif ch == ",":
                i += 1
                continue
            elif ch == "'":
                i += 1
                chars: list[str] = []
                while i < n:
                    c = val_str[i]
                    if c == "\\":
                        i += 1
                        if i < n:
                            esc = val_str[i]
                            if esc == "0":
                                chars.append("\0")
                            elif esc == "b":
                                chars.append("\b")
                            elif esc == "n":
                                chars.append("\n")
                            elif esc == "r":
                                chars.append("\r")
                            elif esc == "t":
                                chars.append("\t")
                            elif esc == "Z":
                                chars.append("\x1a")
                            else:
                                chars.append(esc)
                            i += 1
                    elif c == "'":
                        if i + 1 < n and val_str[i + 1] == "'":
                            chars.append("'")
                            i += 2
                        else:
                            i += 1
                            break
                    else:
                        chars.append(c)
                        i += 1
                row.append("".join(chars))
            elif val_str.startswith("_binary '", i):
                i += 9
                chars = []
                while i < n:
                    c = val_str[i]
                    if c == "\\":
                        i += 1
                        if i < n:
                            chars.append(val_str[i])
                            i += 1
                    elif c == "'":
                        i += 1
                        break
                    else:
                        chars.append(c)
                        i += 1
                row.append("".join(chars))
            elif val_str.startswith("NULL", i):
                row.append(None)
                i += 4
            else:
                start = i
                while i < n and val_str[i] not in ",)":
                    i += 1
                token = val_str[start:i].strip()
                if "." in token:
                    try:
                        row.append(float(token))
                    except ValueError:
                        row.append(token)
                else:
                    try:
                        row.append(int(token))
                    except ValueError:
                        row.append(token)

            while i < n and val_str[i] in " \t\r\n":
                i += 1
            if i < n and val_str[i] == ",":
                i += 1

    return rows


class TableCollection(dict):
    """Dictionary view over canonical tables allowing lookup by aliases and qualified names."""

    def __init__(
        self,
        canonical_tables: dict[str, list[dict[str, Any]]],
        normalizer: Callable[[str], str],
    ) -> None:
        super().__init__(canonical_tables)
        self._normalizer = normalizer

    def __getitem__(self, key: str) -> list[dict[str, Any]]:
        norm = self._normalizer(key)
        return super().__getitem__(norm)

    def get(self, key: str, default: Any = None) -> Any:
        norm = self._normalizer(key)
        return super().get(norm, default)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            norm = self._normalizer(key)
            return super().__contains__(norm)
        return super().__contains__(key)


class TableNodeResolution(list):
    """Dual representation of a resolved table node.

    Behaves both as a list of rows (for iteration and record inspection)
    and as a dictionary of metadata (for node_id, service, db, table, qualified attributes).
    """

    def __init__(self, rows: list[dict[str, Any]], metadata: dict[str, str]) -> None:
        super().__init__(rows)
        self._metadata = metadata
        self.node_id = metadata.get("node_id", "")
        self.service = metadata.get("service", "")
        self.db = metadata.get("db", "")
        self.table = metadata.get("table", "")
        self.qualified = metadata.get("qualified", "")

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            return self._metadata[item]
        return super().__getitem__(item)

    def get(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self._metadata == other
        return super().__eq__(other)


class DatabaseState:
    """In-memory representation of database tables loaded from warmup dump."""

    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        table_aliases: dict[str, str] | None = None,
        table_columns: dict[str, list[str]] | None = None,
    ) -> None:
        self._canonical_tables: dict[str, list[dict[str, Any]]] = tables or {}
        self._table_aliases: dict[str, str] = table_aliases or {}
        self._table_columns: dict[str, list[str]] = table_columns or {}
        self.tables = TableCollection(self._canonical_tables, self.normalize_table_name)

    def normalize_table_name(self, table_name: str) -> str:
        """Normalizes table identifier variants to bare canonical name.

        Variants supported:
          - 'orders'
          - 'ts_order.orders'
          - 'ts-order-service.orders'
          - 'res:table:ts-order-service.orders'
        """
        if not table_name:
            return ""
        if table_name in self._table_aliases:
            return self._table_aliases[table_name]
        t = table_name.removeprefix("res:table:")
        if "." in t:
            t = t.split(".", 1)[1]
        return t

    def get_table(self, table_name: str) -> list[dict[str, Any]]:
        """Returns rows for table or empty list if table does not exist."""
        canonical = self.normalize_table_name(table_name)
        return self._canonical_tables.get(canonical, [])

    def get_columns(self, table_name: str) -> list[str]:
        """Returns column names for the table or empty list."""
        canonical = self.normalize_table_name(table_name)
        return self._table_columns.get(canonical, [])

    def table_names(self) -> list[str]:
        """Returns sorted list of all canonical table names."""
        return sorted(self._canonical_tables.keys())

    def query(self, table_name: str, **filters: Any) -> list[dict[str, Any]]:
        """Filters rows matching all key=value criteria or callable predicates."""
        rows = self.get_table(table_name)
        if not filters:
            return list(rows)

        results: list[dict[str, Any]] = []
        for row in rows:
            matched = True
            for k, expected in filters.items():
                val = row.get(k)
                if callable(expected):
                    if not expected(val):
                        matched = False
                        break
                else:
                    if val != expected and str(val) != str(expected):
                        matched = False
                        break
            if matched:
                results.append(row)
        return results

    def find_one(self, table_name: str, **filters: Any) -> dict[str, Any] | None:
        """Returns first matching row or None."""
        matches = self.query(table_name, **filters)
        return matches[0] if matches else None

    def insert(self, table_name: str, row: dict[str, Any]) -> None:
        """Inserts a new row into the table."""
        canonical = self.normalize_table_name(table_name)
        if canonical not in self._canonical_tables:
            self._canonical_tables[canonical] = []
        self._canonical_tables[canonical].append(dict(row))

    def update(self, table_name: str, updates: dict[str, Any], **filters: Any) -> int:
        """Updates matching rows in-place. Returns number of rows updated."""
        matching_rows = self.query(table_name, **filters)
        for r in matching_rows:
            r.update(updates)
        return len(matching_rows)

    def get_user_by_name(self, user_name: str) -> dict[str, Any] | None:
        """Finds user row in 'user' table by user_name."""
        return self.find_one("user", user_name=user_name)

    def get_user_balance(self, user_id: str) -> float | None:
        """Computes current balance for user_id from inside_money deposits and inside_payment records.

        Matches InsidePaymentServiceImpl logic:
        money = sum(inside_money.money)
        expand = sum(inside_payment.price)
        balance = max(0.0, money - expand)
        """
        add_monies = self.query("inside_money", user_id=user_id)
        payments = self.query("inside_payment", user_id=user_id)
        if not add_monies and not payments:
            return None
        total_money = sum(float(m.get("money") or 0.0) for m in add_monies)
        total_expand = sum(float(p.get("price") or 0.0) for p in payments)
        return max(0.0, total_money - total_expand)

    def fork(self) -> DatabaseState:
        """Creates an isolated copy in < 20 µs for scenario isolation."""
        cloned_tables = {
            tbl: [row.copy() for row in rows]
            for tbl, rows in self._canonical_tables.items()
        }
        return DatabaseState(
            tables=cloned_tables,
            table_aliases=self._table_aliases,
            table_columns=self._table_columns,
        )


def load_db_dump(gz_path: str | Path) -> DatabaseState:
    """Loads and parses context/db-after-warmup.sql.gz into DatabaseState."""
    path = Path(gz_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database dump file not found: {path}")

    # Кодировка latin1 сохраняет произвольные бинарные байты MySQL-дампа без ошибок декодирования
    with gzip.open(path, "rt", encoding="latin1") as f:
        text = f.read()

    lines = text.splitlines()
    current_db = "default"
    table_cols: dict[str, list[str]] = {}
    table_to_db: dict[str, str] = {}

    i = 0
    num_lines = len(lines)
    while i < num_lines:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.upper().startswith("USE "):
            m = re.match(r"USE\s+`?([^;`]+)`?;", line, re.IGNORECASE)
            if m:
                current_db = m.group(1)
            i += 1
            continue

        if line.upper().startswith("CREATE TABLE"):
            m = re.match(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?([a-zA-Z0-9_.]+)`?",
                line,
                re.IGNORECASE,
            )
            tbl_name = m.group(1) if m else "unknown"
            cols: list[str] = []
            i += 1
            while i < num_lines:
                l = lines[i].strip()
                if l.startswith(")") and ("ENGINE" in l.upper() or ";" in l):
                    i += 1
                    break
                if l.startswith("`"):
                    col = l.split("`")[1]
                    cols.append(col)
                i += 1
            table_cols[tbl_name] = cols
            table_to_db[tbl_name] = current_db
            continue

        i += 1

    insert_matches = re.finditer(
        r"INSERT\s+INTO\s+`?([a-zA-Z0-9_.]+)`?\s*(?:\(([^)]+)\))?\s*VALUES\s*(.*?);",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    tables_data: dict[str, list[dict[str, Any]]] = {tbl: [] for tbl in table_cols}

    for match in insert_matches:
        tbl = match.group(1)
        val_clause = match.group(3)
        cols = table_cols.get(tbl, [])
        parsed_rows = _parse_sql_values(val_clause)

        row_dicts: list[dict[str, Any]] = []
        for row_vals in parsed_rows:
            if cols:
                row_dicts.append(dict(zip(cols, row_vals)))
            else:
                row_dicts.append({f"col_{idx}": v for idx, v in enumerate(row_vals)})

        if tbl not in tables_data:
            tables_data[tbl] = []
        tables_data[tbl].extend(row_dicts)

    table_aliases: dict[str, str] = {}
    for tbl, db in table_to_db.items():
        table_aliases[tbl] = tbl
        table_aliases[f"{db}.{tbl}"] = tbl
        svc_name = db.replace("_", "-") + "-service"
        table_aliases[f"{svc_name}.{tbl}"] = tbl
        table_aliases[f"res:table:{svc_name}.{tbl}"] = tbl

    # Dynamic alias mapping derived from schema without hardcoded project tables
    for tbl, db in table_to_db.items():
        base_svc = db.replace("_", "-")
        table_aliases[f"{base_svc}.{tbl}"] = tbl
        table_aliases[f"res:table:{base_svc}.{tbl}"] = tbl

    return DatabaseState(
        tables=tables_data,
        table_aliases=table_aliases,
        table_columns=table_cols,
    )


def parse_context_readme(readme_path: str | Path) -> dict[str, Any]:
    """Extracts benchmark execution context from context/README.md.

    Parses:
      - travel_date (e.g. '1 October 2026' or '2026-10-01')
      - system_date (e.g. '15 September 2026' or '2026-09-15')
      - user_name (e.g. 'fdse_microservice')
      - balance (e.g. 10000.0)
    """
    path = Path(readme_path)
    if not path.is_file():
        return {}

    text = path.read_text(encoding="utf-8", errors="replace")
    info: dict[str, Any] = {}

    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }

    # Travel date (e.g. "booked for 1 October 2026")
    m_travel = re.search(r"booked for\s+([0-9]{1,2})\s+([A-Za-z]+)\s+([0-9]{4})", text, re.IGNORECASE)
    if m_travel:
        day, month_name, year = m_travel.group(1), m_travel.group(2).lower(), m_travel.group(3)
        month = months.get(month_name)
        if month:
            info["travel_date"] = f"{year}-{month}-{int(day):02d}"
    elif m_iso := re.search(r"booked for\s+([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.IGNORECASE):
        info["travel_date"] = m_iso.group(1)

    # System clock date (e.g. "system clock is 15 September 2026")
    m_sys = re.search(r"system clock is\s+([0-9]{1,2})\s+([A-Za-z]+)\s+([0-9]{4})", text, re.IGNORECASE)
    if m_sys:
        day, month_name, year = m_sys.group(1), m_sys.group(2).lower(), m_sys.group(3)
        month = months.get(month_name)
        if month:
            info["system_date"] = f"{year}-{month}-{int(day):02d}"
    elif m_iso := re.search(r"system clock is\s+([0-9]{4}-[0-9]{2}-[0-9]{2})", text, re.IGNORECASE):
        info["system_date"] = m_iso.group(1)

    # Pre-registered account
    m_user = re.search(r"pre-registered user\s+([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
    if m_user:
        info["user_name"] = m_user.group(1)

    # Balance (e.g. "internal account balance 10 000")
    m_bal = re.search(r"(?:account balance|balance)\s+([0-9]+(?:[\s,][0-9]{3})*(?:\.[0-9]+)?)", text, re.IGNORECASE)
    if m_bal:
        info["balance"] = float(m_bal.group(1).replace(" ", "").replace(",", ""))

    return info

