---
name: sonar-common
description: SonarQube 워크플로우 공통 모듈. 환경변수 로더, 로컬 SQLite DB, 웹서비스 REST 클라이언트 및 유틸리티 함수 제공.
user-invocable: false
---

# SonarQube Common Module

내부 스킬들이 공유하는 공통 모듈입니다.

## 제공 기능

- `env_loader.py`: 환경변수 로더 (.env 파일 관리)
- `local_db.py`: SQLite 로컬 상태 DB (프로젝트별 이슈/실행 관리)
- `web_client.py`: 웹서비스 REST API 클라이언트
- `validate_issue_key.py`: 이슈 키 검증
- `tracking_db.py`: SQLite 실행 추적 DB (에이전트용 로컬 추적)
- `tracking_query.py`: 추적 DB 조회 CLI

## 로컬 DB 스키마 (SQLite)

### groups 테이블

```sql
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    rule        TEXT,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
```

### issues 테이블

```sql
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
    jira_key TEXT,
    report_path TEXT,
    worktree_path TEXT,
    analyze_attempts INTEGER DEFAULT 0,
    develop_attempts INTEGER DEFAULT 0,
    synced_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### executions 테이블

```sql
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sonarqube_key TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
```

## 이슈 데이터 JSON 계약

> 모든 스킬이 이슈를 주고받을 때 사용하는 공통 구조입니다.

```json
{
  "sonarqube_key": "AZO...",
  "status": "NEW",
  "group_id": 1,
  "severity": "MAJOR",
  "type": "CODE_SMELL",
  "rule": "java:S1172",
  "file_path": "src/main/java/Foo.java",
  "line": 42,
  "message": "Remove this unused method parameter 'bar'.",
  "jira_key": "ODIN-123",
  "report_path": "reports/AZO...-report.md",
  "worktree_path": "worktrees/AZO...",
  "analyze_attempts": 1,
  "develop_attempts": 0,
  "synced_at": "2025-02-16T12:00:00",
  "created_at": "2025-02-16T10:00:00",
  "updated_at": "2025-02-16T12:00:00"
}
```

## local_db.py — 로컬 SQLite DB 관리

### Python API

```python
from local_db import (
    get_db_path, init_db, upsert_issue, update_status,
    get_issues, get_issue, add_execution,
    create_group, get_groups, get_group_by_name,
    get_changed_for_sync, mark_synced,
)

# DB 초기화
db = init_db()  # SONAR_PROJECT_DIR/sonar.db 또는 CWD/sonar.db

# 이슈 upsert (sonarqube_key 기준 INSERT or UPDATE)
upsert_issue({"sonarqube_key": "AZO...", "status": "NEW", "severity": "MAJOR"})

# 상태 업데이트 (추가 필드도 가능)
update_status("AZO...", "ANALYZING", jira_key="ODIN-123")

# 이슈 조회
issues = get_issues(status="NEW")                 # 상태별 필터
issues = get_issues(group_id=1)                    # 그룹별 필터
issue = get_issue("AZO...")                        # 단일 이슈

# 그룹 CRUD
gid = create_group("group-fstring", rule="python:S3457", description="f-string 변환")
groups = get_groups()
group = get_group_by_name("group-fstring")

# 실행 이력 추가
add_execution("AZO...", phase="analyze", status="success", details="report generated")

# Sync용 변경분 조회
data = get_changed_for_sync()  # [{"sonarqube_key": ..., "status": ..., ...}, ...]

# Sync 완료 표시 (부분 성공 지원)
mark_synced(["KEY1", "KEY2"])
```

### CLI

```bash
python local_db.py init                  # DB 초기화
python local_db.py status                # 전체 이슈 상태 목록
python local_db.py get <sonarqube_key>   # 단일 이슈 JSON
python local_db.py export                # 전체 데이터 sync용 JSON
```

DB 위치: `SONAR_PROJECT_DIR/sonar.db` (환경변수 미설정 시 `CWD/sonar.db`)

## web_client.py — 웹서비스 REST API 클라이언트

### Python API

```python
from web_client import (
    get_projects, get_project_detail, get_project_stats,
    bulk_create_issues, get_issues, create_group, get_groups,
    upload_results, get_dashboard,
)

