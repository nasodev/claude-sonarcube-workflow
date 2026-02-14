---
name: sonar
description: SonarQube 이슈 처리 워크플로우. 이슈 수집, 분석, 개발, 리뷰를 자동화합니다.
argument-hint: "[intake|claim|run|status|approve|reject] [args]"
env:
  MAX_CONCURRENT_AGENTS: "5"  # 동시 실행 서브에이전트 수 (2-10, 기본값 5)
allowed-tools: Bash, Read, Write, Skill
---

# SonarQube Workflow

SonarQube 이슈 처리를 위한 통합 워크플로우입니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 중요 정책

### 이슈 그룹화 금지 (필수)
- **각 스프레드시트 행은 반드시 개별 서브에이전트로 처리**
- 동일 파일에 여러 이슈가 있어도 각각 별도 서브에이전트 실행
- 동일 규칙(예: S3457)의 이슈여도 각각 별도 서브에이전트 실행
- "효율성을 위한 그룹화" 절대 금지
- 10개 이슈 → 10개 서브에이전트 (1:1 매핑)

### Worktree 보존
- **작업 완료 후에도 Worktree를 삭제하지 않음**
- 여러 이슈를 병렬 처리하면 `worktrees/` 아래에 각 이슈별 폴더가 유지됨
- 사용자가 코드 리뷰 후 수동으로 정리

### 자동 커밋/PR 금지
- **커밋은 자동으로 생성하지 않음**
- **PR은 자동으로 생성하지 않음**
- 커밋 메시지와 PR 설명은 `07_final_deliverable.md`에 작성
- 사용자가 리포트 검토 후 수동으로 커밋/PR 진행

### 디버그 모드
- `DEBUG_MODE=true` 설정 시 활성화
- 모든 대화 기록(메인 에이전트, 서브에이전트)을 `history/{issue_key}/` 폴더에 저장
- `{issue_key}`는 Jira 번호 또는 SonarQube 이슈 키
- Hook을 통해 Stop, SubagentStop, SessionEnd 이벤트 시 자동 저장

## 명령어

| 명령 | 설명 | 예시 |
|------|------|------|
| `intake [project_key]` | SonarQube에서 이슈 수집 | `/sonar intake` |
| `claim N` | N개 이슈 할당 | `/sonar claim 5` |
| `run` | 모든 담당 이슈 병렬 처리 | `/sonar run` |
| `run --no-jira` | Jira 생성 없이 리포트만 | `/sonar run --no-jira` |
| `run ISSUE-KEY` | 특정 이슈만 처리 | `/sonar run ODIN-123` |
| `status` | 현황 조회 | `/sonar status` |
| `approve ISSUE-KEY` | 작업 승인 | `/sonar approve ODIN-123` |
| `reject ISSUE-KEY` | 작업 반려 | `/sonar reject ODIN-123` |

## Jira 모드 vs 리포트 모드

### Jira 모드 (기본)

- `JIRA_ENABLED=true` (기본값)
- 분석 완료 후 Jira 티켓 생성
- 보고서 폴더: `reports/{JIRA-KEY}/`

### 리포트 모드

- `JIRA_ENABLED=false` 또는 `--no-jira` 옵션
- Jira 티켓 생성하지 않음
- Jira 형식의 리포트 문서 생성 (`03_jira_report.md`)
- 보고서 폴더: `reports/{SonarQube키}/`

## 실행 규칙

### `/sonar run` (병렬 처리)

> **⚠️ `run`은 항상 병렬 모드로 실행됩니다.** 단건 처리 모드는 없습니다.
> 이슈가 1개여도 서브에이전트 1개로 병렬 처리 방식으로 실행됩니다.

1. 내 담당 이슈 전체 조회
2. **⚠️ 중요: 그룹화 금지**
   - 각 스프레드시트 행(이슈)은 반드시 개별 서브에이전트로 실행
   - 동일 파일, 동일 규칙 등 유사성과 관계없이 **절대 그룹화하지 않음**
3. **⚠️ 최대 동시 실행 에이전트 수: `$MAX_CONCURRENT_AGENTS`개** (`.env` 설정, 1-10, 기본값 5)
   - 한 번에 최대 `$MAX_CONCURRENT_AGENTS`개의 서브에이전트만 병렬 실행
   - 예: `MAX_CONCURRENT_AGENTS=3`이고 12개 이슈 → 먼저 3개 실행, 1개 완료되면 4번째 실행, ...
   - 모든 이슈가 완료될 때까지 반복
   - 값이 없거나 2-10 범위 밖이면 기본값 5 사용
4. 이슈별로 서브에이전트 실행 (`context: fork`)
   - **1개 이슈 = 1개 서브에이전트** (필수)
