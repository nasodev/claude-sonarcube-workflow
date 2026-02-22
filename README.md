# Sonar Workflow Plugin for Claude Code

SonarQube 코드 이슈를 **수집 → 분석 → 수정 → 검증 → 승인**까지 자동 처리하는 Claude Code 워크플로우 플러그인.

독립 서브에이전트 병렬 처리, TDD 게이팅, Jira 연동, 웹 대시보드를 지원합니다.

## 주요 기능

- **자동 이슈 수집**: SonarQube API에서 이슈를 가져와 로컬 SQLite에 저장 (10k+ 이슈 자동 분할 처리)
- **AI 분석/수정**: Claude 에이전트가 소스코드를 읽고 근본 원인 분석 → 코드 수정까지 자동 수행
- **리뷰 게이트**: 분석/수정 결과를 자동 검증하여 PASS/FAIL 판정 (최대 4회 재시도)
- **TDD 게이팅**: BUG/VULNERABILITY 등 주요 이슈는 테스트 작성 후 수정 (선택적 적용)
- **병렬 처리**: 최대 10개 서브에이전트가 동시에 이슈 처리 (기본 5개)
- **이슈 그룹화**: 동일 규칙의 단순 이슈(unused import, fstring 등)를 자동 그룹화하여 일괄 처리
- **Jira 연동**: 승인 시 Jira 티켓 자동 생성 + 브랜치 생성 + 커밋 + 머지
- **웹 대시보드**: FastAPI + Next.js 기반 실시간 모니터링 (별도 구성)

## 요구 사항

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- Python 3.10+
- Git
- SonarQube 서버 + API 토큰
- (선택) Jira 서버 + 계정
- (선택) 웹 서비스 (Docker Compose)

## 설치

### 1. 플러그인 설치

```bash
# Claude Code 프로젝트 디렉토리의 .claude/ 아래에 배치
# 또는 GitHub에서 직접 설치
git clone https://github.com/nasodev/claude-sonarcube-workflow.git
```

### 2. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 생성합니다.

```bash
cp claude/.env.example .env
```

```bash
# .env
WEB_SERVICE_URL=              # 웹서비스 URL (선택, 동기화용)
API_AUTH_KEY=                  # 웹서비스 인증키 (선택)

JIRA_ID=                      # Jira 사용자 ID (승인 시 사용)
JIRA_PASSWORD=                # Jira 비밀번호

ASSIGNEE_NAME=                # 이슈 담당자 이름
TEAM_MEMBERS=                 # 팀원 목록 (콤마 구분)
MAX_CONCURRENT_AGENTS=5       # 병렬 서브에이전트 수 (2~10, 기본 5)
```

## 사용법

### 프로젝트 초기 설정

웹 서비스에 등록된 프로젝트를 기반으로 로컬 작업 환경을 구성합니다.

```bash
/sonar-setup --id=<project_id>
```

실행 결과:
- `projects/<name>/` 디렉토리 생성 (DB, 리포지토리 클론, 작업 디렉토리)
- SonarQube에서 이슈 수집 → SQLite 저장
- 프로젝트별 `.env` 자동 생성

### 이슈 처리 워크플로우

```bash
# 전체 NEW 이슈 자동 처리 (분석 → 리뷰 → 수정 → 검증 → DONE)
/sonar --action=run --id=<project_id>

# 최대 N개 이슈만 처리
/sonar --action=run --id=<project_id> --limit=5

# 특정 이슈 처리
/sonar --action=run --id=<project_id> --key=AZO...

# 그룹 이슈 일괄 처리
/sonar --action=run --id=<project_id> --key=group-unused-imports
```

### 이슈 그룹화

단순/반복 이슈를 자동 분석하여 그룹으로 묶습니다.

```bash
/sonar --action=group --id=<project_id>
```

그룹화 대상: unused import, fstring 변환, 미사용 변수, 타입 힌트, 세미콜론 제거 등

### 승인/반려

