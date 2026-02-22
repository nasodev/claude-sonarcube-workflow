---
name: sonar-setup
description: 프로젝트 초기 환경 구성 + 이슈 수집. 웹서비스에서 프로젝트 정보를 가져와 환경을 설정하고 SonarQube 이슈를 수집한다.
user-invocable: true
argument-hint: "--id=<project_id>"
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write
---

# SonarQube Project Setup + Issue Intake

## Arguments

$ARGUMENTS

웹서비스에서 프로젝트 정보를 가져와 로컬 환경을 구성하고, SonarQube API에서 이슈를 수집하여 SQLite에 저장합니다.

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
{"status": "failed", "project_name": "", "project_dir": "", "message": "--id 파라미터가 필요합니다. 사용법: /sonar-setup --id=<project_id>"}
```

### Output

```json
{
  "status": "success | failed",
  "project_name": "프로젝트명",
  "project_dir": "projects/프로젝트명",
  "issues_added": 42,
  "duplicates_skipped": 5,
  "message": "설명"
}
```

## 워크플로우

### Step 1: 루트 .env에서 WEB_SERVICE_URL 확인

```bash
cat "$CLAUDE_PROJECT_DIR/.env" 2>/dev/null | grep WEB_SERVICE_URL
```

- `WEB_SERVICE_URL`이 비어있거나 없으면 → 에러 출력 후 종료:

```json
{"status": "failed", "project_name": "", "project_dir": "", "message": "루트 .env에 WEB_SERVICE_URL을 설정하세요"}
```

### Step 2: 웹서비스에서 프로젝트 정보 조회

```bash
WEB_SERVICE_URL=<url> python "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/web_client.py" project $PROJECT_ID
```

응답에서 프로젝트 정보 추출:
- 프로젝트명 (name)
- SonarQube: sonarqube_url, sonarqube_token, sonarqube_project_key
- Jira: jira_url, jira_project_key
- Repo: repo_url, repo_branch

### Step 3: 프로젝트 디렉토리 중복 확인

```bash
ls -d "$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME" 2>/dev/null
```

- 디렉토리가 이미 존재하면 → 기존 환경을 재사용하므로 계속 진행 (덮어쓰기)

### Step 4: 루트 .env 생성 (최초 1회)

`$CLAUDE_PROJECT_DIR/.env` 파일이 존재하지 않을 때만 생성. 이미 있으면 건드리지 않음.

생성 시 내용:

```
# 공통 설정 — 최초 생성됨
WEB_SERVICE_URL=
JIRA_ID=
JIRA_PASSWORD=
ASSIGNEE_NAME=
MAX_CONCURRENT_AGENTS=5
```

### Step 5: 프로젝트 폴더 구조 생성

```bash
mkdir -p "$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME"/{data,repo,worktrees,reports}
```

### Step 6: 프로젝트별 .env 생성

`$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME/.env` 파일에 다음 내용을 작성:

```
# 자동 생성됨 - sonar-setup
WEB_PROJECT_ID=<project_id>
PROJECT_NAME=<프로젝트명>
SONARQUBE_URL=<url>
SONARQUBE_TOKEN=<token>
SONARQUBE_PROJECT_KEY=<key>
JIRA_URL=<url 또는 빈 값>
JIRA_PROJECT_KEY=<key 또는 빈 값>
REPO_URL=<url>
REPO_BRANCH=<branch>
REPO_PATH=repo/<프로젝트명>
```

### Step 7: 소스코드 클론

```bash
git clone "$REPO_URL" -b "$REPO_BRANCH" "$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME/repo/$PROJECT_NAME"
```

- 실패 시: 에러 메시지를 출력하되, `.env`와 폴더 구조는 유지. 수동 클론을 안내.

### Step 8: SQLite DB 초기화

```bash
SONAR_PROJECT_DIR="$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME" python "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py" init
```

### Step 9: SonarQube 이슈 수집

> **중요**: 반드시 SonarQube API (`fetch_issues.sh`)로 이슈를 가져와야 합니다.
> 웹서비스(`web_client.py`)의 download/issues API에서 가져오면 안 됩니다.

```bash
SONAR_PROJECT_DIR="$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME" bash "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-intake/scripts/fetch_issues.sh"
```

출력: `$SONAR_PROJECT_DIR/data/{project_key}_{timestamp}/all_issues.json`

### Step 10: 이슈 SQLite 저장

`all_issues.json`의 `.issues[]` 배열을 파싱하여 각 이슈를 `upsert_issue()`로 SQLite에 저장합니다.

**SonarQube JSON → upsert_issue() 필드 매핑:**

| SonarQube JSON 필드 | upsert_issue 키 | 변환 규칙 |
|---------------------|-----------------|-----------|
| `.key` | `sonarqube_key` | 그대로 |
| (고정값) | `status` | 항상 `"NEW"` |
| `.impacts[0].severity` | `severity` | `HIGH` / `MEDIUM` / `LOW` (레거시 `.severity` 사용 금지) |
| `.type` | `type` | `BUG` / `VULNERABILITY` / `CODE_SMELL` |
| `.component` | `file_path` | `":"` 뒤 부분만 추출 (예: `"project:src/Foo.java"` → `"src/Foo.java"`) |
| `.line` | `line` | 정수, 없으면 `null` |
| `.message` | `message` | 그대로 |
| `.rule` | `rule` | 그대로 (예: `"java:S1172"`) |
| `.cleanCodeAttribute` | `clean_code_attribute` | `CONVENTIONAL` / `INTENTIONAL` / `ADAPTIVE` / `RESPONSIBLE` 등 |
| `.impacts[0].softwareQuality` | `software_quality` | `MAINTAINABILITY` / `RELIABILITY` / `SECURITY` |

> **주의**: `.severity` (레거시: BLOCKER/CRITICAL/MAJOR/MINOR/INFO)가 아닌 `.impacts[0].severity` (Clean Code Taxonomy: HIGH/MEDIUM/LOW)를 사용합니다.

```bash
# 이슈 저장 (Python API)
from local_db import upsert_issue
upsert_issue({
    "sonarqube_key": "AYxx...",
    "status": "NEW",
    "severity": "HIGH",
    "type": "BUG",
    "file_path": "src/main/java/Foo.java",
    "line": 42,
    "message": "...",
    "rule": "java:S1172",
    "clean_code_attribute": "INTENTIONAL",
    "software_quality": "RELIABILITY"
})
```

### Step 11: Intake 보고서 생성

`$SONAR_PROJECT_DIR/reports/intake_report.md` 생성.

> **필수**: 반드시 [templates/intake_report.md](../sonar-intake/templates/intake_report.md) 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.

### Step 12: 결과 출력

```json
{
  "status": "success",
  "project_name": "<프로젝트명>",
  "project_dir": "projects/<프로젝트명>",
  "issues_added": 42,
  "duplicates_skipped": 5,
  "message": "프로젝트 환경 구성 및 이슈 수집 완료"
}
```

## 페이지네이션 및 10,000건 제한

SonarQube API `/api/issues/search`는 `p * ps > 10,000`이면 에러를 반환하는 **하드 리밋**이 있습니다.

### 기본 동작 (≤ 10,000건)
- `resolved=false` 필터로 미해결 이슈만 수집
- `p` (page) 파라미터를 증가시키며 반복 호출
- 빈 페이지(`issues: []`) 반환 시 graceful하게 루프 종료

### 10,000건 초과 프로젝트
`fetch_issues.sh`가 자동으로 쿼리를 분할합니다:

1. **types 분할**: BUG, VULNERABILITY, CODE_SMELL 각각 별도 조회
2. **impactSeverities 분할**: 특정 type이 여전히 > 10k이면 HIGH, MEDIUM, LOW로 추가 분할
3. **날짜 범위 분할**: 여전히 > 10k이면 `createdAfter/createdBefore`로 날짜 범위를 이진 분할
4. **중복 제거**: 분할 조회 결과를 `key` 기준 `unique_by`로 병합

## 스크립트

### web_client.py (프로젝트 정보 조회)

```bash
WEB_SERVICE_URL=<url> python "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/web_client.py" project <project_id>
```

### local_db.py (DB 초기화 / 이슈 저장)

```bash
# SQLite DB 초기화
SONAR_PROJECT_DIR="$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME" python "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py" init
```

### fetch_issues.sh (SonarQube 이슈 수집)

```bash
SONAR_PROJECT_DIR="$CLAUDE_PROJECT_DIR/projects/$PROJECT_NAME" bash "${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-intake/scripts/fetch_issues.sh"
```

출력: `$SONAR_PROJECT_DIR/data/{project_key}_{timestamp}/all_issues.json`
