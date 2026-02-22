---
name: sonar-approve
description: DONE 상태 이슈를 승인하고 Jira 생성, 브랜치, 커밋, 머지를 자동 처리한다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write
---

# SonarQube Issue Approve

DONE 상태 이슈를 승인하고 Jira 생성 -> 브랜치 -> 커밋 -> 머지를 자동 처리합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 프로젝트 컨텍스트

> **필수**: `SONAR_PROJECT_DIR` 환경변수가 **절대 경로**로 설정되어 있어야 합니다 (예: `$CLAUDE_PROJECT_DIR/projects/odin-addsvc`).
> 오케스트레이터가 `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`를 설정합니다.
> 모든 경로(worktrees, reports, repo, sonar.db)는 `$SONAR_PROJECT_DIR` 하위입니다.

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
  "jira_key": "PROJ-123",
  "branch": "fix/PROJ-123",
  "message": "설명"
}
```

### 읽기 의존 파일

진행 전 반드시 존재를 확인해야 하는 파일:

| 파일 | 생성 주체 | 용도 |
|------|----------|------|
| `$SONAR_PROJECT_DIR/reports/<issue_key>/07_final_deliverable.md` | sonar-develop | 커밋 메시지 및 설명 추출 (개별 이슈) |
| `$SONAR_PROJECT_DIR/reports/group-<name>/07_final_deliverable.md` | sonar-develop | 커밋 메시지 및 설명 추출 (그룹 이슈) |

> **주의**: 읽기 의존 파일이 존재하지 않으면 진행 불가. 상태를 재확인하고 에러 보고.

### SQLite DB 변경

| 변경 항목 | 값 | 시점 |
|----------|-----|------|
| status | `APPROVED` | 승인 완료 시 |
| jira_key | `PROJ-123` | Jira 이슈 생성 후 |

> **상태 업데이트**: `local_db.update_status(sonarqube_key, "APPROVED", jira_key=jira_key)` 호출로 상태를 변경합니다.

## 사전 조건

- 이슈 상태가 DONE이어야 한다
- `$SONAR_PROJECT_DIR/worktrees/<issue_key>/` 에 수정된 코드가 있어야 한다
- `$SONAR_PROJECT_DIR/reports/<issue_key>/07_final_deliverable.md` 가 존재해야 한다 (그룹: `reports/group-<name>/07_final_deliverable.md`)
- `.env`에 JIRA_URL, JIRA_PROJECT_KEY가 설정되어 있어야 한다

## 워크플로우

### 1. 이슈 상태 확인

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get <sonarqube_key>
```

status가 DONE이 아니면 에러 반환.

### 2. Jira 이슈 생성

`.env`에서 JIRA_URL, JIRA_ID, JIRA_PASSWORD, JIRA_PROJECT_KEY를 읽는다.
`$SONAR_PROJECT_DIR/reports/<issue_key>/07_final_deliverable.md` (그룹: `reports/group-<name>/07_final_deliverable.md`)에서 커밋 메시지와 설명을 추출한다.
Jira REST API로 이슈를 생성한다:

```bash
curl -u "$JIRA_ID:$JIRA_PASSWORD" \
  -X POST "$JIRA_URL/rest/api/2/issue" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "project": {"key": "'$JIRA_PROJECT_KEY'"},
      "summary": "SonarQube: <이슈 요약>",
      "description": "<분석 보고서 내용>",
      "issuetype": {"name": "Task"}
    }
  }'
```

### 3. Jira키로 브랜치 생성

```bash
cd $SONAR_PROJECT_DIR/worktrees/<issue_key>
git checkout -b fix/<JIRA_KEY>
```

### 4. 변경사항 커밋

`07_final_deliverable.md`에서 커밋 메시지를 추출하여 사용:

```bash
cd $SONAR_PROJECT_DIR/worktrees/<issue_key>
git add -A
git commit -m "<커밋 메시지>"
```

### 5. 브랜치 push

```bash
cd $SONAR_PROJECT_DIR/worktrees/<issue_key>
git push -u origin fix/<JIRA_KEY>
```

### 6. 메인 브랜치에 머지

```bash
cd $SONAR_PROJECT_DIR/repo/<project>
git checkout <main_branch>
git merge fix/<JIRA_KEY>
git push
```

### 7. 상태 업데이트

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get <sonarqube_key>
```

```python
from local_db import update_status, add_execution

update_status(key, "APPROVED", jira_key=jira_key)
add_execution(key, "approve", "success", details={"jira_key": jira_key})
```

## 그룹 이슈 승인

`group-<name>`인 경우:

- 그룹에 속한 모든 이슈의 상태를 DONE -> APPROVED로 변경
- 하나의 Jira 이슈를 생성 (그룹 전체에 대해)
- 워크트리 `$SONAR_PROJECT_DIR/worktrees/group-<name>/`에서 커밋/푸시

## 상태 흐름

```
DONE → APPROVED
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

update_status(sonarqube_key, "APPROVED", jira_key="PROJ-123")
add_execution(sonarqube_key, "approve", "success", details="jira_key=PROJ-123")
```
