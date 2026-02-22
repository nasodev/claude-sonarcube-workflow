#!/usr/bin/env python3
"""
SQLite 실행 추적 DB — 에이전트용 로컬 추적 (Sheets 워크플로우를 절대 차단하지 않음)

Usage:
    from tracking_db import get_tracker
    tracker = get_tracker()
    exec_id = tracker.start_execution('ISSUE-001', sheet_row=5, phase='analyze')
    tracker.complete_execution(exec_id, 'success')

Self-test:
    python tracking_db.py
"""

import logging
import os
import random
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# DB 기본 경로: .claude/data/sonar_tracking.db (TRACKING_DB_PATH 환경변수로 오버라이드)
# 1. CLAUDE_PROJECT_DIR (hooks 컨텍스트)
# 2. 스크립트 위치에서 상위 탐색 (로컬 .claude/skills 환경)
# 3. CWD에서 .claude 사용 (플러그인 Bash 실행 컨텍스트)
_SCRIPT_DIR = Path(__file__).parent
if os.environ.get('CLAUDE_PROJECT_DIR'):
    _CLAUDE_DIR = Path(os.environ['CLAUDE_PROJECT_DIR']) / '.claude'
else:
    _candidate = _SCRIPT_DIR.parent.parent.parent    # scripts/ -> sonar-common/ -> skills/ -> .claude/
    if _candidate.name == '.claude':
        _CLAUDE_DIR = _candidate
    else:
        # 플러그인 환경: CWD/.claude
        _CLAUDE_DIR = Path.cwd() / '.claude'
_DEFAULT_DB_PATH = _CLAUDE_DIR / 'data' / 'sonar_tracking.db'

# phase 별칭 정규화: 호출측에서 "fix"를 쓰더라도 DB에는 "develop"로 기록
_PHASE_ALIASES = {'fix': 'develop'}

_SCHEMA_SQL = """
-- issue_executions: 이슈별 실행 단위
CREATE TABLE IF NOT EXISTS issue_executions (
    execution_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key       TEXT NOT NULL,
    sheet_row       INTEGER,
    phase           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    attempt_number  INTEGER NOT NULL DEFAULT 1,
    started_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    completed_at    TEXT,
    duration_ms     INTEGER,
    error_message   TEXT,
    error_phase     TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_issue_key ON issue_executions(issue_key);
CREATE INDEX IF NOT EXISTS idx_exec_status ON issue_executions(status);
CREATE INDEX IF NOT EXISTS idx_exec_phase_status ON issue_executions(phase, status);
CREATE INDEX IF NOT EXISTS idx_exec_started_at ON issue_executions(started_at DESC);

-- state_transitions: 상태 전이 감사 기록
CREATE TABLE IF NOT EXISTS state_transitions (
    transition_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key       TEXT NOT NULL,
    from_status     TEXT NOT NULL DEFAULT '',
    to_status       TEXT NOT NULL,
    transitioned_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    triggered_by    TEXT NOT NULL DEFAULT 'agent',
    attempt_number  INTEGER,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_trans_issue_key ON state_transitions(issue_key);
CREATE INDEX IF NOT EXISTS idx_trans_at ON state_transitions(transitioned_at DESC);

-- error_log: 에러 기록 (덮어쓰기 없이 누적)
CREATE TABLE IF NOT EXISTS error_log (
    error_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key           TEXT NOT NULL,
    phase               TEXT NOT NULL,
    attempt_number      INTEGER NOT NULL DEFAULT 1,
    error_type          TEXT NOT NULL,
    error_message       TEXT NOT NULL,
    review_suggestions  TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_err_issue_key ON error_log(issue_key);
CREATE INDEX IF NOT EXISTS idx_err_type ON error_log(error_type);
CREATE INDEX IF NOT EXISTS idx_err_created_at ON error_log(created_at DESC);

-- v_issue_summary: 이슈별 최신 실행 요약
CREATE VIEW IF NOT EXISTS v_issue_summary AS
SELECT
    e.issue_key,
    e.phase,
    e.status,
    e.attempt_number,
    e.started_at,
    e.completed_at,
    e.duration_ms,
    e.error_message,
    (SELECT COUNT(*) FROM error_log el WHERE el.issue_key = e.issue_key) AS total_errors,
    (SELECT COUNT(*) FROM state_transitions st WHERE st.issue_key = e.issue_key) AS total_transitions
FROM issue_executions e
WHERE e.execution_id = (
    SELECT MAX(e2.execution_id) FROM issue_executions e2 WHERE e2.issue_key = e.issue_key
);

-- v_error_patterns: 에러 유형별 집계
CREATE VIEW IF NOT EXISTS v_error_patterns AS
SELECT
    error_type,
    phase,
    COUNT(*) AS occurrence_count,
    COUNT(DISTINCT issue_key) AS affected_issues,
    MAX(created_at) AS last_seen,
    MIN(created_at) AS first_seen
FROM error_log
GROUP BY error_type, phase
ORDER BY occurrence_count DESC;

-- v_phase_metrics: 단계별 성능 지표
CREATE VIEW IF NOT EXISTS v_phase_metrics AS
SELECT
    phase,
    status,
    COUNT(*) AS execution_count,
    ROUND(AVG(duration_ms)) AS avg_duration_ms,
    MIN(duration_ms) AS min_duration_ms,
    MAX(duration_ms) AS max_duration_ms,
    ROUND(AVG(attempt_number), 1) AS avg_attempts
FROM issue_executions
WHERE status != 'running'
GROUP BY phase, status;
"""


