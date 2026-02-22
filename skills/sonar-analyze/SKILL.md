---
name: sonar-analyze
description: NEW 상태 이슈를 분석하고 리포트를 생성. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# SonarQube Issue Analysis

NEW 상태의 이슈를 분석하고, Review Agent 검증 후 분석 완료 상태로 전환합니다.

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
| `$ARGUMENTS[0]` | string | 필수 | sonarqube_key — SonarQube 이슈 고유 키 (그룹: `group-<name>`) |
| `$ARGUMENTS[1]` | JSON string | 필수 | issue_data — 이슈 정보 (아래 필수 필드 참조) |
| `$ARGUMENTS[2]` | JSON array | 선택 | group_issues — 그룹 처리 시 그룹 내 이슈 목록 |

**issue_data 필수 필드:**

| 필드 | 용도 |
|------|------|
| `파일` | 소스 코드 파일 경로 (분석 대상) |
| `라인` | 소스 코드 라인 번호 (분석 대상) |
| `메시지` | SonarQube 이슈 메시지 (문제 요약에 사용) |
| `규칙` | SonarQube 규칙 ID (예: `java:S1172`) |
| `SonarQube키` | 이슈 고유 식별자 (폴더명) |
| `심각도` | 이슈 심각도 |
| `타입` | 이슈 타입 — BUG, VULNERABILITY, CODE_SMELL |
| `담당자` | 담당자 이름 (보고서 메타데이터) |

### Output

```json
{
  "status": "success | failed | blocked",
  "issue_key": "AYxx...",
  "report_path": "$SONAR_PROJECT_DIR/reports/AYxx.../01_analysis_report.md",
  "attempt": 1
}
```

그룹 처리 시:
```json
{
  "status": "success | failed | blocked",
  "issue_key": "group-<name>",
  "report_path": "$SONAR_PROJECT_DIR/reports/group-<name>/01_analysis_report.md",
  "attempt": 1
}
```

### 생성 파일

| 파일 | 소비자 | 필수 섹션 |
|------|--------|----------|
| `$SONAR_PROJECT_DIR/reports/{sonarqube_key}/01_analysis_report.md` | sonar-review (analysis), sonar-develop | 문제 요약, 원인 분석, 영향범위, 해결 방안, 검증 계획 |
| `$SONAR_PROJECT_DIR/reports/group-<name>/01_analysis_report.md` (그룹) | sonar-review (analysis), sonar-develop | 대상 이슈 목록, 문제 요약, 원인 분석, 영향범위, 해결 방안, 검증 계획 |

### SQLite DB 변경

| 변경 항목 | 값 | 시점 |
|----------|-----|------|
| status | `ANALYZING` | 분석 시작 시 |
| status | `REVIEW_ANALYSIS` | 보고서 작성 완료 시 |
| status | `ANALYZED` | 리뷰 PASS 후 |
| status | `BLOCKED` | 4회 시도 실패 시 |
| analyze_attempts | +1 | 각 시도마다 |

> **상태 업데이트**: `local_db.update_status(sonarqube_key, new_status)` 호출로 상태를 변경합니다.

### sonar-review 호출 규약

```
# 개별 이슈
Skill("sonar-review", args: "analysis {report_path} {issue_data_json}")

# 그룹 이슈 (report_path가 group-<name> 폴더를 가리킴)
Skill("sonar-review", args: "analysis {report_path} {issue_data_json}")
```

반환값: `{verdict: "PASS"|"FAIL", reason, suggestions[]}`
- PASS → 상태를 ANALYZED로 전환 (그룹: 모든 이슈 개별 ANALYZED)
- FAIL → suggestions 반영 후 재시도 (최대 3회 재시도, 총 4회)

## 입력 (요약)

- `$ARGUMENTS[0]`: sonarqube_key (SonarQube 이슈 고유 키, 그룹: `group-<name>`)
- `$ARGUMENTS[1]`: issue_data (JSON 형식의 이슈 정보)
- `$ARGUMENTS[2]`: group_issues (선택, 그룹 내 이슈 JSON 배열 — sonar-develop과 동일한 패턴)

## 상태 흐름

```
NEW → ANALYZING → REVIEW_ANALYSIS → ANALYZED
                                       ↗ (on review PASS)
Retry on FAIL (max 4 attempts total) → BLOCKED
```

## 그룹 이슈 처리

