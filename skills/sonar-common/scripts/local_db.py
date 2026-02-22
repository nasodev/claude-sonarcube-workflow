#!/usr/bin/env python3
"""
local_db.py - SQLite 로컬 상태 DB 관리 모듈

프로젝트별 이슈 상태와 실행 이력을 SQLite에 저장/조회합니다.

Usage (CLI):
    python local_db.py init                  # DB 초기화
    python local_db.py status                # 전체 이슈 상태 목록
    python local_db.py get <sonarqube_key>   # 단일 이슈 JSON 출력
    python local_db.py export                # 전체 데이터 sync용 JSON 출력

Usage (Python API):
    from local_db import init_db, upsert_issue, get_issues, update_status
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def get_db_path() -> str:
    """
    sonar.db 경로를 반환합니다.

    우선순위:
      1. SONAR_PROJECT_DIR 환경변수 하위 sonar.db
      2. CWD/sonar.db
    """
    project_dir = os.environ.get("SONAR_PROJECT_DIR")
    if project_dir:
        return os.path.join(project_dir, "sonar.db")
    return os.path.join(os.getcwd(), "sonar.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_GROUPS_DDL = """\
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    rule        TEXT,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
"""

_ISSUES_DDL = """\
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sonarqube_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'NEW',
    group_id INTEGER REFERENCES groups(id),
    severity TEXT,
    type TEXT,
    rule TEXT,
    file_path TEXT,
    line INTEGER,
    message TEXT,
    clean_code_attribute TEXT,
    software_quality TEXT,
    assignee TEXT,
    jira_key TEXT,
    report_path TEXT,
    worktree_path TEXT,
    analyze_attempts INTEGER DEFAULT 0,
    develop_attempts INTEGER DEFAULT 0,
    synced_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

_EXECUTIONS_DDL = """\
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sonarqube_key TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_UPDATED_AT_TRIGGER = """\
CREATE TRIGGER IF NOT EXISTS trg_issues_updated_at
AFTER UPDATE ON issues
FOR EACH ROW
BEGIN
    UPDATE issues SET updated_at = datetime('now') WHERE id = OLD.id;
END;
"""


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    """SQLite 연결을 반환합니다. Row factory를 설정합니다."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str = None) -> str:
    """
    groups, issues, executions 테이블과 트리거를 생성합니다.

    기존 DB에 group_name 컬럼이 있으면 groups 테이블로 마이그레이션합니다.

    Args:
        db_path: DB 파일 경로. None이면 get_db_path()를 사용합니다.

    Returns:
        생성된 DB 파일의 절대 경로.
    """
    if db_path is None:
        db_path = get_db_path()

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    conn = _connect(db_path)
    try:
        # Check if migration from old schema is needed
        needs_migration = False
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(issues)").fetchall()}
            if "group_name" in cols:
                needs_migration = True
        except Exception:
            pass

        if needs_migration:
            _migrate_group_name_to_groups_table(conn)
        else:
            conn.executescript(f"{_GROUPS_DDL}\n{_ISSUES_DDL}\n{_EXECUTIONS_DDL}\n{_UPDATED_AT_TRIGGER}")
            conn.commit()

        _migrate_add_columns(conn, "groups", [
            ("rule", "TEXT"),
        ])
        _migrate_add_columns(conn, "issues", [
            ("clean_code_attribute", "TEXT"),
            ("software_quality", "TEXT"),
        ])
        conn.commit()
    finally:
        conn.close()

    return os.path.abspath(db_path)


