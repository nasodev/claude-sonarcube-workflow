---
name: sonar-intake
description: SonarQube에서 이슈를 수집하여 SQLite 로컬 DB에 저장합니다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write
---

# SonarQube Issue Intake

SonarQube API에서 코드 이슈를 수집하여 SQLite 로컬 DB에 저장합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | string | 필수 | project_id — 웹서비스 프로젝트 ID (`/sonar-setup`에서 사용한 ID) |

### Output

```json
{
  "status": "success | failed",
  "issues_added": 42,
  "duplicates_skipped": 5,
  "report_path": "reports/intake_report.md"
}
```

### 생성 파일

| 파일 | 소비자 | 설명 |
|------|--------|------|
| `$SONAR_PROJECT_DIR/data/{project_key}_{timestamp}/all_issues.json` | export_to_csv.sh | SonarQube API 원본 응답 |
| `$SONAR_PROJECT_DIR/data/{project_key}_{timestamp}/*.csv` | 데이터 백업 | CSV 변환 결과 |
| `$SONAR_PROJECT_DIR/reports/intake_report.md` | 사용자 | 수집 결과 요약 |
| `$SONAR_PROJECT_DIR/sonar.db` | sonar-analyze, sonar-develop | SQLite 로컬 DB (이슈 상태 관리) |

### SQLite DB 변경

| 변경 항목 | 설명 |
|----------|------|
| 이슈 upsert | 신규 이슈를 `upsert_issue()`로 저장 (상태: `NEW`) |
| 중복 제거 | `sonarqube_key` 기준으로 기존 이슈와 중복 시 스킵 (ON CONFLICT) |

### 저장되는 이슈 필드

| 필드 | 값 |
|------|-----|
| status | `NEW` |
| severity | Impact severity (HIGH / MEDIUM / LOW) |
| type | BUG / VULNERABILITY / CODE_SMELL |
| file_path | 소스 파일 경로 |
| line | 라인 번호 |
| message | SonarQube 이슈 메시지 |
| rule | SonarQube 규칙 ID |
| sonarqube_key | 이슈 고유 키 |
| clean_code_attribute | Clean Code Attribute (CONVENTIONAL, INTENTIONAL 등) |
| software_quality | Software Quality (MAINTAINABILITY, RELIABILITY, SECURITY) |

## 실행 흐름

> **중요**: 반드시 SonarQube API (`fetch_issues.sh`)로 이슈를 가져와야 합니다.
> 웹서비스(`web_client.py`)의 download/issues API에서 가져오면 안 됩니다.

1. `projects/` 폴더에서 `$ARGUMENTS[0]` (project_id)에 해당하는 프로젝트 디렉토리 찾기
   - 각 `projects/*/.env`의 `WEB_PROJECT_ID`를 확인하여 매칭
   - 매칭되는 프로젝트가 없으면 에러: "프로젝트를 찾을 수 없습니다. `/sonar-setup {project_id}`를 먼저 실행하세요"
   - `SONAR_PROJECT_DIR` 변수에 해당 프로젝트 경로 설정
2. `SONAR_PROJECT_DIR/.env` 로드 (env_loader)
3. SonarQube API에서 이슈 목록 조회: `SONAR_PROJECT_DIR=$SONAR_PROJECT_DIR bash ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-intake/scripts/fetch_issues.sh`
4. JSON 응답 파싱 (`all_issues.json`의 `.issues[]` 배열)
5. SQLite DB 초기화: `python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py init`
6. 각 이슈에 대해 `upsert_issue()` 호출하여 SQLite에 저장 (필드 매핑은 아래 참조)
7. JSON → CSV 변환 (`export_to_csv.sh`, 데이터 백업용)
8. `$SONAR_PROJECT_DIR/reports/intake_report.md` 생성
9. Output JSON 반환: `{status, issues_added, duplicates_skipped, report_path}`

### SonarQube JSON → upsert_issue() 필드 매핑

step 6에서 `all_issues.json`의 각 이슈를 아래 규칙으로 변환하여 `upsert_issue()`에 전달해야 합니다.

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

### 1. fetch_issues.sh

```bash
SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name> bash ./scripts/fetch_issues.sh
```

출력: `$SONAR_PROJECT_DIR/data/{project_key}_{timestamp}/all_issues.json`

### 2. export_to_csv.sh

```bash
./scripts/export_to_csv.sh -f data/xxx/all_issues.json
```

출력: `data/{basename}_{timestamp}.csv`

### 3. local_db.py

```bash
# DB 초기화
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py init

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

## 템플릿

- [templates/intake_report.md](templates/intake_report.md) - Intake 보고서 (수집 결과 요약)

> **필수**: intake_report.md 작성 시 반드시 위 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.