```bash
# 승인: Jira 티켓 생성 → 브랜치 → 커밋 → 머지
/sonar --action=approve --id=<project_id> --key=AZO...

# 반려: BLOCKED 처리 + worktree/리포트 정리
/sonar --action=reject --id=<project_id> --key=AZO...
```

### 상태 확인

```bash
/sonar --action=status --id=<project_id>
```

### 웹 서비스 동기화

```bash
/sonar-sync --id=<project_id>
```

## 워크플로우 상태 전이

```
NEW → ANALYZING ↔ REVIEW_ANALYSIS → ANALYZED → DEVELOPING ↔ REVIEW_FIX → TESTING → DONE
         |                                          |
      (4회 실패)                                 (4회 실패)
         ↓                                          ↓
      BLOCKED                                    BLOCKED

DONE ──→ APPROVED  (승인: Jira + git commit + merge)
    └──→ BLOCKED   (반려)
```

각 단계에서 리뷰 게이트를 통과해야 다음 단계로 진행됩니다. 4회 연속 실패 시 BLOCKED로 전환되며 수동 개입이 필요합니다.

## 아키텍처

### 스킬 구성

```
claude/skills/
├── sonar/             # 오케스트레이터 (디스패치 + 병렬 실행)
├── sonar-setup/       # 프로젝트 초기 설정 + 이슈 수집
├── sonar-intake/      # SonarQube API → SQLite 이슈 수집
├── sonar-group/       # 단순/반복 이슈 자동 그룹화
├── sonar-analyze/     # NEW → ANALYZED (분석 보고서 생성)
├── sonar-develop/     # ANALYZED → DONE (코드 수정, TDD)
├── sonar-review/      # 분석/수정 결과 검증 (PASS/FAIL)
├── sonar-approve/     # DONE → APPROVED (Jira + git)
├── sonar-reject/      # DONE → BLOCKED (반려 + 정리)
├── sonar-sync/        # 웹서비스 동기화 (CLI → Server)
├── sonar-dashboard/   # HTML 대시보드 생성
└── sonar-common/      # 공통 모듈 (DB, API 클라이언트, 환경변수)
```

| 스킬 | 유형 | 호출 방식 | 역할 |
|------|------|-----------|------|
| `sonar` | 오케스트레이터 | 사용자 | 명령 디스패치, 병렬 서브에이전트 관리 |
| `sonar-setup` | 초기화 | 사용자 | 프로젝트 디렉토리 생성, 리포 클론, 이슈 수집 |
| `sonar-intake` | 수집 | 내부 | SonarQube API 호출, SQLite 저장 |
| `sonar-group` | 분석 | 내부 | 단순 이슈 패턴 분석, 자동 그룹 생성 |
| `sonar-analyze` | 분석 | 내부 | 소스코드 읽기, 근본 원인 분석, 보고서 작성 |
| `sonar-develop` | 개발 | 내부 | Git worktree에서 코드 수정, TDD, 최종 산출물 |
| `sonar-review` | 검증 | 내부 | 분석/수정 보고서 PASS/FAIL 판정 |
| `sonar-approve` | 승인 | 내부 | Jira 생성, 브랜치, 커밋, 머지 |
| `sonar-reject` | 반려 | 내부 | BLOCKED 전환, worktree/리포트 정리 |
| `sonar-sync` | 동기화 | 사용자 | 로컬 SQLite → 웹 서비스 업로드 |
| `sonar-dashboard` | 리포팅 | 내부 | HTML 대시보드 생성 |
| `sonar-common` | 라이브러리 | - | DB, API, 환경변수 공통 모듈 |

