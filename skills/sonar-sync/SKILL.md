---
name: sonar-sync
description: 변경된 이슈를 웹서비스에 업로드합니다.
user-invocable: true
argument-hint: "--id=<project_id>"
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write
---

# SonarQube Data Sync (Upload Only)

## Arguments

$ARGUMENTS

변경된 이슈만 웹서비스에 업로드합니다. 단방향 (로컬 → 서버).

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## Data Contract

### Input

위 **Arguments** 섹션의 값에서 `--id=<값>` 형식으로 **project_id**를 추출합니다.

**파싱 규칙:**
- Arguments에서 `--id=` 뒤의 값을 project_id로 사용
- 예: `--id=1` → project_id는 `1`
- `--id=`가 없거나 Arguments가 비어있으면 즉시 에러를 출력하고 종료합니다:

```json
{"status": "failed", "uploaded": 0, "message": "--id 파라미터가 필요합니다. 사용법: /sonar-sync --id=<project_id>"}
```

### 프로젝트 디렉토리 해석

project_id로 `SONAR_PROJECT_DIR`을 설정합니다:

1. `$CLAUDE_PROJECT_DIR/projects/*/.env` 에서 `WEB_PROJECT_ID`(숫자) 또는 `PROJECT_NAME`(문자열) 매칭
2. 매칭 성공 시 → `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`
3. 매칭 실패 시 → 에러 출력 후 종료:

```json
{"status": "failed", "uploaded": 0, "message": "프로젝트를 찾을 수 없습니다. /sonar-setup --id=<project_id>를 먼저 실행하세요"}
```

환경변수 로드 (프로젝트 `.env`와 루트 `.env`):
- `WEB_SERVICE_URL`: 웹서비스 URL (필수)
- `WEB_PROJECT_ID`: 웹서비스 프로젝트 ID (필수)
- `ASSIGNEE_NAME`: 담당자 이름 (필수)

### Output

```json
{
  "status": "success",
  "uploaded": 10,
  "skipped": 0
}
```

## 워크플로우

### 1. 환경변수 검증

```python
import os
web_url = os.environ.get("WEB_SERVICE_URL")
project_id = os.environ.get("WEB_PROJECT_ID")
assignee = os.environ.get("ASSIGNEE_NAME")

if not web_url:
    print("WEB_SERVICE_URL이 설정되지 않았습니다. 오프라인 모드로 동작합니다.")
    # 결과 출력 후 종료
    sys.exit(0)

if not project_id:
    print("Error: WEB_PROJECT_ID가 설정되지 않았습니다.")
    sys.exit(1)

if not assignee:
    print("Error: ASSIGNEE_NAME이 설정되지 않았습니다.")
    sys.exit(1)
```

### 2. 변경된 이슈 조회

```python
from local_db import get_changed_for_sync

changed = get_changed_for_sync()
if not changed:
    print("동기화할 변경사항이 없습니다.")
    # 결과 JSON 출력 후 종료
```

### 3. 데이터 변환 (업로드용)

전송할 필드만 추출:

```python
upload_issues = []
for issue in changed:
    upload_issues.append({
        "sonarqube_key": issue["sonarqube_key"],
        "status": issue["status"],
        "jira_key": issue.get("jira_key") or "",
    })
```

### 4. 웹서비스 업로드

```python
from web_client import upload_results

result = upload_results(int(project_id), upload_issues, assignee)
```

### 5. 성공 건 synced_at 갱신

```python
from local_db import mark_synced

success_keys = result.get("success", [])
if success_keys:
    mark_synced(success_keys)
```

## 에러 처리

| 시나리오 | 동작 |
|----------|------|
| WEB_SERVICE_URL 미설정 | 안내 메시지 출력 후 정상 종료 |
| WEB_PROJECT_ID 미설정 | 에러 출력 후 종료 |
| ASSIGNEE_NAME 미설정 | 에러 출력 후 종료 |
| 네트워크 실패 | synced_at 미갱신, 에러 보고 |
| 부분 성공 | 성공 건만 synced_at 갱신, 실패 건 로그 |

## 스크립트

### local_db.py (변경분 조회 및 동기화 마킹)

```bash
# 변경된 이슈 export
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py export
```

```python
# Python API
from local_db import get_changed_for_sync, mark_synced

# 변경분만 조회 (synced_at IS NULL OR updated_at > synced_at)
changed = get_changed_for_sync()

# 동기화 완료 마킹 (성공 건만)
mark_synced(["KEY1", "KEY2"])
```

### web_client.py (웹서비스 업로드)

```python
# Python API
from web_client import upload_results

# 변경 이슈 업로드
result = upload_results(project_id, issues, assignee)
# result: {"success": ["KEY1", "KEY2"], "failed": ["KEY3"]}
```
