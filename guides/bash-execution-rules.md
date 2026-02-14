# Bash 실행 규칙 (필수 준수)

> 이 문서의 규칙은 sonar 워크플로우의 모든 Bash 실행에 반드시 적용됩니다.
> 위반 시 "파일을 찾을 수 없음", "데이터 손실", "조용한 실패" 등의 문제가 발생합니다.

---

## 1. 프로젝트 루트 경로 (PROJECT_ROOT)

### 왜 필요한가?

- 서브에이전트(`context: fork`)에서 실행 시 현재 디렉토리가 예측 불가
- `dirname` 체인(`$(dirname "$(dirname ...)")`)은 디렉토리 구조 변경 시 즉시 깨짐
- 하드코딩된 경로는 다른 환경에서 실패
- **플러그인 환경**에서는 스크립트가 캐시 디렉토리(`~/.claude/plugins/cache/...`)에서 실행되므로 `git rev-parse`가 프로젝트를 찾을 수 없음

### 올바른 방법

```bash
# 방법 0: CLAUDE_PROJECT_DIR 우선 사용 (플러그인 환경 호환, 최우선)
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="$CLAUDE_PROJECT_DIR"
else
    # 방법 1: Git 루트 사용 (로컬 .claude/skills 환경)
    PROJECT_ROOT=$(git rev-parse --show-toplevel 2>&1) || {
        echo "Error: Git 프로젝트가 아닙니다: $PROJECT_ROOT"
        exit 1
    }
fi

# 방법 2: .claude 디렉토리 탐색 (Git이 없고 CLAUDE_PROJECT_DIR도 없을 경우)
PROJECT_ROOT=$(pwd)
while [[ ! -d "$PROJECT_ROOT/.claude" ]] && [[ "$PROJECT_ROOT" != "/" ]]; do
    PROJECT_ROOT=$(dirname "$PROJECT_ROOT")
done

# 검증 (필수)
if [[ ! -d "$PROJECT_ROOT/.claude" ]]; then
    echo "Error: 프로젝트 루트를 찾을 수 없습니다 (현재: $(pwd))"
    exit 1
fi
```

> **참고:** `CLAUDE_PROJECT_DIR`은 Claude Code가 플러그인 환경에서 자동 설정하는 환경변수로, 현재 프로젝트 디렉토리를 가리킵니다. 로컬 `.claude/skills` 환경에서도 설정될 수 있으므로 항상 우선 확인합니다.

### 잘못된 방법

```bash
# dirname 체인 - 구조 변경 시 깨짐
ROOT_DIR="$(dirname "$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")")"

# SCRIPT_DIR 기준 .env 탐색 - 잘못된 위치
ENV_FILE="$SCRIPT_DIR/.env"
```

---

## 2. 환경변수 로드 (.env)

### 왜 필요한가?

- sonar 스크립트는 `SONARCUBE_TOKEN`, `JIRA_URL`, `REPO_PATH` 등 환경변수에 의존
- `.env` 파일은 항상 **프로젝트 루트**에 위치 (`$PROJECT_ROOT/.env`)
- `source` 실패 시 빈 변수로 API 호출 → 조용한 실패

### 올바른 방법

```bash
ENV_FILE="$PROJECT_ROOT/.env"

# 존재 확인
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env 파일을 찾을 수 없습니다: $ENV_FILE"
    exit 1
fi

# 로드 및 에러 검증
if ! source "$ENV_FILE" 2>&1; then
    echo "Error: .env 파일 로드 실패"
    exit 1
fi

# 필수 변수 검증
if [[ -z "$SONARCUBE_TOKEN" ]]; then
    echo "Error: SONARCUBE_TOKEN이 설정되지 않았습니다"
    exit 1
fi
```

### 잘못된 방법

```bash
# 스크립트 디렉토리에서 .env 탐색 - 잘못된 위치
ENV_FILE="$SCRIPT_DIR/.env"

# 에러 무시하는 복잡한 파이프라인
export $(grep -v '^#' "$ROOT_DIR/.env" | sed 's/#.*//' | xargs)

# source 에러 무시
source "$ENV_FILE"  # 구문 오류 시 조용히 실패
```

---

## 3. 에러 출력 규칙

### 왜 필요한가?

- sonar 스크립트는 외부 API(SonarQube, Jira, Google Sheets)에 의존
- 네트워크 에러, 인증 실패 등이 빈번 → 에러 정보 필수
- `2>/dev/null`은 실패 원인을 완전히 숨김

### 올바른 방법

```bash
# 모든 명령에 2>&1 포함
RESULT=$(python3 "$PROJECT_ROOT/.claude/skills/sonar-intake/scripts/sheets_upload.py" 2>&1)
EXIT_CODE=$?
if [[ $EXIT_CODE -ne 0 ]]; then
    echo "Error (exit $EXIT_CODE): $RESULT"
    exit 1
fi

# curl: -s 대신 에러 정보 보존
RESPONSE=$(curl -w "\n%{http_code}" \
    -u "$SONARCUBE_TOKEN:" \
    "$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&ps=1" 2>&1)
```

