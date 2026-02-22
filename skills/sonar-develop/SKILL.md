---
name: sonar-develop
description: ANALYZED 상태 이슈를 수정하고 커밋 메시지 준비. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# SonarQube Issue Development

ANALYZED 상태의 이슈를 수정하고, Review Agent 검증 후 커밋 메시지를 준비합니다.

> **Bash 실행 규칙**: @guides/bash-execution-rules.md
> **에이전트 일탈 방지**: @guides/red-flags.md

## 프로젝트 컨텍스트

> **필수**: `SONAR_PROJECT_DIR` 환경변수가 **절대 경로**로 설정되어 있어야 합니다 (예: `$CLAUDE_PROJECT_DIR/projects/odin-addsvc`).
> 오케스트레이터가 `export SONAR_PROJECT_DIR=$CLAUDE_PROJECT_DIR/projects/<name>`를 설정합니다.
> 모든 경로(worktrees, reports, repo, sonar.db)는 `$SONAR_PROJECT_DIR` 하위입니다.

## 중요 정책

### Worktree 정리 금지
- **작업 완료 후에도 Worktree를 삭제하지 않음**
- 사용자가 코드 리뷰 및 수동 커밋/PR 생성을 위해 worktree 필요
- 수동 정리: `${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/cleanup_worktree.sh -j {issue_key}` (사용자가 직접 실행)

### 자동 커밋/PR 금지
- **절대로 `git commit`을 실행하지 않음**
- **절대로 `git push`를 실행하지 않음**
- **절대로 PR을 생성하지 않음**
- 커밋 메시지는 `07_final_deliverable.md`에 작성
- 사용자가 리포트를 검토 후 수동으로 커밋/PR 생성

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | string | 필수 | sonarqube_key — SonarQube 이슈 고유 키 |
| `$ARGUMENTS[1]` | JSON string | 필수 | issue_data — 이슈 정보 (아래 필수 필드 참조) |
| `$ARGUMENTS[2]` | JSON array | 선택 | group_issues — 그룹 처리 시 그룹 내 이슈 목록 |

**issue_data 필수 필드:**

| 필드 | 용도 |
|------|------|
| `파일` | 소스 코드 파일 경로 (수정 대상) |
| `라인` | 소스 코드 라인 번호 (수정 대상) |
| `메시지` | SonarQube 이슈 메시지 (수정 근거) |
| `규칙` | SonarQube 규칙 ID (준수 확인) |
| `SonarQube키` | 이슈 고유 식별자 (폴더/브랜치명) |
| `담당자` | 담당자 이름 (보고서 메타데이터) |

### 읽기 의존 파일

진행 전 반드시 존재를 확인해야 하는 파일:

| 파일 | 생성 주체 | 용도 |
|------|----------|------|
| `$SONAR_PROJECT_DIR/reports/{sonarqube_key}/01_analysis_report.md` | sonar-analyze | 해결 방안 참조하여 코드 수정 (개별 이슈) |
| `$SONAR_PROJECT_DIR/reports/group-<name>/01_analysis_report.md` | sonar-analyze | 그룹 통합 해결 방안 참조하여 코드 수정 (그룹 이슈) |

> **주의**: 읽기 의존 파일이 존재하지 않으면 진행 불가. 상태를 재확인하고 에러 보고.

### Output

```json
{
  "status": "success | failed | blocked",
  "issue_key": "AYxx...",
  "worktree_path": "$SONAR_PROJECT_DIR/worktrees/AYxx...",
  "branch": "fix/AYxx...",
  "report_path": "$SONAR_PROJECT_DIR/reports/AYxx.../07_final_deliverable.md",
  "commit_ready": true,
  "note": "커밋/PR은 사용자가 수동으로 진행"
}
```

### 생성 파일

| 파일 | 소비자 | 필수 섹션 |
|------|--------|----------|
| `$SONAR_PROJECT_DIR/reports/{issue_key}/04_fix_report.md` | sonar-review (fix) | 변경 요약, 수정 근거, 변경 파일, 사이드이펙트, 로컬 검증 |
| `$SONAR_PROJECT_DIR/reports/{issue_key}/06_test_report.md` | 사용자 | 테스트 목록, 테스트 결과, 테스트 로그 |
| `$SONAR_PROJECT_DIR/reports/{issue_key}/07_final_deliverable.md` | 사용자 | 변경 요약, 커밋 메시지, PR 설명, 수동 작업 안내 |

