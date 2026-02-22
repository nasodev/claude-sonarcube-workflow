#!/usr/bin/env python3
import os
import tempfile
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))

def _make_db(tmp_dir):
    return os.path.join(tmp_dir, "sonar.db")

def test_init_creates_groups_table():
    from local_db import init_db, _connect
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(groups)").fetchall()}
        conn.close()
        assert cols == {"id", "name", "description", "created_at"}

def test_init_removes_group_name_from_issues():
    from local_db import init_db, _connect
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        conn = _connect(db)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(issues)").fetchall()}
        conn.close()
        assert "group_name" not in cols
        assert "group_id" in cols

def test_migration_preserves_group_data():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "sonar.db")
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sonarqube_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'NEW',
            group_id INTEGER, group_name TEXT,
            severity TEXT, type TEXT, rule TEXT, file_path TEXT, line INTEGER,
            message TEXT, clean_code_attribute TEXT, software_quality TEXT,
            assignee TEXT, jira_key TEXT, report_path TEXT, worktree_path TEXT,
            analyze_attempts INTEGER DEFAULT 0, develop_attempts INTEGER DEFAULT 0,
            synced_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sonarqube_key TEXT NOT NULL, phase TEXT NOT NULL,
            status TEXT NOT NULL, details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("INSERT INTO issues (sonarqube_key, group_name) VALUES ('KEY1', 'group-fstring')")
        conn.execute("INSERT INTO issues (sonarqube_key, group_name) VALUES ('KEY2', 'group-fstring')")
        conn.execute("INSERT INTO issues (sonarqube_key, group_name) VALUES ('KEY3', 'group-imports')")
        conn.execute("INSERT INTO issues (sonarqube_key) VALUES ('KEY4')")
        conn.commit()
        conn.close()

        from local_db import init_db, _connect
        init_db(db)

        conn = _connect(db)
        groups = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
        assert len(groups) == 2
        assert groups[0]["name"] == "group-fstring"
        assert groups[1]["name"] == "group-imports"

        key1 = conn.execute("SELECT group_id FROM issues WHERE sonarqube_key='KEY1'").fetchone()
        key3 = conn.execute("SELECT group_id FROM issues WHERE sonarqube_key='KEY3'").fetchone()
        key4 = conn.execute("SELECT group_id FROM issues WHERE sonarqube_key='KEY4'").fetchone()
        assert key1["group_id"] == groups[0]["id"]
        assert key3["group_id"] == groups[1]["id"]
        assert key4["group_id"] is None

        cols = {row[1] for row in conn.execute("PRAGMA table_info(issues)").fetchall()}
        assert "group_name" not in cols
        conn.close()

def test_create_group():
    from local_db import init_db, create_group, _connect
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        gid = create_group("group-fstring", "F-string conversion", db)
        assert gid > 0
        conn = _connect(db)
        row = conn.execute("SELECT * FROM groups WHERE id = ?", (gid,)).fetchone()
        conn.close()
        assert row["name"] == "group-fstring"
        assert row["description"] == "F-string conversion"

def test_create_group_duplicate_returns_existing():
    from local_db import init_db, create_group
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        gid1 = create_group("group-fstring", "desc1", db)
        gid2 = create_group("group-fstring", "desc2", db)
        assert gid1 == gid2

def test_get_groups():
    from local_db import init_db, create_group, get_groups
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        create_group("group-a", None, db)
        create_group("group-b", "desc", db)
        groups = get_groups(db)
        assert len(groups) == 2
        names = {g["name"] for g in groups}
        assert names == {"group-a", "group-b"}

def test_get_group_by_name():
    from local_db import init_db, create_group, get_group_by_name
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        create_group("group-x", "desc", db)
        g = get_group_by_name("group-x", db)
        assert g is not None
        assert g["name"] == "group-x"
        assert get_group_by_name("nonexistent", db) is None

def test_upsert_issue_without_group_name():
    """upsert_issue should work without group_name column."""
    from local_db import init_db, upsert_issue, get_issue
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        upsert_issue({"sonarqube_key": "K1", "status": "NEW", "group_id": None}, db)
        issue = get_issue("K1", db)
        assert issue["sonarqube_key"] == "K1"
        assert issue["group_id"] is None