### 잘못된 방법

```bash
# -s로 에러 숨김 + jq 실패 무시
TOTAL=$(curl -s -u "$TOKEN:" "$URL" | jq '.total')

# 에러 출력 폐기
python3 script.py 2>/dev/null

# 에러 미확인
jq '.issues' "$FILE" >> "$OUTPUT"  # jq 실패 시 빈 데이터 기록
```

---

## 4. API 호출 규칙 (curl)

### 왜 필요한가?

- SonarQube API, Jira API 호출이 sonar 워크플로우의 핵심
- 네트워크 단절, 토큰 만료, Rate Limit 등 다양한 실패 가능
- HTTP 상태 코드 + 응답 본문 모두 검증 필요

### 올바른 방법

```bash
# HTTP 상태 코드 분리 캡처
RESPONSE=$(curl -w "\n%{http_code}" \
    -u "$SONARCUBE_TOKEN:" \
    "$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&ps=$PAGE_SIZE&p=$page" 2>&1)

# 네트워크 에러 확인
if [[ $? -ne 0 ]]; then
    echo "Error: curl 실행 실패 (네트워크 오류)"
    echo "$RESPONSE"
    exit 1
fi

# HTTP 상태 코드 확인
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ -z "$HTTP_CODE" || "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    echo "Error: API 호출 실패 (HTTP $HTTP_CODE)"
    echo "$BODY"
    exit 1
fi

# JSON 파싱 검증
if ! echo "$BODY" | jq '.' > /dev/null 2>&1; then
    echo "Error: 응답이 유효한 JSON이 아닙니다"
    echo "$BODY"
    exit 1
fi
```

### 잘못된 방법

```bash
# 네트워크 에러 무시, JSON 파싱 에러 무시
TOTAL=$(curl -s -u "$TOKEN:" "$URL" | jq '.total')

# HTTP 코드 미확인
RESPONSE=$(curl -s "$URL")
ISSUES=$(echo "$RESPONSE" | jq '.issues')  # 401/403 HTML 응답이면 jq 실패
```

---

## 5. 파이프라인 규칙

### 왜 필요한가?

- sonar-intake에서 `curl | jq | paste` 파이프라인 사용
- 중간 단계 실패 시 빈 데이터가 다음 단계로 전달 → 데이터 손실
- Bash는 기본적으로 파이프라인 마지막 명령의 종료 코드만 반환

### 올바른 방법

```bash
# 스크립트 상단에 pipefail 설정
set -euo pipefail

# 또는 단계별 실행 (더 안전)
ISSUES=$(echo "$RESPONSE" | jq '.issues' 2>&1)
if [[ $? -ne 0 ]]; then
    echo "Error: JSON 파싱 실패: $ISSUES"
    exit 1
fi

FORMATTED=$(echo "$ISSUES" | jq -c '.[]' 2>&1)
if [[ $? -ne 0 ]]; then
    echo "Error: 이슈 포매팅 실패: $FORMATTED"
    exit 1
fi

echo "$FORMATTED" | paste -sd ',' - >> "$OUTPUT_FILE"
```

### 잘못된 방법

```bash
# 중간 실패 무시 - jq 실패 시 빈 데이터 기록
echo "$ISSUES" | jq -c '.[]' | paste -sd ',' - >> "$OUTPUT_FILE"

# pipefail 없이 긴 파이프라인
curl -s "$URL" | jq '.issues' | jq -c '.[]' | paste -sd ',' - >> "$FILE"
```

---

## 6. 디렉토리 변경 규칙

### 왜 필요한가?

- sonar-develop의 `create_worktree.sh`가 `cd $FULL_REPO_PATH` 사용
- 스크립트 중간에 에러 발생 시 사용자가 잘못된 디렉토리에 남음
- 이후 `$PROJECT_ROOT` 기준 경로가 모두 깨짐

### 올바른 방법

```bash
# 서브셸로 격리 (권장)
(
    cd "$FULL_REPO_PATH" || exit 1
    git fetch origin 2>&1 || exit 1
    git checkout "$BASE_BRANCH" 2>&1 || exit 1
    git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "origin/$BASE_BRANCH" 2>&1 || exit 1
) || {
    echo "Error: Worktree 생성 실패"
    exit 1
}

# pushd/popd 사용 (디버깅이 필요한 경우)
pushd "$FULL_REPO_PATH" > /dev/null || exit 1
git fetch origin 2>&1
git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "origin/$BASE_BRANCH" 2>&1
popd > /dev/null
```

### 잘못된 방법

```bash
# 직접 cd - 에러 시 복구 불가
cd "$FULL_REPO_PATH"
git fetch origin
git worktree add ...
# 여기서 에러 발생 시 사용자는 $FULL_REPO_PATH에 남아 있음
```

---

## 7. 실행 전 체크리스트

모든 Bash 스크립트 작성/실행 전 확인:

