---
name: sonar-reject
description: DONE 상태 이슈를 반려하고 워크트리/리포트를 제거한다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read
---

# SonarQube Issue Reject

DONE 상태 이슈를 반려(BLOCKED)하고 관련 워크트리와 리포트를 제거합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 프로젝트 컨텍스트

> **필수**: `SONAR_PROJECT_DIR` 환경변수가 **절대 경로**로 설정되어 있어야 합니다 (예: `$CLAUDE_PROJECT_DIR/projects/odin-addsvc`).
> 오케스트레이터가 `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`를 설정합니다.
> 모든 경로(worktrees, reports, sonar.db)는 `$SONAR_PROJECT_DIR` 하위입니다.

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | string | 필수 | sonarqube_key 또는 group-name |

### Output

```json
{
  "status": "success | failed",
  "sonarqube_key": "KEY",
  "message": "설명"
}
```

### SQLite DB 변경

| 변경 항목 | 값 | 시점 |
|----------|-----|------|
| status | `BLOCKED` | 반려 완료 시 |

> **상태 업데이트**: `local_db.update_status(sonarqube_key, "BLOCKED")` 호출로 상태를 변경합니다.

## 사전 조건

- 이슈 상태가 DONE이어야 한다

## 워크플로우

### 1. 이슈 상태 확인

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get <sonarqube_key>
```

status가 DONE이 아니면 에러 반환.

### 2. 워크트리 제거

```bash
# 개별 이슈
rm -rf $SONAR_PROJECT_DIR/worktrees/<issue_key>

# 그룹 이슈
rm -rf $SONAR_PROJECT_DIR/worktrees/group-<name>
```

> git worktree로 생성된 경우 `git worktree remove`를 먼저 시도하고, 실패하면 `rm -rf`로 제거합니다.

### 3. 리포트 제거

```bash
# 개별 이슈
rm -rf $SONAR_PROJECT_DIR/reports/<issue_key>

# 그룹 이슈
rm -rf $SONAR_PROJECT_DIR/reports/group-<name>
```

### 4. 상태 업데이트

```python
from local_db import update_status, add_execution

update_status(sonarqube_key, "BLOCKED")
add_execution(sonarqube_key, "reject", "success", details="사용자 반려")
```

## 그룹 이슈 반려

`group-<name>`인 경우:

1. 그룹에 속한 모든 DONE 이슈의 상태를 BLOCKED로 변경
2. 각 이슈별 리포트 제거 (`$SONAR_PROJECT_DIR/reports/<issue_key>/`)
3. 그룹 워크트리 제거 (`$SONAR_PROJECT_DIR/worktrees/group-<name>/`)
4. 그룹 리포트 제거 (`$SONAR_PROJECT_DIR/reports/group-<name>/`)
5. 각 이슈별 execution 기록

## 상태 흐름

```
DONE → BLOCKED (반려)
```

## 스크립트

### local_db.py (상태 업데이트)

```bash
# 이슈 조회
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get <sonarqube_key>
```

```python
# Python API로 상태 업데이트
from local_db import update_status, add_execution

update_status(sonarqube_key, "BLOCKED")
add_execution(sonarqube_key, "reject", "success", details="사용자 반려")
```
