---
name: sonar-intake
description: SonarQube에서 이슈를 수집하여 Google Sheets에 업로드합니다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write
hooks:
  Stop:
    - hooks:
        - type: command
          command: "$CLAUDE_PROJECT_DIR/.claude/hooks/save-history.sh"
---

# SonarQube Issue Intake

SonarQube API에서 코드 이슈를 수집하여 팀 공유 Google Sheets에 업로드합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | string | 선택 | project_key — SonarQube 프로젝트 키 (기본값: .env의 설정) |

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
| `data/{project_key}_{timestamp}/all_issues.json` | export_to_csv.sh | SonarQube API 원본 응답 |
| `data/{project_key}_{timestamp}/*.csv` | sheets_upload.py | CSV 변환 결과 |
| `reports/intake_report.md` | 사용자 | 수집 결과 요약 |

### 스프레드시트 변경

| 변경 항목 | 설명 |
|----------|------|
| 행 추가 | 신규 이슈를 행으로 추가 (상태: `대기`) |
| 중복 제거 | `SonarQube키` 기준으로 기존 행과 중복 시 스킵 |
| 헤더 포맷팅 | 첫 행 헤더에 스타일 적용 |

### 생성되는 행의 컬럼 값

| 컬럼 | 값 |
|------|-----|
| 상태 | `대기` |
| 담당자 | (빈 값) |
| Jira키 | (빈 값) |
| 심각도 | SonarQube severity |
| 품질 | SonarQube quality |
| 타입 | BUG / VULNERABILITY / CODE_SMELL |
| 파일 | 소스 파일 경로 |
| 라인 | 라인 번호 |
| 메시지 | SonarQube 이슈 메시지 |
| 규칙 | SonarQube 규칙 ID |
| CleanCode | Clean Code 속성 |
| SonarQube키 | 이슈 고유 키 |
| 생성일 | 이슈 생성 일시 |
| 이후 컬럼 | (빈 값 — 워크플로우 진행 시 채워짐) |

## 실행 흐름

1. SonarQube API에서 이슈 목록 조회
2. JSON → CSV 변환
3. Google Sheets에 업로드 (중복 제거)
4. intake_report.md 생성

## 스크립트

### 1. fetch_issues.sh

```bash
./scripts/fetch_issues.sh [project_key]
```

출력: `data/{project_key}_{timestamp}/all_issues.json`

### 2. export_to_csv.sh

```bash
./scripts/export_to_csv.sh -f data/xxx/all_issues.json
```

출력: `data/{basename}_{timestamp}.csv`

### 3. sheets_upload.py

```bash
python scripts/sheets_upload.py -f data/xxx.csv -s $SPREADSHEET_ID
```

## 템플릿

- [templates/intake_report.md](templates/intake_report.md) - Intake 보고서 (수집 결과 요약)

> **필수**: intake_report.md 작성 시 반드시 위 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.