| # | 체크 항목 | 확인 방법 |
|---|----------|----------|
| 1 | PROJECT_ROOT 동적 취득 | `CLAUDE_PROJECT_DIR` 우선 → `git rev-parse` 폴백 |
| 2 | .env 위치 올바름 | `$PROJECT_ROOT/.env` 사용 |
| 3 | 에러 출력 포함 | 모든 명령에 `2>&1` 사용 |
| 4 | curl 에러 검증 | HTTP 코드 + 응답 본문 확인 |
| 5 | pipefail 설정 | `set -euo pipefail` 또는 단계별 검증 |
| 6 | cd 격리됨 | 서브셸 `()` 또는 `pushd/popd` 사용 |
| 7 | 하드코딩 경로 없음 | `dirname` 체인, `/Users/...` 패턴 없음 |

---

## 8. 표준 명령어 템플릿

### 스크립트 시작 (공통 프리앰블)

```bash
#!/bin/bash
set -euo pipefail

# 프로젝트 루트 동적 취득 (CLAUDE_PROJECT_DIR 우선, 플러그인 환경 호환)
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="$CLAUDE_PROJECT_DIR"
else
    PROJECT_ROOT=$(git rev-parse --show-toplevel 2>&1) || {
        echo "Error: Git 프로젝트가 아닙니다: $PROJECT_ROOT"
        exit 1
    }
fi
if [[ ! -d "$PROJECT_ROOT/.claude" ]]; then
    echo "Error: 프로젝트 루트를 찾을 수 없습니다 (현재: $(pwd))"
    exit 1
fi

# 환경변수 로드
ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env 파일이 없습니다: $ENV_FILE"
    exit 1
fi
source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }
```

### SonarQube API 호출

```bash
RESPONSE=$(curl -w "\n%{http_code}" \
    -u "$SONARCUBE_TOKEN:" \
    "$SONARQUBE_URL/api/issues/search?componentKeys=$PROJECT_KEY&ps=$PAGE_SIZE&p=$page" 2>&1)

if [[ $? -ne 0 ]]; then echo "Error: 네트워크 오류"; exit 1; fi

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    echo "Error: SonarQube API 실패 (HTTP $HTTP_CODE): $BODY"
    exit 1
fi
```

### Jira API 호출

```bash
RESPONSE=$(curl -w "\n%{http_code}" \
    -u "$JIRA_ID:$JIRA_PASSWORD" \
    -X POST \
    -H "Content-Type: application/json" \
    -d "$JSON_PAYLOAD" \
    "$JIRA_URL/rest/api/2/issue" 2>&1)

if [[ $? -ne 0 ]]; then echo "Error: 네트워크 오류"; exit 1; fi

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ -z "$HTTP_CODE" || "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    echo "Error: Jira API 실패 (HTTP $HTTP_CODE): $BODY"
    exit 1
fi
```

### Git Worktree 생성

```bash
(
    cd "$FULL_REPO_PATH" || exit 1
    git fetch origin 2>&1 || { echo "Error: git fetch 실패"; exit 1; }
    git worktree add -b "fix/$ISSUE_KEY" "$WORKTREE_PATH" "origin/$BASE_BRANCH" 2>&1 || {
        echo "Error: worktree 생성 실패"
        exit 1
    }
) || exit 1
```

---

## 9. 오류 발생 시 디버깅

```bash
# 현재 상태 확인
echo "현재 디렉토리: $(pwd)"
echo "PROJECT_ROOT: $PROJECT_ROOT"
echo ".claude 존재: $(ls -d $PROJECT_ROOT/.claude 2>&1)"
echo ".env 존재: $(ls -l $PROJECT_ROOT/.env 2>&1)"

# 환경변수 확인 (토큰 마스킹)
echo "SONARCUBE_TOKEN: ${SONARCUBE_TOKEN:+설정됨}"
echo "JIRA_URL: ${JIRA_URL:-미설정}"
echo "REPO_PATH: ${REPO_PATH:-미설정}"

# 명령어 상세 실행
set -x  # 명령어 출력 활성화
python3 "$PROJECT_ROOT/.claude/skills/sonar-intake/scripts/sheets_upload.py" 2>&1
set +x  # 비활성화
```

---

## 요약: 필수 규칙 5가지

| # | 규칙 | 핵심 |
|---|------|------|
| 1 | **동적 경로** | `CLAUDE_PROJECT_DIR` 우선 → `git rev-parse` 폴백 — `dirname` 체인 금지 |
| 2 | **환경변수** | `$PROJECT_ROOT/.env`에서 로드 — 스크립트 디렉토리 기준 금지 |
| 3 | **에러 포함** | 항상 `2>&1` 사용 — `2>/dev/null`, `curl -s` 단독 사용 금지 |
| 4 | **API 검증** | HTTP 상태 코드 + 응답 본문 모두 확인 — 조용한 실패 금지 |
| 5 | **디렉토리 격리** | 서브셸 `()` 또는 `pushd/popd` — 직접 `cd` 금지 |
