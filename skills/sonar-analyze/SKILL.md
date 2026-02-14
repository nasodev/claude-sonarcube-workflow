---
name: sonar-analyze
description: CLAIMED 상태 이슈를 분석하고 Jira 생성 또는 리포트 생성. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
hooks:
  Stop:
    - hooks:
        - type: command
          command: "$CLAUDE_PROJECT_DIR/.claude/hooks/save-history.sh"
---

# SonarQube Issue Analysis

CLAIMED 상태의 이슈를 분석하고, Review Agent 검증 후 Jira 티켓 또는 리포트를 생성합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | number | 필수 | issue_row — 스프레드시트 행 번호 |
| `$ARGUMENTS[1]` | JSON string | 필수 | issue_data — 이슈 정보 (아래 필수 필드 참조) |
| `$ARGUMENTS[2]` | string | 선택 | `--no-jira` — Jira 생성 안함 (리포트 모드 강제) |

**issue_data 필수 필드:**

| 필드 | 용도 |
|------|------|
| `_row` | 스프레드시트 행 번호 (상태 업데이트) |
| `파일` | 소스 코드 파일 경로 (분석 대상) |
| `라인` | 소스 코드 라인 번호 (분석 대상) |
| `메시지` | SonarQube 이슈 메시지 (문제 요약에 사용) |
| `규칙` | SonarQube 규칙 ID (예: `java:S1172`) |
| `SonarQube키` | 이슈 고유 식별자 (리포트 모드 시 폴더명) |
| `심각도` | 이슈 심각도 (Jira 우선순위 매핑) |
| `타입` | 이슈 타입 — BUG, VULNERABILITY, CODE_SMELL |
| `담당자` | 담당자 이름 (보고서 메타데이터) |

### Output

#### Jira 모드
```json
{
  "status": "success | failed | blocked",
  "jira_key": "ODIN-123",
  "report_path": "reports/ODIN-123/01_analysis_report.md",
  "attempt": 1
}
```

#### 리포트 모드
```json
{
  "status": "success | failed | blocked",
  "issue_key": "AYxx...",
  "report_path": "reports/AYxx.../01_analysis_report.md",
  "jira_report_path": "reports/AYxx.../03_jira_report.md",
  "attempt": 1
}
```

### 생성 파일

| 파일 | 소비자 | 필수 섹션 |
|------|--------|----------|
| `reports/{issue_key}/01_analysis_report.md` | sonar-review (analysis), sonar-develop | 문제 요약, 원인 분석, 영향범위, 해결 방안, 검증 계획 |
| `reports/{issue_key}/03_jira_created.md` | sonar-develop (Jira 모드) | Jira 키, 생성 결과 |
| `reports/{issue_key}/03_jira_report.md` | sonar-develop (리포트 모드) | Jira 형식 리포트 전문 |

### 스프레드시트 변경

| 변경 항목 | 값 | 시점 | 자동 추적 |
|----------|-----|------|-----------|
| 상태 | `ANALYZING` | 분석 시작 시 | `start_execution(analyze)` 자동 |
| 상태 | `REVIEW_ANALYSIS` | 보고서 작성 완료 시 | — |
| 상태 | `JIRA_CREATED` / `REPORT_CREATED` | 리뷰 PASS + Jira/리포트 생성 후 | `complete_execution(analyze, success)` 자동 |
| 상태 | `BLOCKED` | 4회 시도 실패 시 | `complete_running_for_issue(blocked)` 자동 |
| 분석시도 | 카운터 +1 | 각 시도마다 | — |
| Jira키 | `ODIN-123` | Jira 생성 성공 시 (Jira 모드) | — |
| 에러 | 에러 메시지 | 실패 시 | — |

> **자동 추적**: `sheets_update.py --status` 호출 시 실행 추적이 자동으로 관리됩니다. `--start-exec`/`--complete-exec` 플래그 불필요. `--issue-key` 생략 시 ROW에서 자동 추출.

### sonar-review 호출 규약

```
Skill("sonar-review", args: "analysis {report_path} {issue_data_json}")
```

반환값: `{verdict: "PASS"|"FAIL", reason, suggestions[]}`
- PASS → Jira/리포트 생성 진행
- FAIL → suggestions 반영 후 재시도 (최대 3회 재시도, 총 4회)

## 입력 (요약)

- `$ARGUMENTS[0]`: issue_row (스프레드시트 행 번호)
- `$ARGUMENTS[1]`: issue_data (JSON 형식의 이슈 정보)
- `$ARGUMENTS[2]`: --no-jira (선택, Jira 생성 안함)

