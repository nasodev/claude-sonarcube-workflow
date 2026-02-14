---
name: sonar-common
description: SonarQube 워크플로우 공통 모듈. 환경변수 로더, Google Sheets 클라이언트 및 유틸리티 함수 제공.
user-invocable: false
---

# SonarQube Common Module

내부 스킬들이 공유하는 공통 모듈입니다.

## 제공 기능

- `env_loader.py`: 환경변수 로더 (.env 파일 관리)
- `sheets_client.py`: Google Sheets CRUD 클라이언트
- `validate_issue_key.py`: 이슈 키 검증 (ROW의 SonarQube키와 issue_key 일치 확인)
- `tracking_db.py`: SQLite 실행 추적 DB (에이전트용 로컬 추적)
- `tracking_query.py`: 추적 DB 조회 CLI

## 스프레드시트 컬럼 스키마 (정규 정의)

> 이 테이블이 모든 스킬의 issue_data JSON 필드의 **단일 원천(Single Source of Truth)**입니다.
> `sheets_client.py`의 `COL_*` 상수와 1:1 대응합니다.

| 인덱스 | 상수명 | 헤더 | JSON 키 | 설명 |
|--------|--------|------|---------|------|
| 0 | `COL_STATUS` | 상태 | `상태` | 워크플로우 상태 (대기, CLAIMED, ANALYZING, ...) |
| 1 | `COL_ASSIGNEE` | 담당자 | `담당자` | 담당 에이전트/사람 이름 |
| 2 | `COL_JIRA_KEY` | Jira키 | `Jira키` | Jira 티켓 번호 (예: ODIN-123) |
| 3 | `COL_SEVERITY` | 심각도 | `심각도` | BLOCKER, CRITICAL, MAJOR, MINOR, INFO |
| 4 | `COL_QUALITY` | 품질 | `품질` | RELIABILITY, SECURITY, MAINTAINABILITY |
| 5 | `COL_TYPE` | 타입 | `타입` | BUG, VULNERABILITY, CODE_SMELL |
| 6 | `COL_FILE` | 파일 | `파일` | 소스 코드 파일 경로 |
| 7 | `COL_LINE` | 라인 | `라인` | 소스 코드 라인 번호 |
| 8 | `COL_MESSAGE` | 메시지 | `메시지` | SonarQube 이슈 메시지 |
| 9 | `COL_RULE` | 규칙 | `규칙` | SonarQube 규칙 ID (예: java:S1172) |
| 10 | `COL_CLEAN_CODE` | CleanCode | `CleanCode` | Clean Code 속성 |
| 11 | `COL_SONAR_KEY` | SonarQube키 | `SonarQube키` | 이슈 고유 식별자 |
| 12 | `COL_CREATED` | 생성일 | `생성일` | 이슈 생성 일시 |
| 13 | `COL_LOCK_TS` | 할당시각 | `할당시각` | Claim 시 잠금 타임스탬프 |
| 14 | `COL_ATTEMPT_ANALYSIS` | 분석시도 | `분석시도` | 분석 시도 횟수 |
| 15 | `COL_ATTEMPT_FIX` | 수정시도 | `수정시도` | 수정 시도 횟수 |
| 16 | `COL_REPORT_URL` | 보고서 | `보고서` | 보고서 파일 경로/URL |
| 17 | `COL_LAST_ERROR` | 에러 | `에러` | 최근 에러 메시지 |
| 18 | `COL_APPROVED_BY` | 승인자 | `승인자` | 승인한 사람 이름 |
| 19 | `COL_APPROVED_TS` | 승인시각 | `승인시각` | 승인 타임스탬프 |

**특수 필드**: `_row` (인덱스 없음) — `sheets_client.py`의 `get_all_issues()`가 자동 추가. 스프레드시트 행 번호 (2부터 시작, 1은 헤더).

## 환경 설정

1. `.env.example`을 프로젝트 루트에 `.env`로 복사
2. 환경변수 값 설정
3. `credentials.json` (Google 서비스 계정 키) 배치

## 사용법

다른 스킬에서 import:

```python
import sys
sys.path.insert(0, '/path/to/sonar-common/scripts')
from env_loader import load_env, get_env
from sheets_client import SheetsClient

load_env()  # .env 파일 로드
spreadsheet_id = get_env('SPREADSHEET_ID')
```

### 이슈 키 검증

```bash
# 보고서/워크트리 생성 전 필수 실행
python .claude/skills/sonar-common/scripts/validate_issue_key.py \
  -r ROW -k ISSUE_KEY -s SPREADSHEET_ID

# JSON 출력 모드
python .claude/skills/sonar-common/scripts/validate_issue_key.py \
  -r ROW -k ISSUE_KEY -s SPREADSHEET_ID --json
```

- Exit 0: 일치 (검증 통과)
- Exit 1: 불일치 또는 오류 (검증 실패)

### 추적 DB — 자동 추적 (sheets_update.py 연동)

`sheets_update.py --status` 호출 시 실행 추적이 **자동으로** 관리됩니다:

| 상태 전환 | 자동 동작 |
|---|---|
| → `ANALYZING` | `start_execution(phase='analyze')` |
| → `JIRA_CREATED` / `REPORT_CREATED` | `complete_execution(phase='analyze', 'success')` |
| → `DEVELOPING` | `start_execution(phase='develop')` |
| → `DONE` | `complete_execution(phase='develop', 'success')` |
| → `BLOCKED` | `complete_running_for_issue('blocked')` — 모든 running 레코드 닫음 |

**에이전트가 별도로 `--start-exec`/`--complete-exec` 플래그를 전달할 필요 없음.**

추가 보호 기능:
- `--issue-key` 생략 시 ROW에서 SonarQube키 자동 추출
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
tracker.record_transition('ISSUE-001', 'CLAIMED', 'ANALYZING', triggered_by='agent')
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