class TrackingDB:
    """SQLite 실행 추적 DB. 모든 public 메서드는 예외를 전파하지 않음."""

    def __init__(self, db_path: Path = None):
        self._db_path = db_path or Path(os.environ.get('TRACKING_DB_PATH', str(_DEFAULT_DB_PATH)))
        self._local = threading.local()
        self._available = True
        self._ensure_schema()

    # ── 연결 관리 ──────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """스레드별 연결 반환 (WAL 모드, busy_timeout=30000)"""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _execute_with_retry(self, operation, max_attempts=3):
        """Write operation을 재시도 로직과 함께 실행."""
        last_error = None
        for attempt in range(max_attempts):
            try:
                return operation()
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_attempts - 1:
                    delay = 0.1 * (3 ** attempt) + random.uniform(0, 0.05)
                    logger.debug(f"Tracking DB retry {attempt+1}/{max_attempts}: {e}")
                    time.sleep(delay)
        logger.warning(f"Tracking DB write failed after {max_attempts} attempts: {last_error}")
        return None

    def _ensure_schema(self):
        """테이블/뷰 생성 (IF NOT EXISTS). 실패 시 warning만."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._get_conn()
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
        except Exception as e:
            logger.warning(f"Tracking DB schema init failed: {e}")
            self._available = False

    # ── issue_executions ──────────────────────────────────────

    def find_running_execution(self, issue_key: str, phase: str = None) -> Optional[Dict]:
        """이슈의 running 상태 실행 레코드 조회. 없으면 None."""
        try:
            if not self._available:
                return None
            conn = self._get_conn()
            if phase:
                phase = _PHASE_ALIASES.get(phase, phase)
                row = conn.execute(
                    """SELECT * FROM issue_executions
                       WHERE issue_key = ? AND phase = ? AND status = 'running'
                       ORDER BY execution_id DESC LIMIT 1""",
                    (issue_key, phase)
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT * FROM issue_executions
                       WHERE issue_key = ? AND status = 'running'
                       ORDER BY execution_id DESC LIMIT 1""",
                    (issue_key,)
                ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.warning(f"Tracking DB find_running_execution failed: {e}")
            return None

    def start_execution(self, issue_key: str, sheet_row: int = None,
                        phase: str = 'analyze', attempt: int = 1) -> Optional[int]:
        """실행 시작 기록. 기존 running 레코드가 있으면 superseded로 닫고 새로 생성."""
        try:
            if not self._available:
                return None
            phase = _PHASE_ALIASES.get(phase, phase)

            def _op():
                conn = self._get_conn()
                # 기존 running 레코드를 superseded로 닫기
                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                conn.execute(
                    """UPDATE issue_executions
                       SET status = 'superseded', completed_at = ?,
                           error_message = 'Closed: new execution started'
                       WHERE issue_key = ? AND phase = ? AND status = 'running'""",
                    (now_str, issue_key, phase)
                )
                cur = conn.execute(
                    """INSERT INTO issue_executions (issue_key, sheet_row, phase, attempt_number)
                       VALUES (?, ?, ?, ?)""",
                    (issue_key, sheet_row, phase, attempt)
                )
                conn.commit()
                return cur.lastrowid

            return self._execute_with_retry(_op)
        except Exception as e:
            logger.warning(f"Tracking DB start_execution failed: {e}")
            return None

    def complete_execution(self, execution_id: int = None, status: str = 'success',
                           error_message: str = None, error_phase: str = None,
                           issue_key: str = None, phase: str = None,
                           attempt: int = None) -> bool:
        """실행 완료 기록. execution_id 또는 자연키(issue_key+phase+attempt)로 찾음."""
        try:
            if not self._available:
                return False
            if phase is not None:
                phase = _PHASE_ALIASES.get(phase, phase)

            def _op():
                conn = self._get_conn()
                eid = execution_id

                # execution_id가 없으면 자연키로 찾기
                if eid is None:
                    if not (issue_key and phase):
                        logger.warning("complete_execution: need execution_id or (issue_key + phase)")
                        return False
                    query = """SELECT execution_id, started_at FROM issue_executions
                               WHERE issue_key = ? AND phase = ? AND status = 'running'"""
                    params = [issue_key, phase]
                    if attempt is not None:
                        query += " AND attempt_number = ?"
                        params.append(attempt)
                    query += " ORDER BY execution_id DESC LIMIT 1"
                    row = conn.execute(query, params).fetchone()
                    if not row:
                        logger.warning(f"complete_execution: no running execution found for {issue_key}/{phase}")
                        return False
                    eid = row['execution_id']
                    started_at_str = row['started_at']
                else:
                    row = conn.execute(
                        "SELECT started_at FROM issue_executions WHERE execution_id = ?",
                        (eid,)
                    ).fetchone()
                    if not row:
                        logger.warning(f"complete_execution: execution_id {eid} not found")
                        return False
                    started_at_str = row['started_at']

                # duration 계산
                now = datetime.now()
                now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                try:
                    started_at = datetime.strptime(started_at_str, '%Y-%m-%d %H:%M:%S')
                    duration_ms = int((now - started_at).total_seconds() * 1000)
                except (ValueError, TypeError):
                    duration_ms = None

                conn.execute(
                    """UPDATE issue_executions
                       SET status = ?, completed_at = ?, duration_ms = ?,
                           error_message = ?, error_phase = ?
                       WHERE execution_id = ?""",
                    (status, now_str, duration_ms, error_message, error_phase, eid)
                )
                conn.commit()
                return True

            result = self._execute_with_retry(_op)
            return result if result is not None else False
        except Exception as e:
            logger.warning(f"Tracking DB complete_execution failed: {e}")
            return False

    def fail_execution(self, execution_id: int, error_message: str,
                       error_phase: str = None) -> bool:
        """실행 실패 기록 (complete_execution의 편의 래퍼)."""
        return self.complete_execution(
            execution_id=execution_id,
            status='failed',
            error_message=error_message,
            error_phase=error_phase
        )

    def complete_running_for_issue(self, issue_key: str, status: str = 'success',
                                   error_message: str = None) -> int:
        """이슈의 모든 running 실행 레코드를 완료 처리. 닫은 건수 반환."""
        try:
            if not self._available:
                return 0

            def _op():
                conn = self._get_conn()
                now = datetime.now()
                now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                # running 레코드 조회
                rows = conn.execute(
                    """SELECT execution_id, started_at FROM issue_executions
                       WHERE issue_key = ? AND status = 'running'""",
                    (issue_key,)
                ).fetchall()
                if not rows:
                    return 0
                for row in rows:
                    try:
                        started_at = datetime.strptime(row['started_at'], '%Y-%m-%d %H:%M:%S')
                        duration_ms = int((now - started_at).total_seconds() * 1000)
                    except (ValueError, TypeError):
                        duration_ms = None
                    conn.execute(
                        """UPDATE issue_executions
                           SET status = ?, completed_at = ?, duration_ms = ?, error_message = ?
                           WHERE execution_id = ?""",
                        (status, now_str, duration_ms, error_message, row['execution_id'])
                    )
                conn.commit()
                return len(rows)

            result = self._execute_with_retry(_op)
            return result if result is not None else 0
        except Exception as e:
            logger.warning(f"Tracking DB complete_running_for_issue failed: {e}")
            return 0

    def cleanup_stale(self, threshold_minutes: int = 30) -> int:
        """장기 running 레코드를 abandoned로 처리. 닫은 건수 반환."""
        try:
            if not self._available:
                return 0

            def _op():
                conn = self._get_conn()
                now = datetime.now()
                now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                rows = conn.execute(
                    """SELECT execution_id, started_at FROM issue_executions
                       WHERE status = 'running'"""
                ).fetchall()
                closed = 0
                for row in rows:
                    try:
                        started_at = datetime.strptime(row['started_at'], '%Y-%m-%d %H:%M:%S')
                        elapsed_min = (now - started_at).total_seconds() / 60
                    except (ValueError, TypeError):
                        elapsed_min = threshold_minutes + 1  # 파싱 실패 시 stale 처리
                    if elapsed_min >= threshold_minutes:
                        duration_ms = int(elapsed_min * 60 * 1000)
                        conn.execute(
                            """UPDATE issue_executions
                               SET status = 'abandoned', completed_at = ?, duration_ms = ?,
                                   error_message = ?
                               WHERE execution_id = ?""",
                            (now_str, duration_ms,
                             f'Stale: running for {int(elapsed_min)}min (threshold={threshold_minutes}min)',
                             row['execution_id'])
                        )
                        closed += 1
                if closed > 0:
                    conn.commit()
                return closed

            result = self._execute_with_retry(_op)
            return result if result is not None else 0
        except Exception as e:
            logger.warning(f"Tracking DB cleanup_stale failed: {e}")
            return 0

    # ── state_transitions ─────────────────────────────────────

    def record_transition(self, issue_key: str, from_status: str, to_status: str,
                          triggered_by: str = 'agent', attempt: int = None,
                          notes: str = None) -> bool:
        """상태 전이 기록."""
        try:
            if not self._available:
                return False

            def _op():
                conn = self._get_conn()
                conn.execute(
                    """INSERT INTO state_transitions
                       (issue_key, from_status, to_status, triggered_by, attempt_number, notes)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (issue_key, from_status, to_status, triggered_by, attempt, notes)
                )
                conn.commit()
                return True

            result = self._execute_with_retry(_op)
            return result if result is not None else False
        except Exception as e:
            logger.warning(f"Tracking DB record_transition failed: {e}")
            return False

    # ── error_log ─────────────────────────────────────────────

    def log_error(self, issue_key: str, phase: str, attempt: int,
                  error_type: str, error_message: str,
                  review_suggestions: str = None) -> bool:
        """에러 누적 기록."""
        try:
            if not self._available:
                return False

            def _op():
                conn = self._get_conn()
                conn.execute(
                    """INSERT INTO error_log
                       (issue_key, phase, attempt_number, error_type, error_message, review_suggestions)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (issue_key, phase, attempt, error_type, error_message, review_suggestions)
                )
                conn.commit()
                return True

            result = self._execute_with_retry(_op)
            return result if result is not None else False
        except Exception as e:
            logger.warning(f"Tracking DB log_error failed: {e}")
            return False

    # ── 조회 ──────────────────────────────────────────────────

    def _rows_to_dicts(self, rows) -> List[Dict]:
        """sqlite3.Row 리스트를 dict 리스트로 변환."""
        return [dict(r) for r in rows]

    def get_issue_summary(self, issue_key: str = None) -> List[Dict]:
        """이슈별 최신 실행 요약."""
        try:
            if not self._available:
                return []
            conn = self._get_conn()
            if issue_key:
                rows = conn.execute(
                    "SELECT * FROM v_issue_summary WHERE issue_key = ?", (issue_key,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM v_issue_summary").fetchall()
            return self._rows_to_dicts(rows)
        except Exception as e:
            logger.warning(f"Tracking DB get_issue_summary failed: {e}")
            return []

    def get_error_patterns(self, limit: int = 20) -> List[Dict]:
        """에러 유형별 집계."""
        try:
            if not self._available:
                return []
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM v_error_patterns LIMIT ?", (limit,)
            ).fetchall()
            return self._rows_to_dicts(rows)
        except Exception as e:
            logger.warning(f"Tracking DB get_error_patterns failed: {e}")
            return []

    def get_phase_metrics(self) -> List[Dict]:
        """단계별 성능 지표."""
        try:
            if not self._available:
                return []
            conn = self._get_conn()
            rows = conn.execute("SELECT * FROM v_phase_metrics").fetchall()
            return self._rows_to_dicts(rows)
        except Exception as e:
            logger.warning(f"Tracking DB get_phase_metrics failed: {e}")
            return []

    def get_issue_history(self, issue_key: str) -> Dict:
        """이슈 전체 이력 (실행 + 전이 + 에러 통합)."""
        try:
            if not self._available:
                return {'issue_key': issue_key, 'executions': [], 'transitions': [], 'errors': []}
            conn = self._get_conn()
            executions = conn.execute(
                "SELECT * FROM issue_executions WHERE issue_key = ? ORDER BY execution_id",
                (issue_key,)
            ).fetchall()
            transitions = conn.execute(
                "SELECT * FROM state_transitions WHERE issue_key = ? ORDER BY transition_id",
                (issue_key,)
            ).fetchall()
            errors = conn.execute(
                "SELECT * FROM error_log WHERE issue_key = ? ORDER BY error_id",
                (issue_key,)
            ).fetchall()
            return {
                'issue_key': issue_key,
                'executions': self._rows_to_dicts(executions),
                'transitions': self._rows_to_dicts(transitions),
                'errors': self._rows_to_dicts(errors),
            }
        except Exception as e:
            logger.warning(f"Tracking DB get_issue_history failed: {e}")
            return {'issue_key': issue_key, 'executions': [], 'transitions': [], 'errors': []}

    def get_recent_executions(self, limit: int = 20, status: str = None) -> List[Dict]:
        """최근 실행 목록."""
        try:
            if not self._available:
                return []
            conn = self._get_conn()
            if status:
                rows = conn.execute(
                    """SELECT * FROM issue_executions
                       WHERE status = ? ORDER BY started_at DESC LIMIT ?""",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM issue_executions ORDER BY started_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            return self._rows_to_dicts(rows)
        except Exception as e:
            logger.warning(f"Tracking DB get_recent_executions failed: {e}")
            return []


# ── 모듈 레벨 싱글톤 ─────────────────────────────────────────

_tracker_instance: Optional[TrackingDB] = None
_tracker_lock = threading.Lock()


def get_tracker() -> TrackingDB:
    """TrackingDB 싱글톤 반환."""
    global _tracker_instance
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:
                _tracker_instance = TrackingDB()
    return _tracker_instance


# ── Self-test ─────────────────────────────────────────────────

if __name__ == '__main__':
    import tempfile

    print("=== TrackingDB Self-Test ===\n")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / 'test_tracking.db'
        db = TrackingDB(db_path)
        print(f"[OK] DB created at {db_path}")

        # 1) start_execution
        eid = db.start_execution('TEST-001', sheet_row=5, phase='analyze', attempt=1)
        assert eid is not None, "start_execution should return an id"
        print(f"[OK] start_execution -> execution_id={eid}")

        # 2) record_transition
        ok = db.record_transition('TEST-001', 'NEW', 'ANALYZING', triggered_by='test')
        assert ok, "record_transition should succeed"
        print("[OK] record_transition")

        ok = db.record_transition('TEST-001', 'ANALYZING', 'REVIEW_ANALYSIS', triggered_by='test')
        assert ok
        print("[OK] record_transition (2nd)")

        # 3) log_error
        ok = db.log_error('TEST-001', 'analyze', 1, 'SyntaxError', 'unexpected token',
                          review_suggestions='Check line 42')
        assert ok, "log_error should succeed"
        print("[OK] log_error")

        # 4) complete_execution
        ok = db.complete_execution(eid, 'success')
        assert ok, "complete_execution should succeed"
        print("[OK] complete_execution (by id)")

        # 5) start + complete by natural key
        eid2 = db.start_execution('TEST-002', sheet_row=10, phase='develop', attempt=1)
        ok = db.complete_execution(
            issue_key='TEST-002', phase='develop', attempt=1, status='failed',
            error_message='build failed'
        )
        assert ok, "complete_execution by natural key should succeed"
        print("[OK] complete_execution (by natural key)")

        # 6) fail_execution
        eid3 = db.start_execution('TEST-003', phase='analyze', attempt=2)
        ok = db.fail_execution(eid3, 'timeout', error_phase='sonar_api')
        assert ok, "fail_execution should succeed"
        print("[OK] fail_execution")

        # 7) get_issue_summary
        summary = db.get_issue_summary()
        assert len(summary) >= 2, f"Expected >= 2 summaries, got {len(summary)}"
        print(f"[OK] get_issue_summary -> {len(summary)} issues")

        summary_one = db.get_issue_summary('TEST-001')
        assert len(summary_one) == 1
        print(f"[OK] get_issue_summary(TEST-001) -> {summary_one[0]['status']}")

        # 8) get_error_patterns
        patterns = db.get_error_patterns()
        assert len(patterns) >= 1
        print(f"[OK] get_error_patterns -> {len(patterns)} patterns")

        # 9) get_phase_metrics
        metrics = db.get_phase_metrics()
        assert len(metrics) >= 1
        print(f"[OK] get_phase_metrics -> {len(metrics)} entries")

        # 10) get_issue_history
        history = db.get_issue_history('TEST-001')
        assert len(history['executions']) >= 1
        assert len(history['transitions']) >= 2
        assert len(history['errors']) >= 1
        print(f"[OK] get_issue_history -> execs={len(history['executions'])}, "
              f"trans={len(history['transitions'])}, errs={len(history['errors'])}")

        # 11) get_recent_executions
        recent = db.get_recent_executions()
        assert len(recent) >= 3
        print(f"[OK] get_recent_executions -> {len(recent)} entries")

        recent_failed = db.get_recent_executions(status='failed')
        assert len(recent_failed) >= 1
        print(f"[OK] get_recent_executions(status=failed) -> {len(recent_failed)} entries")

        # 12) phase alias: "fix" -> "develop"
        eid4 = db.start_execution('TEST-004', sheet_row=20, phase='fix', attempt=1)
        assert eid4 is not None, "start_execution with phase='fix' should succeed"
        # DB에는 "develop"로 저장되어야 함
        row = db._get_conn().execute(
            "SELECT phase FROM issue_executions WHERE execution_id = ?", (eid4,)
        ).fetchone()
        assert row['phase'] == 'develop', f"Expected 'develop', got '{row['phase']}'"
        print("[OK] phase alias: 'fix' stored as 'develop'")

        # complete by natural key with "fix" -> should find "develop"
        ok = db.complete_execution(issue_key='TEST-004', phase='fix', attempt=1, status='success')
        assert ok, "complete_execution with phase='fix' should find 'develop' record"
        print("[OK] complete_execution with phase alias")

        # 13) start_execution 중복 방지: 기존 running을 superseded로 닫음
        eid5a = db.start_execution('TEST-005', sheet_row=30, phase='analyze', attempt=1)
        assert eid5a is not None
        eid5b = db.start_execution('TEST-005', sheet_row=30, phase='analyze', attempt=2)
        assert eid5b is not None
        # 이전 eid5a는 superseded로 닫혀야 함
        row = db._get_conn().execute(
            "SELECT status FROM issue_executions WHERE execution_id = ?", (eid5a,)
        ).fetchone()
        assert row['status'] == 'superseded', f"Expected 'superseded', got '{row['status']}'"
        print("[OK] start_execution: duplicate running → superseded")

        # 14) find_running_execution
        running = db.find_running_execution('TEST-005', 'analyze')
        assert running is not None
        assert running['execution_id'] == eid5b
        print("[OK] find_running_execution")

        no_running = db.find_running_execution('TEST-005', 'develop')
        assert no_running is None
        print("[OK] find_running_execution (no match)")

        # 15) complete_running_for_issue
        db.start_execution('TEST-006', sheet_row=40, phase='analyze', attempt=1)
        db.start_execution('TEST-006', sheet_row=40, phase='develop', attempt=1)
        closed = db.complete_running_for_issue('TEST-006', status='blocked', error_message='4 fails')
        # start_execution의 중복 방지는 같은 phase만 닫으므로
        # analyze와 develop 각각 running → 둘 다 닫힘
        assert closed == 2, f"Expected 2 closed (both phases running), got {closed}"
        print(f"[OK] complete_running_for_issue -> closed {closed}")

        # 16) cleanup_stale (threshold=0으로 즉시 정리)
        db.start_execution('TEST-007', sheet_row=50, phase='analyze', attempt=1)
        import time as _time
        _time.sleep(0.1)  # 최소 경과 시간 확보
        stale_closed = db.cleanup_stale(threshold_minutes=0)
        assert stale_closed >= 1, f"Expected >= 1 stale closed, got {stale_closed}"
        print(f"[OK] cleanup_stale -> closed {stale_closed}")

        print("\n=== All tests passed! ===")
