---
name: sonar
description: SonarQube 이슈 처리 워크플로우. 이슈 수집, 분석, 개발, 리뷰를 자동화합니다.
argument-hint: "--action=<command> --id=<project_id> [--key=<key>] [--limit=<N>]"
env:
  MAX_CONCURRENT_AGENTS: "5"  # 동시 실행 서브에이전트 수 (2-10, 기본값 5)
allowed-tools: Bash, Read, Write, Skill
---

# SonarQube Workflow — 오케스트레이터

**가장 먼저 아래 디스패치 테이블을 확인하고 Skill을 호출하세요.**

## 디스패치 (첫 번째로 수행)

`$ARGUMENTS`에서 named parameter를 파싱합니다.

**파싱 규칙:**
- `--action=<값>`: 실행할 명령어 (필수)
- `--id=<값>`: project_id (필수)
- `--key=<값>`: sonarqube_key 또는 group-name (선택)
- `--limit=<값>`: 최대 처리 건수 (선택, run 전용)
- 필수 파라미터가 없으면 에러 출력 후 종료

| `--action` 값 | Skill 호출 (정확히 이대로) |
|----------------|--------------------------|
| `group` | SONAR_PROJECT_DIR 설정 후 `Skill("sonar-group")` |
| `run` | SONAR_PROJECT_DIR 설정 후 스킬 호출 |
| `run` + `--key` | SONAR_PROJECT_DIR 설정 후 스킬 호출 (특정 이슈/그룹) |
| `run` + `--limit` | SONAR_PROJECT_DIR 설정 후 스킬 호출 (N개 제한) |
| `approve` + `--key` | SONAR_PROJECT_DIR 설정 후 `Skill("sonar-approve")` |
| `reject` + `--key` | SONAR_PROJECT_DIR 설정 후 `Skill("sonar-reject")` |
| `status` | SONAR_PROJECT_DIR 설정 후 `Skill("sonar-dashboard")` |

모든 명령어는 `--id`의 값으로 프로젝트 매칭 후 `SONAR_PROJECT_DIR`을 설정합니다:
1. `projects/*/.env` 에서 `WEB_PROJECT_ID`(숫자) 또는 `PROJECT_NAME`(문자열) 매칭
2. 매칭 실패 시 → "프로젝트를 찾을 수 없습니다. `/sonar-setup --id=<project_id>`를 먼저 실행하세요"

---

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 중요 정책

### Worktree 보존
- **작업 완료 후에도 Worktree를 삭제하지 않음**
- 여러 이슈를 병렬 처리하면 `worktrees/` 아래에 각 이슈별 폴더가 유지됨
- 사용자가 코드 리뷰 후 수동으로 정리

## 명령어

| 파라미터 | 설명 | 예시 |
|----------|------|------|
| `--action=group --id=<id>` | 단순/반복 이슈 자동 그룹화 | `/sonar --action=group --id=2` |
| `--action=run --id=<id>` | 모든 NEW 이슈 병렬 처리 | `/sonar --action=run --id=2` |
| `--action=run --id=<id> --limit=<N>` | 최대 N개 NEW 이슈 처리 | `/sonar --action=run --id=2 --limit=5` |
| `--action=run --id=<id> --key=<key>` | 특정 이슈만 처리 | `/sonar --action=run --id=2 --key=AZO...` |
| `--action=run --id=<id> --key=group-<name>` | 그룹 이슈 일괄 처리 | `/sonar --action=run --id=2 --key=group-fstring-fix` |
| `--action=approve --id=<id> --key=<key>` | 승인 -> Jira -> 브랜치 -> 커밋 -> 머지 | `/sonar --action=approve --id=2 --key=AZO...` |
| `--action=reject --id=<id> --key=<key>` | 작업 반려 -> BLOCKED | `/sonar --action=reject --id=2 --key=AZO...` |
| `--action=status --id=<id>` | 현황 조회 | `/sonar --action=status --id=2` |

## 실행 규칙

### `--action=run` (병렬 처리)