## Jira 모드 vs 리포트 모드

### Jira 모드 (기본)
- `JIRA_ENABLED=true` 환경변수 (기본값)
- 분석 완료 후 Jira 티켓 실제 생성
- 상태: ANALYZING → REVIEW_ANALYSIS → **JIRA_CREATED**
- 보고서 폴더: `reports/{JIRA-KEY}/`

### 리포트 모드
- `JIRA_ENABLED=false` 또는 `--no-jira` 옵션
- Jira 티켓 생성하지 않음
- Jira 형식의 리포트 문서만 생성 (`03_jira_report.md`)
- 상태: ANALYZING → REVIEW_ANALYSIS → **REPORT_CREATED**
- 보고서 폴더: `reports/{SonarQube키}/`

## 실행 흐름

### 사전 검증 (필수)

보고서 디렉토리 생성 전, 반드시 `validate_issue_key.py`를 실행하여 ROW의 SonarQube키와 사용할 issue_key가 일치하는지 검증한다.
불일치 시 `$ARGUMENTS[1]`의 SonarQube키 필드를 재확인한다.

```bash
python .claude/skills/sonar-common/scripts/validate_issue_key.py \
  -r ROW -k "$ISSUE_KEY" -s $SPREADSHEET_ID
```

- 검증 통과 (exit 0) → 실행 흐름 계속
- 검증 실패 (exit 1) → `$ARGUMENTS[1]`에서 SonarQube키를 다시 읽고, 스프레드시트 ROW를 재확인하여 올바른 키를 사용

### Jira 모드
1. 상태 → ANALYZING 업데이트
2. 해당 파일:라인 읽기
3. 원인 분석 및 영향범위 파악
4. 분석 보고서 작성 (`reports/{issue_key}/01_analysis_report.md`)
5. 상태 → REVIEW_ANALYSIS
6. sonar-review 호출하여 검증
7. 통과 시: **Jira 생성** → `03_jira_created.md` 작성 → JIRA_CREATED
8. 실패 시: 재시도 (최대 3회) 또는 BLOCKED

### 리포트 모드
1. 상태 → ANALYZING 업데이트
2. 해당 파일:라인 읽기
3. 원인 분석 및 영향범위 파악
4. 분석 보고서 작성 (`reports/{sonarqube_key}/01_analysis_report.md`)
5. 상태 → REVIEW_ANALYSIS
6. sonar-review 호출하여 검증
7. 통과 시: **Jira 리포트 생성** → `03_jira_report.md` 작성 → REPORT_CREATED
8. 실패 시: 재시도 (최대 3회) 또는 BLOCKED

## 스크립트

### sheets_claim.py

```bash
python scripts/sheets_claim.py -n 5 -a "$ASSIGNEE_NAME" -s $SPREADSHEET_ID
```

### sheets_get_issue.py

```bash
python scripts/sheets_get_issue.py -a "$ASSIGNEE_NAME" -s $SPREADSHEET_ID --json
```

### sheets_update.py

```bash
# 상태 업데이트 — 실행 추적은 상태값에 따라 자동 (--issue-key 생략 가능)
python scripts/sheets_update.py -r ROW -s $SPREADSHEET_ID --status ANALYZING
python scripts/sheets_update.py -r ROW -s $SPREADSHEET_ID --status REPORT_CREATED
python scripts/sheets_update.py -r ROW -s $SPREADSHEET_ID --status BLOCKED --error "message"
```

> **자동 추적**: `--status ANALYZING` → `start_execution(analyze)` 자동, `--status REPORT_CREATED`/`JIRA_CREATED` → `complete_execution(analyze, success)` 자동. `--start-exec`/`--complete-exec` 플래그 불필요.

### create_jira_issue.sh (Jira 모드만)

```bash
./scripts/create_jira_issue.sh -p PROJECT -s "Summary" -d "Description"
```

## 템플릿

- [templates/analysis_report.md](templates/analysis_report.md) - 분석 보고서
- [templates/jira_report.md](templates/jira_report.md) - Jira 형식 리포트 (리포트 모드)
- [templates/jira_created.md](templates/jira_created.md) - Jira 생성 결과 (Jira 모드)

> **필수**: 리포트 작성 시 반드시 위 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.

## 재시도 규칙

- Review Agent가 FAIL 판정 시 재시도
- 최대 3회 재시도 (총 4회 시도)
- 4회 실패 시 BLOCKED 상태로 전환