# 프로젝트
projects = get_projects()                            # GET /api/projects
detail = get_project_detail(1)                       # GET /api/projects/1/detail
stats = get_project_stats(1)                         # GET /api/projects/1/stats

# 이슈
bulk_create_issues(1, [{"sonarqube_key": "AZO...", ...}])  # POST /api/projects/1/issues/bulk
issues = get_issues(1, status="NEW")                       # GET /api/projects/1/issues?status=NEW

# 그룹
create_group(1, name="java:S1172", rule="java:S1172", description="Unused params")
groups = get_groups(1)                               # GET /api/projects/1/groups

# 동기화 (업로드만)
upload_results(1, issues=[...], assignee="홍길동")   # POST /api/projects/1/sync/upload

# 대시보드
dashboard = get_dashboard()                          # GET /api/dashboard
```

### CLI

```bash
python web_client.py projects            # 프로젝트 목록
python web_client.py project <id>        # 프로젝트 상세
python web_client.py stats <id>          # 프로젝트 통계
python web_client.py dashboard           # 대시보드
```

웹서비스 URL: `WEB_SERVICE_URL` 환경변수 (기본값: `http://localhost:10010`)

## 환경 설정

1. `.env.example`을 프로젝트 루트에 `.env`로 복사
2. 환경변수 값 설정

## 사용법

다른 스킬에서 import:

```python
import sys
sys.path.insert(0, '/path/to/sonar-common/scripts')
from env_loader import load_env, get_env
from local_db import init_db, upsert_issue, get_issues
from web_client import get_projects, upload_results

load_env()  # .env 파일 로드
```

### 이슈 키 검증

```bash
# 이슈 키가 DB에 존재하는지 확인
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/validate_issue_key.py \
  -k ISSUE_KEY

# JSON 출력 모드
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/validate_issue_key.py \
  -k ISSUE_KEY --json
```

- Exit 0: 검증 통과
- Exit 1: 불일치 또는 오류

### 추적 DB — 자동 추적

상태 전환 시 실행 추적이 **자동으로** 관리됩니다:

| 상태 전환 | 자동 동작 |
|---|---|
| → `ANALYZING` | `start_execution(phase='analyze')` |
| → `JIRA_CREATED` / `REPORT_CREATED` | `complete_execution(phase='analyze', 'success')` |
| → `DEVELOPING` | `start_execution(phase='develop')` |
| → `DONE` | `complete_execution(phase='develop', 'success')` |
| → `BLOCKED` | `complete_running_for_issue('blocked')` — 모든 running 레코드 닫음 |

추가 보호 기능:
- `start_execution`: 기존 running 레코드가 있으면 `superseded`로 자동 닫고 새로 생성
- 매 호출 시 30분 이상 running 레코드를 `abandoned`로 자동 정리

### 추적 DB 직접 사용 (Python API)

```python
from tracking_db import get_tracker

tracker = get_tracker()

# 실행 시작 (기존 running 자동 superseded)
exec_id = tracker.start_execution('ISSUE-001', sheet_row=5, phase='analyze')
tracker.complete_execution(exec_id, 'success')

# 이슈의 모든 running 실행 닫기 (BLOCKED 처리 시)
tracker.complete_running_for_issue('ISSUE-001', status='blocked', error_message='4 fails')

# running 실행 조회
running = tracker.find_running_execution('ISSUE-001', phase='analyze')

# 장기 running 정리
closed = tracker.cleanup_stale(threshold_minutes=30)

# 상태 전이 / 에러 기록
tracker.record_transition('ISSUE-001', 'NEW', 'ANALYZING', triggered_by='agent')
tracker.log_error('ISSUE-001', 'analyze', 1, 'SyntaxError', 'unexpected token')
```

### 추적 DB 조회 CLI

```bash
python tracking_query.py summary [--issue KEY] [--json]
python tracking_query.py history ISSUE_KEY [--json]
python tracking_query.py errors [--limit 20] [--json]
python tracking_query.py metrics [--json]
python tracking_query.py recent [--limit 20] [--status S] [--json]
```

DB 위치: `.claude/data/sonar_tracking.db` (`TRACKING_DB_PATH` 환경변수로 오버라이드 가능)
