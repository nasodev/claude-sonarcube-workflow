---
name: sonar-group
description: 단순하고 동일한 종류의 이슈를 자동 그룹화한다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write, Grep, Glob
---

# SonarQube Issue Grouping

단순하고 동일한 종류의 이슈를 자동으로 그룹화합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 프로젝트 컨텍스트

> **필수**: `SONAR_PROJECT_DIR` 환경변수가 **절대 경로**로 설정되어 있어야 합니다 (예: `$CLAUDE_PROJECT_DIR/projects/odin-addsvc`).
> 오케스트레이터가 `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`를 설정합니다.
> 모든 경로(worktrees, reports, repo, sonar.db)는 `$SONAR_PROJECT_DIR` 하위입니다.

## Data Contract

### Input

없음 (현재 프로젝트의 SQLite DB에서 NEW 상태 이슈를 읽음)

### Output

```json
{
  "status": "success",
  "groups_created": 3,
  "issues_grouped": 25,
  "issues_individual": 15,
  "report_path": "reports/20260219_group_report.md",
  "groups": [
    {"name": "group-fstring-fix", "rule": "python:S3457", "count": 10},
    {"name": "group-unused-imports", "rule": "python:S1128", "count": 8}
  ]
}
```

### SQLite DB 변경

| 변경 항목 | 값 | 시점 |
|----------|-----|------|
| groups 테이블 | `group-<설명>` 이름으로 그룹 생성 | 그룹화 결정 시 |
| issues.group_id | 생성된 그룹의 ID | 그룹화 결정 시 |

> **그룹 생성**: `local_db.create_group(name, rule, description)` 로 그룹을 생성하고, `local_db.update_status(sonarqube_key, status, group_id=group_id)` 로 이슈에 할당합니다.

## 워크플로우

### 1. SQLite에서 NEW 상태 이슈 전체 조회

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py status
```

### 2. rule별 이슈 집계

같은 rule을 가진 이슈들을 집계한다.

### 3. 복잡도 판단 (rule별)

각 rule의 대표 이슈 2-3개의 소스코드를 읽고 복잡도를 판단한다:

- **단순 패턴** (그룹화 대상): fstring 변환, unused import 제거, 미사용 변수 제거,
  타입 힌트 추가, 불필요한 세미콜론 등 기계적으로 수정 가능한 이슈
- **복잡한 패턴** (개별 처리): 비즈니스 로직 변경, 리팩토링 필요, 컨텍스트 의존적 수정

### 4. 그룹 생성

단순 패턴으로 판단된 rule의 이슈들을 그룹으로 묶는다:

- 그룹명: `group-<설명>` (예: `group-fstring-fix`, `group-unused-imports`)
- `groups` 테이블에 그룹 생성 후 `issues.group_id` 할당

```python
from local_db import create_group, get_group_by_name, update_status

# 그룹 생성 (이미 존재하면 기존 ID 반환)
group_id = create_group("group-fstring-fix", rule="python:S3457", description="f-string 변환")

# 그룹에 속하는 각 이슈에 group_id 설정
update_status(sonarqube_key, "NEW", group_id=group_id)
```

### 5. 결과 리포트 출력

그룹화 결과를 JSON으로 출력한다.

### 6. 그룹화 보고서 파일 저장

그룹화 결과를 마크다운 파일로 저장한다.

- **파일 경로**: `$SONAR_PROJECT_DIR/reports/YYYYMMDD_group_report.md`
- 같은 날 다시 실행하면 덮어씀 (최신 결과만 유지)

**보고서 형식:**

```markdown
# 그룹화 보고서

| 항목 | 값 |
|------|-----|
| 프로젝트 | {PROJECT_NAME} |
| 실행일시 | YYYY-MM-DD HH:MM:SS |
| 상태 | success |

## 요약

| 항목 | 건수 |
|------|------|
| 전체 NEW 이슈 | {total} |
| 그룹화됨 | {grouped} |
| 개별 처리 | {individual} |
| 생성된 그룹 | {group_count} |

## 그룹 목록

| 그룹 | 규칙 | 건수 | 설명 |
|------|------|------|------|
| group-fstring-fix | S3457 | 294 | 불필요한 f-string 접두어 제거 |
| ... | ... | ... | ... |

## 개별 처리 대상 (규칙별 집계)

| 규칙 | 건수 | 설명 |
|------|------|------|
| python:S1192 | 667 | 문자열 중복 |
| ... | ... | ... |
```

**저장 방법:**

Step 5에서 수집한 결과 데이터를 바탕으로 마크다운 문자열을 조립하고, `Write` 도구로 저장한다.

```python
import os
from datetime import datetime

report_dir = os.path.join(os.environ["SONAR_PROJECT_DIR"], "reports")
os.makedirs(report_dir, exist_ok=True)
report_path = os.path.join(report_dir, f"{datetime.now().strftime('%Y%m%d')}_group_report.md")
# Write 도구로 report_path에 마크다운 내용 저장
```

## 스크립트

### local_db.py (이슈 조회 및 그룹 업데이트)

```bash
# 전체 이슈 상태 조회
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py status

# 단일 이슈 조회
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get <sonarqube_key>
```

```python
# Python API로 그룹 생성 및 이슈 할당
from local_db import get_issues, create_group, get_group_by_name, update_status

# NEW 상태 이슈 조회
issues = get_issues(status="NEW")

# 그룹 생성 (이미 존재하면 기존 ID 반환)
group_id = create_group("group-unused-imports", rule="python:S1128", description="unused import 제거")

# 이슈에 그룹 할당
update_status(sonarqube_key, "NEW", group_id=group_id)
```

## 복잡도 판단 기준

### 단순 패턴 (그룹화 대상)

| 규칙 유형 | 예시 |
|----------|------|
| fstring 변환 | `python:S3457` |
| unused import 제거 | `python:S1128`, `java:S1128` |
| 미사용 변수 제거 | `python:S1481`, `java:S1481` |
| 타입 힌트 추가 | `python:S5765` |
| 불필요한 세미콜론 | `java:S1116` |
| 단순 코드 포맷팅 | 들여쓰기, 공백 등 |

### 복잡한 패턴 (개별 처리)

| 규칙 유형 | 이유 |
|----------|------|
| 비즈니스 로직 변경 | 컨텍스트 이해 필요 |
| 리팩토링 필요 | 구조적 변경 |
| 보안 취약점 | 세밀한 분석 필요 |
| 동시성 이슈 | 사이드이펙트 위험 |