> **그룹 이슈**: `{issue_key}`는 `group-<group_name>`으로 대체됩니다. 예: `reports/group-fstring-fix/04_fix_report.md`
| `tests/sonar_tdd/test_{issue_key}_{function}.py` | sonar-review, 사용자 | 특성화 테스트 (TDD_REQUIRED 시) |

### SQLite DB 변경

| 변경 항목 | 값 | 시점 |
|----------|-----|------|
| status | `DEVELOPING` | 개발 시작 시 |
| status | `REVIEW_FIX` | 수정 보고서 작성 완료 시 |
| status | `TESTING` | 리뷰 PASS 후 |
| status | `DONE` | 테스트 완료 + 최종 산출물 작성 후 |
| status | `BLOCKED` | 4회 시도 실패 시 |
| develop_attempts | +1 | 각 시도마다 |

> **상태 업데이트**: `local_db.update_status(sonarqube_key, new_status)` 호출로 상태를 변경합니다.

### sonar-review 호출 규약

```
Skill("sonar-review", args: "fix {report_path} {issue_data_json}")
```

반환값: `{verdict: "PASS"|"FAIL", reason, suggestions[]}`
- PASS → TESTING 단계로 진행
- FAIL → suggestions 반영 후 재시도 (최대 3회 재시도, 총 4회)

## 입력 (요약)

- `$ARGUMENTS[0]`: sonarqube_key (SonarQube 이슈 고유 키)
- `$ARGUMENTS[1]`: issue_data (JSON 형식의 이슈 정보)
- `$ARGUMENTS[2]`: group_issues (선택, 그룹 내 이슈 JSON 배열)

## 상태 흐름

```
ANALYZED → DEVELOPING → REVIEW_FIX → TESTING → DONE
```

## 그룹 이슈 처리

`$ARGUMENTS[2]` (group_issues)가 제공되면 그룹 처리 요청으로 간주합니다.

### 그룹 처리 규칙

- **Worktree 경로**: `$SONAR_PROJECT_DIR/worktrees/group-<group_name>/` (개별 이슈: `$SONAR_PROJECT_DIR/worktrees/<sonarqube_key>/`)
- **브랜치**: `fix/group-<group_name>`
- 그룹 내 모든 이슈를 단일 worktree에서 수정
- 통합 `04_fix_report.md` 생성 (모든 그룹 이슈의 수정 내용 포함)
- 그룹 내 각 이슈의 상태를 개별적으로 DONE으로 업데이트
- 보고서 폴더: `$SONAR_PROJECT_DIR/reports/group-<group_name>/`

### 그룹 처리 흐름

1. group_issues JSON 파싱 → 이슈 목록 추출
2. 그룹 내 모든 이슈의 상태를 DEVELOPING으로 업데이트
3. 그룹 worktree 생성 (`worktrees/group-<group_name>/`)
4. 그룹 통합 `01_analysis_report.md` 참조 (`reports/group-<group_name>/`)
5. 모든 이슈를 순차 수정
6. 통합 `04_fix_report.md` 작성
7. sonar-review 호출
8. 통과 시: 모든 이슈 상태 → TESTING → DONE
9. 통합 `07_final_deliverable.md` 작성

## 실행 흐름

### 사전 검증 (필수)

Worktree 생성 전, 반드시 `validate_issue_key.py`를 실행하여 SQLite DB의 SonarQube키와 사용할 issue_key가 일치하는지 검증한다.

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-common/scripts/validate_issue_key.py \
  -k "$SONARQUBE_KEY"
