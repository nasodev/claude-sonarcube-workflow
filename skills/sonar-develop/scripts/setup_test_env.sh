#!/bin/bash

# Setup Test Environment (최초 1회 실행)
# Usage: ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/setup_test_env.sh

set -euo pipefail

# ============================================
# 프로젝트 디렉토리 (SONAR_PROJECT_DIR 필수)
# ============================================
if [[ -z "${SONAR_PROJECT_DIR:-}" ]]; then
    echo "Error: SONAR_PROJECT_DIR 환경변수가 설정되지 않았습니다"
    exit 1
fi
if [[ ! -d "$SONAR_PROJECT_DIR" ]]; then
    echo "Error: 프로젝트 디렉토리가 존재하지 않습니다: $SONAR_PROJECT_DIR"
    exit 1
fi

# 상대 경로를 절대 경로로 변환
SONAR_PROJECT_DIR="$(cd "$SONAR_PROJECT_DIR" && pwd)"

# ============================================
# .env 로딩
# ============================================
ENV_FILE="$SONAR_PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }
fi

REPO_PATH="${REPO_PATH:-}"
if [[ -z "$REPO_PATH" ]]; then
    echo "Error: REPO_PATH not found in .env file"
    exit 1
fi
FULL_REPO_PATH="$SONAR_PROJECT_DIR/$REPO_PATH"

if [[ ! -d "$FULL_REPO_PATH" ]]; then
    echo "Error: Repository가 존재하지 않습니다: $FULL_REPO_PATH"
    echo "먼저 create_worktree.sh로 repository를 설정하세요"
    exit 1
fi

# ============================================
# 프로젝트 타입 감지
# ============================================
detect_project_type() {
    local dir="$1"

    if [[ -f "$dir/build.gradle" || -f "$dir/build.gradle.kts" ]]; then
        echo "gradle"
    elif [[ -f "$dir/pom.xml" ]]; then
        echo "maven"
    elif [[ -f "$dir/package.json" ]]; then
        echo "node"
    elif [[ -f "$dir/setup.py" || -f "$dir/pyproject.toml" || -f "$dir/requirements.txt" ]]; then
        echo "python"
    else
        echo "unknown"
    fi
}

PROJECT_TYPE=$(detect_project_type "$FULL_REPO_PATH")
echo "프로젝트 타입: $PROJECT_TYPE"

if [[ "$PROJECT_TYPE" == "unknown" ]]; then
    echo "Error: 프로젝트 타입을 감지할 수 없습니다"
    echo "지원 타입: Python, Gradle, Maven, Node.js"
    exit 1
fi

# ============================================
# 환경 구성
# ============================================
case "$PROJECT_TYPE" in
    python)
        VENV_DIR="${VENV_PATH:-venv}"
        FULL_VENV="$FULL_REPO_PATH/$VENV_DIR"

        echo ""
        echo "Python 테스트 환경 구성 중..."
        echo "  venv 경로: $FULL_VENV"

        if [[ -d "$FULL_VENV" ]]; then
            echo "  venv가 이미 존재합니다. 기존 환경을 사용합니다."
        else
            echo "  venv 생성 중..."
            python3 -m venv "$FULL_VENV"
            echo "  venv 생성 완료"
        fi

        # venv 활성화
        source "$FULL_VENV/bin/activate"

        # requirements.txt가 있으면 의존성 설치
        if [[ -f "$FULL_REPO_PATH/requirements.txt" ]]; then
            echo "  의존성 설치 중 (requirements.txt)..."
            pip install -r "$FULL_REPO_PATH/requirements.txt" 2>&1
        fi

        # pytest 설치 확인
        if ! command -v pytest &>/dev/null; then
            echo "  pytest 설치 중..."
            pip install pytest 2>&1
        else
            echo "  pytest 이미 설치됨"
        fi

        echo ""
        echo "Python 테스트 환경 구성 완료!"
        echo "  venv: $FULL_VENV"
        echo "  worktree에서 테스트 시 이 venv가 자동 활성화됩니다"
        ;;

    gradle)
        echo ""
        echo "Gradle 테스트 환경 구성 중..."
        (
            cd "$FULL_REPO_PATH" || exit 1
            echo "  의존성 확인 중..."
            ./gradlew dependencies 2>&1
        )
        echo ""
        echo "Gradle 테스트 환경 구성 완료!"
        ;;

    maven)
        echo ""
        echo "Maven 테스트 환경 구성 중..."
        (
            cd "$FULL_REPO_PATH" || exit 1
            echo "  의존성 확인 중..."
            mvn dependency:resolve 2>&1
        )
        echo ""
        echo "Maven 테스트 환경 구성 완료!"
        ;;

    node)
        echo ""
        echo "Node.js 테스트 환경 구성 중..."
        (
            cd "$FULL_REPO_PATH" || exit 1
            echo "  의존성 설치 중..."
            npm install 2>&1
        )
        echo ""
        echo "Node.js 테스트 환경 구성 완료!"
        ;;
esac

echo ""
echo "테스트 환경이 준비되었습니다."
echo "다음 명령으로 테스트를 실행하세요:"
echo "  ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/"