5. **⚠️ 각 서브에이전트가 DONE/BLOCKED까지 전체 워크플로우 수행**:
   - 서브에이전트는 이슈 상태가 DONE 또는 BLOCKED가 될 때까지 루프
   - 예: CLAIMED → 분석 → JIRA_CREATED/REPORT_CREATED → 개발 → DONE
   - 각 단계 완료 후 스프레드시트에서 상태를 확인하고 다음 단계로 자동 진행
   - **한 단계(예: 분석)만 실행하고 종료하지 않음**
6. **각 이슈별 Worktree 유지**
7. **커밋/PR 생성 안함** (리포트만 작성)
8. 결과 집계 및 보고

## 상태 전이 규칙

### Jira 모드
```
대기 → CLAIMED → ANALYZING ⟷ REVIEW_ANALYSIS → JIRA_CREATED
                    ↓ (4회 실패)
                 BLOCKED

JIRA_CREATED → DEVELOPING ⟷ REVIEW_FIX → TESTING → DONE
                   ↓ (4회 실패)
                BLOCKED

DONE → APPROVED (승인)
DONE → BLOCKED (반려)
```

### 리포트 모드
```
대기 → CLAIMED → ANALYZING ⟷ REVIEW_ANALYSIS → REPORT_CREATED
                    ↓ (4회 실패)
                 BLOCKED

REPORT_CREATED → DEVELOPING ⟷ REVIEW_FIX → TESTING → DONE
                     ↓ (4회 실패)
                  BLOCKED

DONE → APPROVED (승인)
DONE → BLOCKED (반려)
```

## 내부 스킬 (자동 호출)

- `sonar-intake`: 이슈 수집 및 스프레드시트 업로드
- `sonar-analyze`: 이슈 분석 및 Jira 생성 (또는 리포트 생성)
- `sonar-develop`: 코드 수정 및 커밋 메시지 준비 **(실제 커밋 안함)**
- `sonar-review`: 분석/수정 결과 검증

**중요**: 내부 스킬은 `context: fork`로 서브에이전트에서 실행됩니다.

## Data Contract

### issue_data JSON 공통 스키마

스프레드시트에서 조회한 이슈 데이터는 아래 형식의 JSON으로 스킬 간 전달됩니다.
정규 컬럼 정의는 `sonar-common/SKILL.md`의 스프레드시트 컬럼 스키마를 참조합니다.

```json
{
  "_row": 2,
  "상태": "CLAIMED",
  "담당자": "홍길동",
  "Jira키": "",
  "심각도": "MAJOR",
  "품질": "RELIABILITY",
  "타입": "BUG",
  "파일": "src/main/java/com/example/Main.java",
  "라인": "42",
  "메시지": "Remove this unused method parameter \"name\".",
  "규칙": "java:S1172",
  "CleanCode": "CLEAR",
  "SonarQube키": "AYxx...",
  "생성일": "2025-01-15T10:30:00+0900",
  "할당시각": "2025-02-05T14:00:00+0900",
  "분석시도": "0",
  "수정시도": "0",
  "보고서": "",
  "에러": "",
  "승인자": "",
  "승인시각": ""
}
```

**필수 필드** (모든 스킬에서 참조):
- `_row`: 스프레드시트 행 번호 (상태 업데이트에 필수)
- `파일`, `라인`: 소스 코드 위치 (분석/수정 대상)
- `메시지`, `규칙`: SonarQube 이슈 내용
- `SonarQube키`: 이슈 고유 식별자

### 스킬 간 데이터 흐름

```
sonar (orchestrator)
  │
  ├─ sonar-intake(project_key)
  │   └→ 스프레드시트에 행 추가 (issue_data 생성 원본)
  │
  ├─ sonar-analyze(row, issue_data, [--no-jira])
  │   ├→ 생성: 01_analysis_report.md ──→ sonar-review가 읽음
  │   ├→ 생성: 03_jira_created.md ────→ sonar-develop가 읽음 (Jira 모드)
  │   ├→ 생성: 03_jira_report.md ─────→ sonar-develop가 읽음 (리포트 모드)
  │   └→ 반환: {status, jira_key/issue_key, report_path, attempt}
  │
  ├─ sonar-review(review_type, report_path, issue_data)
  │   ├→ 생성: 02_analysis_review.md (review_type="analysis")
  │   ├→ 생성: 05_fix_review.md (review_type="fix")
  │   └→ 반환: {verdict, reason, suggestions[]}
  │
  └─ sonar-develop(row, issue_data)
      ├→ 읽기 의존: 01_analysis_report.md, 03_jira_created.md/03_jira_report.md
      ├→ 생성: 04_fix_report.md ──────→ sonar-review가 읽음
      ├→ 생성: 06_test_report.md
      ├→ 생성: 07_final_deliverable.md (커밋 메시지/PR 설명)
      ├→ 생성: 08_cto_approval.md (CTO 승인 요청 보고서)
      └→ 반환: {status, jira_key/issue_key, worktree_path, branch, report_path, commit_ready}
```