```

- 검증 통과 (exit 0) → 실행 흐름 계속
- 검증 실패 (exit 1) → `$ARGUMENTS[1]`에서 SonarQube키를 다시 읽고, DB를 재확인하여 올바른 키를 사용

### 개발 단계

1. Git Worktree 생성 (`$SONAR_PROJECT_DIR/worktrees/{sonarqube_key}/` 또는 `$SONAR_PROJECT_DIR/worktrees/group-<group_name>/`)
   - `run_tests.sh`는 테스트 환경이 없으면 자동으로 `setup_test_env.sh`를 호출 (수동 실행 불필요)
2. **프로젝트 코딩 규칙 로드** (선택사항)
   - 환경변수 `CODING_RULES_PATH` 확인
   - 설정되어 있고 디렉토리가 존재하면:
     a. `SKILL.md` 읽기 — 전체 구조와 핵심 규칙
     b. `references/*.md` 읽기 — 상세 가이드
     c. `templates/*` 읽기 — 코드 패턴 참조
     d. `scripts/*` 읽기 — 유틸리티 참고
   - 로드한 규칙은 이후 모든 코드 수정에 반드시 준수
   - 미설정 또는 경로 없음 → 건너뛰고 일반 코딩 관행 적용
3. 상태 → DEVELOPING (`local_db.update_status(sonarqube_key, "DEVELOPING")`)
4. **TDD 게이팅 판단** (규칙 기반)
   - `01_analysis_report.md`의 "TDD 게이팅" 섹션 참조
   - TDD_REQUIRED → 5단계로 진행
   - TDD_SKIP → 7단계로 직행 (사유를 `04_fix_report.md`에 기록)
5. **특성화 테스트 작성** (TDD_REQUIRED일 때만)
   - `01_analysis_report.md`에서 수정 대상 함수/메서드 식별
   - **worktree 내부**에 `tests/sonar_tdd/test_{issue_key}_{function}.py` 생성
   - @templates/tdd_guidelines.md 참조
6. **BEFORE 테스트 실행** → GREEN 확인
   - `${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/`
   - run_tests.sh가 자동으로 worktree에서 실행하고, Python venv도 자동 활성화
   - FAIL 시: 테스트 수정 (기존 동작에 맞춤, 최대 3회)
7. 분석 보고서 참고하여 코드 수정
8. **AFTER 테스트 실행** → GREEN 확인 (TDD_REQUIRED일 때만)
   - 동일 테스트 재실행
   - FAIL 시: 코드 수정이 기존 동작을 깨뜨린 것 → 코드 재수정
9. 수정 보고서 작성 (`04_fix_report.md`) — TDD 결과 포함
10. 상태 → REVIEW_FIX (`local_db.update_status(sonarqube_key, "REVIEW_FIX")`)
11. sonar-review 호출하여 검증
12. 통과 시: 상태 → TESTING (`local_db.update_status(sonarqube_key, "TESTING")`)
13. 테스트 보고서 작성 (`06_test_report.md`) — TDD 섹션 포함
14. 상태 → DONE (`local_db.update_status(sonarqube_key, "DONE", assignee=ASSIGNEE_NAME)`)
15. **최종 산출물 작성** (`07_final_deliverable.md`) — TDD 산출물 포함
    - 커밋 메시지 작성 (실제 커밋 X)
    - PR 설명 작성 (실제 PR 생성 X)
16. **Worktree 유지** (삭제하지 않음)

## 스크립트

### create_worktree.sh

```bash
# 개별 이슈
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/create_worktree.sh -j AYxx...

# 그룹 이슈
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/create_worktree.sh -j group-<group_name>
```

### cleanup_worktree.sh (수동 정리용)

```bash
# 사용자가 직접 실행 - 자동 호출 금지
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/cleanup_worktree.sh -j {issue_key}
```

### setup_test_env.sh (최초 1회)

```bash
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/setup_test_env.sh
```

repo에 테스트 환경을 초기 구성한다. Python: venv 생성 + 의존성 설치, Java: 의존성 다운로드, Node.js: npm install.
`run_tests.sh`가 venv 미존재 시 자동 호출하므로, 수동 실행은 선택사항.

### run_tests.sh

```bash
# worktree에서 특정 테스트 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/

# worktree에서 전체 테스트 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --all

# repo에서 전체 테스트 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --all
```

프로젝트 타입을 자동 감지하여 적절한 테스트 명령을 실행한다. Python venv는 repo에서 자동 활성화.

### local_db.py (상태 업데이트)

```python
# Python API로 상태 업데이트
from local_db import update_status, add_execution

update_status(sonarqube_key, "DEVELOPING")
update_status(sonarqube_key, "REVIEW_FIX")
update_status(sonarqube_key, "TESTING")
update_status(sonarqube_key, "DONE", assignee=ASSIGNEE_NAME)

# 실행 이력 기록
add_execution(sonarqube_key, "develop", "success")
add_execution(sonarqube_key, "develop", "failure", details="error message")
```

## 테스트 실행 규칙 (필수)

1. 모든 테스트는 worktree 디렉토리 안에서 실행한다
2. repo 디렉토리에서 실행하면 수정 전 코드가 테스트되므로 무효
3. Python 프로젝트: repo의 venv를 활성화 후 worktree에서 실행
4. Java 프로젝트: worktree에서 직접 빌드 도구 실행
5. 반드시 run_tests.sh를 사용한다 (직접 pytest/gradle 실행 금지)

### venv 공유 구조 (Python)

```
repo/project/
├── venv/              ← 공유 venv (setup_test_env.sh로 생성)
├── src/
└── requirements.txt

worktrees/AYxx.../     ← worktree (수정된 코드)
├── src/               ← 이 코드가 테스트됨
└── tests/sonar_tdd/   ← 특성화 테스트

실행: repo venv 활성화 → PYTHONPATH=worktree → worktree cd → pytest
→ PYTHONPATH에 의해 worktree의 수정된 코드가 우선 import됨
→ editable install(pip install -e .)이 repo를 가리켜도 안전
```

## Worktree 구조

```
worktrees/
├── AYxx.../            # 개별 이슈 (작업 완료 후에도 유지)
├── AYyy.../            # 개별 이슈 (작업 완료 후에도 유지)
└── group-security/     # 그룹 이슈 (작업 완료 후에도 유지)
```

- 브랜치: `fix/{sonarqube_key}` 또는 `fix/group-<group_name>`
- 베이스: `origin/{REPO_BRANCH}`

## 템플릿

- [templates/fix_report.md](templates/fix_report.md)
- [templates/test_report.md](templates/test_report.md)
- [templates/final_deliverable.md](templates/final_deliverable.md) - **커밋 메시지 포함**
- [templates/tdd_guidelines.md](templates/tdd_guidelines.md) - **TDD 특성화 테스트 가이드**

## TDD 게이팅 규칙

`01_analysis_report.md`에 기록된 TDD 게이팅 판정을 참조한다. sonar-develop은 판정 결과를 읽기만 한다.

### TDD_REQUIRED → 테스트 작성 필수

- 타입이 BUG 또는 VULNERABILITY
- 품질이 SECURITY 또는 RELIABILITY
- 수정이 함수 시그니처/반환값/동작을 변경
- 큰 리팩터링 (영향 함수 3개 이상)
- 기존 테스트가 없는 영역

### TDD_SKIP → 테스트 작성 생략

- 타입이 CODE_SMELL이고 심각도 MINOR/INFO
- 변수명/메서드명 변경만 필요
- 주석/문서/로깅만 변경
- 사용하지 않는 import 제거
- 단순 코드 포맷팅

> **주의**: TDD_SKIP일 때도 `04_fix_report.md`에 스킵 사유를 기록한다.

### 테스트 가이드라인

@templates/tdd_guidelines.md 참조

## 재시도 규칙

- Review Agent가 FAIL 판정 시 재시도
- 최대 3회 재시도 (총 4회 시도)
- 4회 실패 시 BLOCKED 상태로 전환

## 금지 사항 체크리스트 (settings.json `permissions.deny`로 기술적 차단)

- [ ] `git commit` 실행 금지
- [ ] `git push` 실행 금지
- [ ] `gh pr create` 실행 금지
- [ ] `git worktree remove` 자동 실행 금지
- [ ] `cleanup_worktree.sh` 자동 호출 금지
- [ ] `rm -rf` 재귀적 삭제 금지
- [ ] `git reset --hard` 변경사항 폐기 금지
- [ ] `git checkout .` 워킹 디렉토리 변경 폐기 금지
- [ ] `git clean -f` 추적되지 않는 파일 삭제 금지