> **`run`은 항상 병렬 모드로 실행됩니다.** 단건 처리 모드는 없습니다.
> 이슈가 1개여도 서브에이전트 1개로 병렬 처리 방식으로 실행됩니다.

1. SQLite DB에서 status=NEW인 이슈 전체 조회
2. **개별 이슈는 1:1 서브에이전트로 실행, 그룹 이슈는 그룹 단위로 서브에이전트 실행**
   - 그룹에 속하지 않은 이슈: 각각 별도 서브에이전트 실행
   - 그룹 이슈(`group_id` 존재): 같은 그룹의 이슈를 단일 서브에이전트에서 처리
3. **최대 동시 실행 에이전트 수: `$MAX_CONCURRENT_AGENTS`개** (`.env` 설정, 2-10, 기본값 5)
   - 한 번에 최대 `$MAX_CONCURRENT_AGENTS`개의 서브에이전트만 병렬 실행
   - 예: `MAX_CONCURRENT_AGENTS=3`이고 12개 이슈 -> 먼저 3개 실행, 1개 완료되면 4번째 실행, ...
   - 모든 이슈가 완료될 때까지 반복
   - 값이 없거나 2-10 범위 밖이면 기본값 5 사용
4. 이슈별로 서브에이전트 실행 (`context: fork`)
   - **1개 이슈 = 1개 서브에이전트** (개별 이슈)
   - **1개 그룹 = 1개 서브에이전트** (그룹 이슈)
5. **각 서브에이전트가 DONE/BLOCKED까지 전체 워크플로우 수행**:
   - 서브에이전트는 이슈 상태가 DONE 또는 BLOCKED가 될 때까지 루프
   - 예: NEW -> 분석 -> ANALYZED -> 개발 -> DONE
   - 각 단계 완료 후 SQLite DB에서 상태를 확인하고 다음 단계로 자동 진행
   - **한 단계(예: 분석)만 실행하고 종료하지 않음**
   - **그룹 서브에이전트**: sonar-analyze를 그룹 단위로 1회만 호출하여 통합 분석 보고서 1건 생성 → sonar-develop도 그룹 단위로 1회 호출
6. **각 이슈별 Worktree 유지**
7. 결과 집계 및 보고

### `--action=run --limit=<N>` (N개 제한 모드)

- `--limit`이 지정되면 N개 제한 모드
- SQLite DB에서 status=NEW인 이슈를 최대 N개만 조회하여 처리
- 나머지 규칙은 `--action=run`과 동일

### `--action=run --key=<sonarqube-key>` (단일 이슈 지정)

- 지정된 sonarqube_key의 이슈만 처리
- 나머지 규칙은 `--action=run`과 동일

### `--action=run --key=group-<name>` (그룹 이슈)

- 지정된 그룹의 모든 이슈를 단일 서브에이전트에서 처리
- 그룹 보고서: `reports/group-<name>/` (01~07 모든 보고서가 이 폴더에 생성)
- 그룹 worktree: `worktrees/group-<name>/`
- sonar-analyze에 `group_issues` JSON을 전달하여 통합 분석
- sonar-develop에 `group_issues` JSON을 전달하여 그룹 수정
- 그룹 내 각 이슈의 상태를 개별적으로 업데이트

## 상태 전이 규칙

```
NEW -> ANALYZING <-> REVIEW_ANALYSIS -> ANALYZED
          | (4회 실패)
       BLOCKED

ANALYZED -> DEVELOPING <-> REVIEW_FIX -> TESTING -> DONE
                | (4회 실패)
             BLOCKED

DONE -> APPROVED (승인: Jira 생성 + 브랜치 + 커밋 + 머지)
DONE -> BLOCKED (반려)
```

## 내부 스킬 (자동 호출)

- `sonar-analyze`: 이슈 분석 (리뷰 포함)
- `sonar-develop`: 코드 수정 (그룹 워크트리 지원)
- `sonar-review`: 분석/수정 결과 검증
- `sonar-group`: 단순 이슈 자동 그룹화
- `sonar-approve`: 승인 -> Jira -> 브랜치 -> 커밋 -> 머지
- `sonar-reject`: 반려 -> BLOCKED + 워크트리/리포트 제거