def test_upsert_issue_with_group_id():
    from local_db import init_db, upsert_issue, get_issue, create_group
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        gid = create_group("group-test", None, db)
        upsert_issue({"sonarqube_key": "K1", "group_id": gid}, db)
        issue = get_issue("K1", db)
        assert issue["group_id"] == gid

def test_update_status_with_group_id():
    from local_db import init_db, upsert_issue, update_status, get_issue, create_group
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        gid = create_group("group-test", None, db)
        upsert_issue({"sonarqube_key": "K1", "status": "NEW"}, db)
        update_status("K1", "NEW", db_path=db, group_id=gid)
        issue = get_issue("K1", db)
        assert issue["group_id"] == gid

def test_get_issues_filter_by_group_id():
    from local_db import init_db, upsert_issue, get_issues, create_group
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        gid = create_group("group-a", None, db)
        upsert_issue({"sonarqube_key": "K1", "group_id": gid}, db)
        upsert_issue({"sonarqube_key": "K2", "group_id": None}, db)
        results = get_issues(group_id=gid, db_path=db)
        assert len(results) == 1
        assert results[0]["sonarqube_key"] == "K1"

def test_get_changed_for_sync_returns_unsynced():
    from local_db import init_db, upsert_issue, get_changed_for_sync
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        upsert_issue({"sonarqube_key": "K1", "status": "DONE"}, db)
        upsert_issue({"sonarqube_key": "K2", "status": "NEW"}, db)
        changed = get_changed_for_sync(db)
        keys = {i["sonarqube_key"] for i in changed}
        assert keys == {"K1", "K2"}  # both unsynced (synced_at is NULL)

def test_get_changed_for_sync_excludes_synced():
    from local_db import init_db, upsert_issue, mark_synced, get_changed_for_sync
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        upsert_issue({"sonarqube_key": "K1", "status": "DONE"}, db)
        upsert_issue({"sonarqube_key": "K2", "status": "NEW"}, db)
        mark_synced(["K1"], db)
        changed = get_changed_for_sync(db)
        keys = {i["sonarqube_key"] for i in changed}
        # K1: synced_at is set, updated_at <= synced_at → excluded
        # K2: synced_at is NULL → included
        assert "K2" in keys
        assert "K1" not in keys

def test_mark_synced_partial():
    from local_db import init_db, upsert_issue, mark_synced, get_issue
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        init_db(db)
        upsert_issue({"sonarqube_key": "K1", "status": "NEW"}, db)
        upsert_issue({"sonarqube_key": "K2", "status": "NEW"}, db)
        count = mark_synced(["K1"], db)
        assert count == 1
        k1 = get_issue("K1", db)
        k2 = get_issue("K2", db)
        assert k1["synced_at"] is not None
        assert k2["synced_at"] is None


# ---------------------------------------------------------------------------
# Batch processing tests for mark_synced (SQLite parameter limit)
# ---------------------------------------------------------------------------

def _create_db_with_issues(count: int) -> str:
    """Create a temp DB with N issues, return db_path."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from local_db import init_db, upsert_issue
    init_db(db_path)
    for i in range(count):
        upsert_issue({"sonarqube_key": f"KEY-{i:06d}", "status": "NEW"}, db_path)
    return db_path


def test_mark_synced_small_batch():
    """Basic: mark 10 issues as synced."""
    from local_db import mark_synced, get_issue
    db_path = _create_db_with_issues(10)
    try:
        keys = [f"KEY-{i:06d}" for i in range(10)]
        updated = mark_synced(keys, db_path)
        assert updated == 10
        issue = get_issue("KEY-000000", db_path)
        assert issue["synced_at"] is not None
    finally:
        os.unlink(db_path)


def test_mark_synced_over_999():
    """Must handle >999 keys without SQLite parameter limit error."""
    from local_db import mark_synced, get_issue
    db_path = _create_db_with_issues(2000)
    try:
        keys = [f"KEY-{i:06d}" for i in range(2000)]
        updated = mark_synced(keys, db_path)
        assert updated == 2000
        # Verify first and last
        assert get_issue("KEY-000000", db_path)["synced_at"] is not None
        assert get_issue("KEY-001999", db_path)["synced_at"] is not None
    finally:
        os.unlink(db_path)


def test_mark_synced_empty():
    """Empty list should return 0."""
    from local_db import mark_synced
    db_path = _create_db_with_issues(1)
    try:
        assert mark_synced([], db_path) == 0
    finally:
        os.unlink(db_path)
