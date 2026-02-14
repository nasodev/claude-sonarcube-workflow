# claude-sonarcube-workflow

SonarQube 코드 이슈를 수집 → 분석 → 수정 → 검증까지 자동 처리하는 Claude Code 워크플로우 플러그인.

## 주요 기능

- **이슈 수집** (sonar-intake): SonarQube API에서 이슈를 수집하여 Google Sheets에 업로드
- **이슈 분석** (sonar-analyze): 코드 분석 후 Jira 티켓 또는 리포트 생성
- **코드 수정** (sonar-develop): Git Worktree에서 코드 수정, TDD 게이팅 지원
- **검증** (sonar-review): 독립 에이전트가 분석/수정 결과를 PASS/FAIL 판정
- **대시보드** (sonar-dashboard): HTML 대시보드 생성
- **병렬 처리**: 최대 `MAX_CONCURRENT_AGENTS`개 서브에이전트 동시 실행 (1이슈 = 1서브에이전트, 기본값 5, 2-10 설정 가능)

## 설치

### 마켓플레이스를 통한 설치

```shell
# 마켓플레이스 추가 (최초 1회)
/plugin marketplace add nasodev/nasodev-marketplace

# 플러그인 설치
/plugin install sonar@nasodev-marketplace
```

### 직접 설치

```shell
/plugin install --url https://github.com/nasodev/claude-sonarcube-workflow.git
```

## 환경 설정

1. `.env.example`을 프로젝트 루트에 `.env`로 복사:

```bash
cp .env.example .env
```

2. `.env` 파일에서 환경변수 설정:

```bash
# SonarQube
SONARQUBE_URL=https://your-sonarqube.example.com
SONARCUBE_TOKEN=your_token

# Jira (JIRA_ENABLED=false면 불필요)
JIRA_URL=https://jira.example.com
JIRA_ID=your_id
JIRA_PASSWORD=your_password
PROJECT_KEY=YOUR_PROJECT
JIRA_ENABLED=true

# Google Sheets
SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_CREDENTIALS=credentials.json

# Workflow
ASSIGNEE_NAME=담당자이름
MAX_CONCURRENT_AGENTS=5  # 동시 실행 서브에이전트 수 (1-10, 기본값 5)

# Repository
REPO_PATH=repo/your-project
REPO_URL=git@github.com:org/your-project.git
REPO_BRANCH=main

# Debug
DEBUG_MODE=false
```

3. Google 서비스 계정 키 (`credentials.json`)를 프로젝트 루트에 배치

## 사용법

### 기본 명령어

```shell
# 이슈 수집
/sonar intake

# 이슈 할당 (5개)
/sonar claim 5

# 모든 담당 이슈 병렬 처리
/sonar run

# Jira 없이 리포트 모드로 실행
/sonar run --no-jira

# 현황 조회
/sonar status

# 작업 승인/반려
/sonar approve ODIN-123
/sonar reject ODIN-123
```

### 워크플로우

```
이슈 수집 → 할당 → 분석 → 리뷰 → Jira/리포트 → 개발 → 리뷰 → 테스트 → 완료
```

상태 전이:
```
대기 → CLAIMED → ANALYZING ⟷ REVIEW_ANALYSIS → JIRA_CREATED/REPORT_CREATED
→ DEVELOPING ⟷ REVIEW_FIX → TESTING → DONE
```

### 작업 완료 후 (수동)

```bash
# 리포트 확인
cat reports/{issue_key}/07_final_deliverable.md

# 커밋 생성
cd worktrees/{issue_key}
git add .
git commit -m "커밋 메시지 (리포트에서 복사)"

# PR 생성
git push -u origin fix/{issue_key}
gh pr create --title "제목" --body "PR 설명"

# Worktree 정리 (PR 머지 후)
.claude/skills/sonar-develop/scripts/cleanup_worktree.sh -j {issue_key}
```

## 스킬 구성

| 스킬 | 설명 | User Invocable |
|------|------|:-:|
| sonar | 오케스트레이터 | O |
| sonar-intake | 이슈 수집 | X |
| sonar-analyze | 이슈 분석 | X |
| sonar-develop | 코드 수정 | X |
| sonar-review | 검증 | X |
| sonar-common | 공통 모듈 | X |
| sonar-dashboard | 대시보드 | O |

## 보안 설정

`settings.json`에서 위험한 명령어를 차단합니다:

- `git commit`, `git push`, `gh pr create` — 자동 커밋/PR 금지
- `git worktree remove`, `cleanup_worktree` — Worktree 자동 삭제 금지
- `rm -rf`, `git reset --hard`, `git checkout .`, `git clean -f` — 파괴적 명령 금지

## 디버그 모드

`.env`에서 `DEBUG_MODE=true` 설정 시:

- Stop, SubagentStop, SessionEnd 이벤트마다 대화 기록 저장
- 저장 위치: `history/{issue_key}/`
- 요약 마크다운 + 원본 JSONL 트랜스크립트

## 라이선스

MIT