### 처리 흐름

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  SonarQube  │────▶│  sonar-setup │────▶│  SQLite DB   │
│  API        │     │  (intake)    │     │  (sonar.db)  │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                    ┌──────────────────────────┐ │
                    │  /sonar run (orchestrator)│◀┘
                    │  MAX_CONCURRENT_AGENTS=5  │
                    └──────┬───────────────────┘
                           │ fork (1 issue = 1 subagent)
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
   │ subagent #1 │ │ subagent #2 │ │ subagent #N │
   │ analyze     │ │ analyze     │ │ analyze     │
   │ → review    │ │ → review    │ │ → review    │
   │ → develop   │ │ → develop   │ │ → develop   │
   │ → review    │ │ → review    │ │ → review    │
   │ → DONE      │ │ → BLOCKED   │ │ → DONE      │
   └──────┬──────┘ └─────────────┘ └──────┬──────┘
          │                                │
          ▼                                ▼
   ┌─────────────┐                 ┌──────────────┐
   │ sonar-sync  │────────────────▶│  Web Service │
   │ (upload)    │                 │  (PostgreSQL)│
   └─────────────┘                 └──────────────┘
```

### 프로젝트 디렉토리 구조

`/sonar-setup` 실행 후 생성되는 프로젝트별 작업 디렉토리:

```
projects/<name>/
├── .env                    # 프로젝트 환경변수 (SonarQube, Jira, Repo 설정)
├── sonar.db                # SQLite 로컬 DB
├── data/                   # SonarQube 수집 원본 데이터 (JSON)
├── repo/<name>/            # 소스코드 리포지토리 (git clone)
├── worktrees/<key>/        # Git worktree (이슈별 격리 작업 공간)
└── reports/<key>/          # 이슈별 산출물
    ├── 01_analysis_report.md     # 분석 보고서
    ├── 02_analysis_review.md     # 분석 리뷰 결과
    ├── 04_fix_report.md          # 수정 보고서
    ├── 05_fix_review.md          # 수정 리뷰 결과
    ├── 06_test_report.md         # 테스트 보고서
    └── 07_final_deliverable.md   # 최종 산출물 (커밋 메시지, PR 설명)
```

### TDD 게이팅

분석 단계에서 이슈 특성에 따라 TDD 적용 여부를 자동 결정합니다.

| 조건 | TDD 적용 |
|------|----------|
| BUG, VULNERABILITY 타입 | 필수 |
| SECURITY, RELIABILITY 품질 | 필수 |
| 3개 이상 함수 리팩토링 | 필수 |
| 기존 테스트 없는 영역 | 필수 |
| CODE_SMELL (minor/info) | 생략 |
| 변수/메서드 이름 변경 | 생략 |
| 주석/문서, import 정리, 포맷팅 | 생략 |

### 안전 장치

**Permission 제한** (`settings.json`):
- `git push --force`, `git reset --hard`, `git clean -f` 차단
- `gh pr create` 차단 (승인 워크플로우 통해서만 가능)
- `rm -rf` 차단
- Worktree 자동 삭제 차단

**에이전트 규칙**:
- 1 이슈 = 1 서브에이전트 (예외 없음)
- 상태 전이 순서 필수 (건너뛰기 금지)
- 리뷰 없이 다음 단계 진행 금지
- Worktree는 사용자가 직접 정리

## 웹 서비스

별도의 웹 대시보드로 프로젝트/이슈/그룹을 관리하고 실시간 진행 상황을 모니터링할 수 있습니다.

**기술 스택**: FastAPI + Next.js 14 + PostgreSQL 16 + Nginx

```bash
cd web-service

# Docker Compose로 실행
make up                     # 백엔드 + 프론트엔드 + Nginx
make up-with-db             # PostgreSQL 포함

# 포트 구성
# Nginx:     localhost:10010
# Frontend:  localhost:10081
# Backend:   localhost:10082
```

| 기능 | 설명 |
|------|------|
| 프로젝트 관리 | CRUD, SonarQube/Jira/Repo 설정 |
| 이슈 목록 | 상태별 필터, 페이지네이션, 승인/반려 |
| 이슈 그룹 | 그룹별 이슈 관리 |
| 대시보드 | 상태별 통계, 실시간 WebSocket 업데이트 |
| CLI 동기화 | `/sonar-sync`로 로컬 데이터 업로드 |

## 라이선스

MIT

## 작성자

[nasodev](https://github.com/nasodev)