### 스킬 호출 규약

| 스킬 | 호출 방법 | $ARGUMENTS |
|------|----------|------------|
| sonar-intake | `Skill("sonar-intake", args: "project_key")` | `[0]`: project_key (string) |
| sonar-analyze | `Skill("sonar-analyze", args: "ROW JSON [--no-jira]")` | `[0]`: row (number), `[1]`: issue_data (JSON string), `[2]`: --no-jira (optional) |
| sonar-review | `Skill("sonar-review", args: "TYPE PATH JSON")` | `[0]`: review_type ("analysis"\|"fix"), `[1]`: report_path, `[2]`: issue_data (JSON string) |
| sonar-develop | `Skill("sonar-develop", args: "ROW JSON")` | `[0]`: row (number), `[1]`: issue_data (JSON string) |

## 환경 설정

```bash
# .env 파일
SONARCUBE_TOKEN=xxx

# Jira (JIRA_ENABLED=false면 아래 설정 불필요)
JIRA_URL=https://jira.example.com
JIRA_ID=xxx
JIRA_PASSWORD=xxx
PROJECT_KEY=ODIN
JIRA_ENABLED=true  # false면 Jira 대신 리포트 문서 생성

# Google Sheets
SPREADSHEET_ID=xxx

# Workflow
ASSIGNEE_NAME=홍길동
MAX_CONCURRENT_AGENTS=5  # 동시 실행 서브에이전트 수 (2-10, 기본값 5)

# Repository
REPO_PATH=repo/my-project
REPO_URL=git@github.com:org/my-project.git
REPO_BRANCH=main

# Debug
DEBUG_MODE=false  # true면 작업 기록을 history/{issue_key}/ 폴더에 저장
```

## 작업 완료 후 구조

```
프로젝트/
├── worktrees/                    # 작업 완료 후에도 유지됨
│   ├── ODIN-123/                # 이슈 1 worktree
│   ├── ODIN-124/                # 이슈 2 worktree
│   └── AYxx.../                 # 이슈 3 worktree (리포트 모드)
├── reports/
│   ├── ODIN-123/
│   │   ├── 01_analysis_report.md
│   │   ├── ...
│   │   └── 07_final_deliverable.md  # 커밋 메시지/PR 설명 포함
│   └── ODIN-124/
│       └── ...
├── history/                     # DEBUG_MODE=true 일 때만 생성
│   ├── ODIN-123/               # 이슈별 대화 기록
│   │   ├── 20250205_123456_main_Stop.jsonl
│   │   ├── 20250205_123500_subagent_general-purpose.jsonl
│   │   └── 20250205_123500_hook_metadata.json
│   └── ODIN-124/
│       └── ...
├── .claude/data/                   # 추적 DB (.claude/data/sonar_tracking.db)
└── data/                        # intake 결과 (SonarQube JSON)
```

## 사용자 수동 작업

작업 완료(DONE) 후 사용자가 직접 수행:

### 1. 리포트 확인
```bash
cat reports/{issue_key}/07_final_deliverable.md
```

### 2. 커밋 생성
```bash
cd worktrees/{issue_key}
git add .
git commit -m "커밋 메시지 (리포트에서 복사)"
```

### 3. PR 생성
```bash
git push -u origin fix/{issue_key}
gh pr create --title "제목" --body "PR 설명 (리포트에서 복사)"
```

### 4. Worktree 정리 (PR 머지 후)
```bash
.claude/skills/sonar-develop/scripts/cleanup_worktree.sh -j {issue_key}
```

## 보고서 위치

### Jira 모드
```
reports/
└── {JIRA-KEY}/
    ├── 01_analysis_report.md
    ├── 02_analysis_review.md
    ├── 03_jira_created.md
    ├── 04_fix_report.md
    ├── 05_fix_review.md
    ├── 06_test_report.md
    ├── 07_final_deliverable.md  # 커밋 메시지/PR 설명 포함
    └── 08_cto_approval.md       # CTO 승인 요청 보고서
```

### 리포트 모드
```
reports/
└── {SonarQube키}/
    ├── 01_analysis_report.md
    ├── 02_analysis_review.md
    ├── 03_jira_report.md
    ├── 04_fix_report.md
    ├── 05_fix_review.md
    ├── 06_test_report.md
    ├── 07_final_deliverable.md  # 커밋 메시지/PR 설명 포함
    └── 08_cto_approval.md       # CTO 승인 요청 보고서
```