**중요**: 내부 스킬은 `context: fork`로 서브에이전트에서 실행됩니다.

## Data Contract

### issue_data JSON 공통 스키마

SQLite DB에서 조회한 이슈 데이터는 아래 형식의 JSON으로 스킬 간 전달됩니다.
정규 컬럼 정의는 `sonar-common/SKILL.md`의 로컬 DB 스키마를 참조합니다.

```json
{
  "sonarqube_key": "AZO...",
  "status": "NEW",
  "group_id": null,
  "severity": "MAJOR",
  "type": "BUG",
  "rule": "java:S1172",
  "file_path": "src/main/java/com/example/Main.java",
  "line": 42,
  "message": "Remove this unused method parameter \"name\".",
  "jira_key": "",
  "report_path": "",
  "worktree_path": "",
  "analyze_attempts": 0,
  "develop_attempts": 0,
  "synced_at": "",
  "created_at": "2025-01-15T10:30:00",
  "updated_at": "2025-02-05T14:00:00"
}
```

**필수 필드** (모든 스킬에서 참조):
- `sonarqube_key`: 이슈 고유 식별자
- `file_path`: 소스 코드 파일 경로 (분석/수정 대상)
- `line`: 소스 코드 라인 번호 (분석/수정 대상)
- `message`: SonarQube 이슈 메시지
- `rule`: SonarQube 규칙 ID

### 스킬 간 데이터 흐름

```
sonar (orchestrator)
  |
  +- sonar-group()  [SONAR_PROJECT_DIR 설정 후 호출]
  |   +-> SQLite에서 NEW 이슈 조회 -> 단순 패턴 그룹화 -> groups 테이블 생성 + issues.group_id 할당
  |
  +- sonar-analyze(sonarqube_key, issue_data, [group_issues])
  |   +-> 생성: 01_analysis_report.md -> sonar-review가 읽음
  |   +-> 그룹: reports/group-<name>/01_analysis_report.md (통합 분석)
  |   +-> 반환: {status, issue_key, report_path, attempt}
  |
  +- sonar-review(review_type, report_path, issue_data)
  |   +-> 생성: 02_analysis_review.md (review_type="analysis")
  |   +-> 생성: 05_fix_review.md (review_type="fix")
  |   +-> 반환: {verdict, reason, suggestions[]}
  |
  +- sonar-develop(sonarqube_key, issue_data, [group_issues])
  |   +-> 읽기 의존: 01_analysis_report.md
  |   +-> 생성: 04_fix_report.md -> sonar-review가 읽음
  |   +-> 생성: 06_test_report.md
  |   +-> 생성: 07_final_deliverable.md (커밋 메시지/PR 설명)
  |   +-> 반환: {status, issue_key, worktree_path, branch, report_path, commit_ready}
  |
  +- sonar-approve(sonarqube_key_or_group)
  |   +-> 읽기 의존: 07_final_deliverable.md
  |   +-> Jira 생성 -> 브랜치 -> 커밋 -> 푸시 -> 머지
  |   +-> 반환: {status, sonarqube_key, jira_key, branch, message}
  |
  +- sonar-reject(sonarqube_key_or_group)
      +-> 워크트리 제거 + 리포트 제거
      +-> 상태: DONE -> BLOCKED
      +-> 반환: {status, sonarqube_key, message}
```

### 스킬 호출 규약

> **사전조건**: 모든 스킬 호출 전에 `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`를 **절대 경로**로 설정해야 합니다.
> 오케스트레이터가 `project_id`로 프로젝트 디렉토리를 찾아 설정합니다.