`$ARGUMENTS[2]` (group_issues)가 제공되면 그룹 처리 요청으로 간주합니다.

### 그룹 처리 규칙

- **보고서 폴더**: `$SONAR_PROJECT_DIR/reports/group-<group_name>/` (개별 이슈: `$SONAR_PROJECT_DIR/reports/{sonarqube_key}/`)
- **통합 분석**: 같은 rule의 이슈이므로 단일 `01_analysis_report.md` 생성
- **상태 업데이트**: 그룹 내 모든 이슈를 개별적으로 업데이트 (ANALYZING → REVIEW_ANALYSIS → ANALYZED)

### 그룹 처리 흐름

1. group_issues JSON 파싱 → 이슈 목록 추출
2. 그룹명 추출 (`$ARGUMENTS[0]`에서 `group-<name>`)
3. 모든 이슈의 상태를 ANALYZING으로 업데이트
4. 모든 이슈의 소스 파일:라인 읽기 (각 이슈별 코드 확인)
5. 통합 `01_analysis_report.md` 작성 (`$SONAR_PROJECT_DIR/reports/group-<group_name>/01_analysis_report.md`, `group_analysis_report.md` 템플릿 사용)
6. 모든 이슈의 상태를 REVIEW_ANALYSIS로 업데이트
7. sonar-review 호출 (report_path = 그룹 폴더의 01_analysis_report.md)
8. PASS: 모든 이슈 → ANALYZED + report_path를 `reports/group-<group_name>/01_analysis_report.md`로 설정
9. FAIL: suggestions 반영 후 재시도 (최대 4회)

### 사전 검증 (그룹)

그룹 처리 시 각 이슈별로 `validate_issue_key.py`를 실행하여 SQLite DB의 SonarQube키 검증:

```bash
# 그룹 내 각 이슈에 대해 실행
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/validate_issue_key.py \
  -k "$EACH_ISSUE_SONARQUBE_KEY"
```

## 실행 흐름

### 사전 검증 (필수)

보고서 디렉토리 생성 전, 반드시 `validate_issue_key.py`를 실행하여 SQLite DB의 SonarQube키와 사용할 issue_key가 일치하는지 검증한다.

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/validate_issue_key.py \
  -k "$SONARQUBE_KEY"
```

- 검증 통과 (exit 0) → 실행 흐름 계속
- 검증 실패 (exit 1) → `$ARGUMENTS[1]`에서 SonarQube키를 다시 읽고, DB를 재확인하여 올바른 키를 사용

### 분석 단계

1. 상태 → ANALYZING 업데이트 (`local_db.update_status(sonarqube_key, "ANALYZING")`)
2. 해당 파일:라인 읽기
3. 원인 분석 및 영향범위 파악
4. 분석 보고서 작성 (`$SONAR_PROJECT_DIR/reports/{sonarqube_key}/01_analysis_report.md`)
5. 상태 → REVIEW_ANALYSIS (`local_db.update_status(sonarqube_key, "REVIEW_ANALYSIS")`)
6. sonar-review 호출하여 검증
7. 통과 시: 상태 → ANALYZED (`local_db.update_status(sonarqube_key, "ANALYZED")`)
8. 실패 시: 재시도 (최대 3회) 또는 BLOCKED

## 스크립트

### local_db.py (상태 업데이트)

```bash
# 상태 업데이트
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/local_db.py get "$SONARQUBE_KEY"
```

```python
# Python API로 상태 업데이트
from local_db import update_status, add_execution

update_status(sonarqube_key, "ANALYZING")
update_status(sonarqube_key, "ANALYZED")
update_status(sonarqube_key, "BLOCKED")

# 실행 이력 기록
add_execution(sonarqube_key, "analyze", "success")
add_execution(sonarqube_key, "analyze", "failure", details="error message")
```

## 템플릿

- [templates/analysis_report.md](templates/analysis_report.md) - 분석 보고서 (개별 이슈)
- [templates/group_analysis_report.md](templates/group_analysis_report.md) - 그룹 통합 분석 보고서 (그룹 이슈)

> **필수**: 리포트 작성 시 반드시 위 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.
> 그룹 이슈 처리 시 `group_analysis_report.md` 템플릿을 사용합니다.

## 재시도 규칙

- Review Agent가 FAIL 판정 시 재시도
- 최대 3회 재시도 (총 4회 시도)
- 4회 실패 시 BLOCKED 상태로 전환