def _migrate_add_columns(conn: sqlite3.Connection, table: str, columns: list):
    """기존 테이블에 누락된 컬럼을 추가합니다 (ALTER TABLE ADD COLUMN)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col_name, col_type in columns:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")


def _migrate_group_name_to_groups_table(conn: sqlite3.Connection):
    """Migrate old group_name column to groups table + group_id FK."""
    # 1. Create groups table
    conn.execute(_GROUPS_DDL)
    conn.commit()

    # 2. Insert distinct group_name values into groups
    conn.execute("""
        INSERT OR IGNORE INTO groups (name)
        SELECT DISTINCT group_name FROM issues
        WHERE group_name IS NOT NULL AND group_name != ''
    """)
    conn.commit()

    # 3. Recreate issues table without group_name
    conn.execute("ALTER TABLE issues RENAME TO _issues_old")
    conn.execute(_ISSUES_DDL)

    # 4. Copy data, resolving group_name -> group_id
    conn.execute("""
        INSERT INTO issues (
            id, sonarqube_key, status, group_id,
            severity, type, rule, file_path, line, message,
            clean_code_attribute, software_quality,
            assignee, jira_key, report_path, worktree_path,
            analyze_attempts, develop_attempts, synced_at, created_at, updated_at
        )
        SELECT
            o.id, o.sonarqube_key, o.status,
            g.id,
            o.severity, o.type, o.rule, o.file_path, o.line, o.message,
            o.clean_code_attribute, o.software_quality,
            o.assignee, o.jira_key, o.report_path, o.worktree_path,
            o.analyze_attempts, o.develop_attempts, o.synced_at, o.created_at, o.updated_at
        FROM _issues_old o
        LEFT JOIN groups g ON o.group_name = g.name
    """)

    # 5. Drop old table
    conn.execute("DROP TABLE _issues_old")

    # 6. Ensure executions and trigger exist
    conn.execute(_EXECUTIONS_DDL)
    conn.execute(_UPDATED_AT_TRIGGER)
    conn.commit()


# ---------------------------------------------------------------------------
# Group CRUD
# ---------------------------------------------------------------------------

def create_group(name: str, rule: str = None, description: str = None, db_path: str = None) -> int:
    """
    그룹을 생성합니다. 이미 존재하면 기존 ID를 반환합니다.

    Args:
        name: 그룹 이름 (UNIQUE).
        rule: SonarQube 규칙 ID (예: "python:S3457").
        description: 그룹 설명.
        db_path: DB 경로.

    Returns:
        그룹 ID.
    """
    if db_path is None:
        db_path = get_db_path()

    conn = _connect(db_path)
    try:
        existing = conn.execute(
            "SELECT id FROM groups WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            return existing["id"]

        cur = conn.execute(
            "INSERT INTO groups (name, rule, description) VALUES (?, ?, ?)",
            (name, rule, description),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_groups(db_path: str = None) -> list:
    """전체 그룹 목록을 반환합니다."""
    if db_path is None:
        db_path = get_db_path()

    conn = _connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM groups ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_group_by_name(name: str, db_path: str = None) -> dict | None:
    """이름으로 그룹을 조회합니다."""
    if db_path is None:
        db_path = get_db_path()

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM groups WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Issue CRUD
# ---------------------------------------------------------------------------

def upsert_issue(issue_data: dict, db_path: str = None) -> int:
    """
    이슈를 INSERT 또는 UPDATE합니다 (sonarqube_key 기준).

    Args:
        issue_data: 이슈 딕셔너리. 필수 키: sonarqube_key
        db_path: DB 파일 경로.

    Returns:
        affected row id.
    """
    if db_path is None:
        db_path = get_db_path()

    key = issue_data.get("sonarqube_key")
    if not key:
        raise ValueError("issue_data must contain 'sonarqube_key'")

    columns = [
        "sonarqube_key", "status", "group_id",
        "severity", "type", "rule", "file_path", "line", "message",
        "clean_code_attribute", "software_quality",
        "jira_key", "report_path", "worktree_path",
        "analyze_attempts", "develop_attempts",
    ]

    values = {}
    for col in columns:
        if col in issue_data:
            values[col] = issue_data[col]

    # sonarqube_key is always required
    values["sonarqube_key"] = key

    cols_str = ", ".join(values.keys())
    placeholders = ", ".join(f":{k}" for k in values.keys())

    # Build SET clause for ON CONFLICT (exclude sonarqube_key)
    update_cols = [k for k in values.keys() if k != "sonarqube_key"]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in update_cols)

    sql = (
        f"INSERT INTO issues ({cols_str}) VALUES ({placeholders})"
        f" ON CONFLICT(sonarqube_key) DO UPDATE SET {set_clause}"
    )

    conn = _connect(db_path)
    try:
        cur = conn.execute(sql, values)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_status(sonarqube_key: str, new_status: str, db_path: str = None, **kwargs) -> bool:
    """
    이슈 상태를 업데이트합니다.

    Args:
        sonarqube_key: 이슈 키.
        new_status: 새 상태.
        db_path: DB 경로.
        **kwargs: 추가 업데이트 필드 (jira_key, report_path, worktree_path 등).

    Returns:
        업데이트 성공 여부.
    """
    if db_path is None:
        db_path = get_db_path()

    fields = {"status": new_status}
    fields.update(kwargs)

    set_parts = [f"{k} = :{k}" for k in fields.keys()]
    fields["_key"] = sonarqube_key

    sql = f"UPDATE issues SET {', '.join(set_parts)} WHERE sonarqube_key = :_key"

    conn = _connect(db_path)
    try:
        cur = conn.execute(sql, fields)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_issues(status: str = None, group_id: int = None, db_path: str = None) -> list:
    """
    이슈 목록을 조회합니다.

    Args:
        status: 필터할 상태 (None이면 전체).
        group_id: 필터할 그룹 ID (None이면 전체).
        db_path: DB 경로.

    Returns:
        이슈 딕셔너리 리스트.
    """
    if db_path is None:
        db_path = get_db_path()

    conditions = []
    params = {}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if group_id is not None:
        conditions.append("group_id = :group_id")
        params["group_id"] = group_id

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM issues{where} ORDER BY id"

    conn = _connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_issue(sonarqube_key: str, db_path: str = None) -> dict | None:
    """
    단일 이슈를 조회합니다.

    Args:
        sonarqube_key: 이슈 키.
        db_path: DB 경로.

    Returns:
        이슈 딕셔너리 또는 None.
    """
    if db_path is None:
        db_path = get_db_path()

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM issues WHERE sonarqube_key = ?", (sonarqube_key,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Execution history
# ---------------------------------------------------------------------------

def add_execution(
    sonarqube_key: str,
    phase: str,
    status: str,
    details: str = None,
    db_path: str = None,
) -> int:
    """
    실행 이력을 추가합니다.

    Args:
        sonarqube_key: 이슈 키.
        phase: 실행 단계 (analyze, develop 등).
        status: 실행 상태 (success, failure 등).
        details: 상세 내용.
        db_path: DB 경로.

    Returns:
        새 실행 레코드 ID.
    """
    if db_path is None:
        db_path = get_db_path()

    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=False)

    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO executions (sonarqube_key, phase, status, details) "
            "VALUES (?, ?, ?, ?)",
            (sonarqube_key, phase, status, details),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def get_changed_for_sync(db_path: str = None) -> list:
    """
    동기화가 필요한 변경된 이슈만 반환합니다.

    조건: synced_at IS NULL 또는 updated_at > synced_at

    Returns:
        변경된 이슈 딕셔너리 리스트.
    """
    if db_path is None:
        db_path = get_db_path()

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM issues WHERE synced_at IS NULL OR updated_at > synced_at ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_synced(keys: list, db_path: str = None) -> int:
    """
    지정된 이슈들의 synced_at을 현재 시각으로 업데이트합니다.

    대량 키는 999개씩 배치 처리합니다 (SQLite 파라미터 제한 회피).

    Args:
        keys: 동기화 완료된 sonarqube_key 리스트.
        db_path: DB 경로.

    Returns:
        업데이트된 행 수.
    """
    if db_path is None:
        db_path = get_db_path()

    if not keys:
        return 0

    now = datetime.utcnow().isoformat()
    batch_size = 999
    total = 0

    conn = _connect(db_path)
    try:
        for i in range(0, len(keys), batch_size):
            batch = keys[i:i + batch_size]
            placeholders = ", ".join("?" for _ in batch)
            cur = conn.execute(
                f"UPDATE issues SET synced_at = ? WHERE sonarqube_key IN ({placeholders})",
                [now] + list(batch),
            )
            total += cur.rowcount
        conn.commit()
        return total
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_status(db_path: str):
    """전체 이슈 상태 요약을 출력합니다."""
    conn = _connect(db_path)
    try:
        rows = conn.execute("""
            SELECT i.*, g.name as group_name
            FROM issues i
            LEFT JOIN groups g ON i.group_id = g.id
            ORDER BY i.id
        """).fetchall()
        issues = [dict(r) for r in rows]
    finally:
        conn.close()

    if not issues:
        print("No issues found.")
        return

    fmt = "{:<6} {:<30} {:<12} {:<15} {:<10}"
    print(fmt.format("ID", "SonarQube Key", "Status", "Group", "Severity"))
    print("-" * 80)

    for issue in issues:
        print(fmt.format(
            issue["id"],
            issue["sonarqube_key"][:30],
            issue["status"],
            (issue["group_name"] or "")[:15],
            issue["severity"] or "",
        ))

    from collections import Counter
    status_counts = Counter(i["status"] for i in issues)
    print(f"\nTotal: {len(issues)} issues")
    for s, c in sorted(status_counts.items()):
        print(f"  {s}: {c}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python local_db.py {init|status|get <key>|export}")
        sys.exit(1)

    command = sys.argv[1]
    db_path = get_db_path()

    if command == "init":
        path = init_db(db_path)
        print(f"Database initialized: {path}")

    elif command == "status":
        if not os.path.exists(db_path):
            print(f"Database not found: {db_path}")
            print("Run 'python local_db.py init' first.")
            sys.exit(1)
        _print_status(db_path)

    elif command == "get":
        if len(sys.argv) < 3:
            print("Usage: python local_db.py get <sonarqube_key>")
            sys.exit(1)
        issue = get_issue(sys.argv[2], db_path)
        if issue:
            print(json.dumps(issue, indent=2, ensure_ascii=False))
        else:
            print(f"Issue not found: {sys.argv[2]}")
            sys.exit(1)

    elif command == "export":
        if not os.path.exists(db_path):
            print(f"Database not found: {db_path}")
            sys.exit(1)
        data = get_changed_for_sync(db_path)
        print(json.dumps(data, indent=2, ensure_ascii=False))

    else:
        print(f"Unknown command: {command}")
        print("Usage: python local_db.py {init|status|get <key>|export}")
        sys.exit(1)


if __name__ == "__main__":
    main()