| 스킬 | 호출 방법 | $ARGUMENTS | SONAR_PROJECT_DIR |
|------|----------|------------|-------------------|
| sonar-group | `Skill("sonar-group")` | 없음 | 사전 설정 필수 |
| sonar-analyze | `Skill("sonar-analyze", args: "SONARQUBE_KEY JSON [GROUP_JSON]")` | `[0]`: sonarqube_key, `[1]`: issue_data, `[2]`: group_issues (선택) | 사전 설정 필수 |
| sonar-review | `Skill("sonar-review", args: "TYPE PATH JSON")` | `[0]`: review_type, `[1]`: report_path, `[2]`: issue_data (JSON string) | 사전 설정 필수 |
| sonar-develop | `Skill("sonar-develop", args: "SONARQUBE_KEY JSON [GROUP_JSON]")` | `[0]`: sonarqube_key, `[1]`: issue_data, `[2]`: group_issues (선택) | 사전 설정 필수 |
| sonar-approve | `Skill("sonar-approve", args: "SONARQUBE_KEY_OR_GROUP")` | `[0]`: sonarqube_key 또는 group-name | 사전 설정 필수 |
| sonar-reject | `Skill("sonar-reject", args: "SONARQUBE_KEY_OR_GROUP")` | `[0]`: sonarqube_key 또는 group-name | 사전 설정 필수 |

## 환경 설정

### 루트 .env (공통)

```bash
# 웹서비스 연결 (선택)
WEB_SERVICE_URL=

# 개인 인증 정보 (모든 프로젝트 공통)
JIRA_ID=xxx
JIRA_PASSWORD=xxx

# 워크플로우
ASSIGNEE_NAME=홍길동
MAX_CONCURRENT_AGENTS=5  # 동시 실행 서브에이전트 수 (2-10, 기본값 5)
```

### 프로젝트별 .env (projects/\<name\>/.env)

```bash
# 프로젝트 식별
WEB_PROJECT_ID=1
PROJECT_NAME=FULLAUTO

# SonarQube
SONARQUBE_URL=https://sonarqube.example.com
SONARQUBE_TOKEN=xxx
SONARQUBE_PROJECT_KEY=com.example:fullauto

# Jira
JIRA_URL=https://jira.example.com
JIRA_PROJECT_KEY=ODIN

# Repository
REPO_URL=git@github.com:org/my-project.git
REPO_BRANCH=main
REPO_PATH=repo/FULLAUTO
```

## 작업 완료 후 구조

```
projects/<name>/
+-- .env                         # 프로젝트별 환경 설정
+-- sonar.db                     # SQLite 로컬 DB (이슈/실행 관리)
+-- data/                        # intake 결과 (SonarQube JSON)
+-- repo/<name>/                 # 소스코드 리포지토리
+-- worktrees/                   # 작업 완료 후에도 유지됨
|   +-- AZO.../                  # 개별 이슈 worktree
|   +-- AZO.../                  # 개별 이슈 worktree
|   +-- group-fstring-fix/       # 그룹 이슈 worktree
+-- reports/
|   +-- AZO.../
|   |   +-- 01_analysis_report.md
|   |   +-- 02_analysis_review.md
|   |   +-- 04_fix_report.md
|   |   +-- 05_fix_review.md
|   |   +-- 06_test_report.md
|   |   +-- 07_final_deliverable.md
|   +-- group-fstring-fix/
|       +-- 01_analysis_report.md
|       +-- 02_analysis_review.md
|       +-- 04_fix_report.md
|       +-- 05_fix_review.md
|       +-- 06_test_report.md
|       +-- 07_final_deliverable.md
```

## 보고서 위치

```
$SONAR_PROJECT_DIR/reports/
+-- {sonarqube_key}/
|   +-- 01_analysis_report.md
|   +-- 02_analysis_review.md
|   +-- 04_fix_report.md
|   +-- 05_fix_review.md
|   +-- 06_test_report.md
|   +-- 07_final_deliverable.md  # 커밋 메시지/PR 설명 포함
+-- group-<name>/
    +-- 01_analysis_report.md
    +-- 02_analysis_review.md
    +-- 04_fix_report.md
    +-- 05_fix_review.md
    +-- 06_test_report.md
    +-- 07_final_deliverable.md
```
