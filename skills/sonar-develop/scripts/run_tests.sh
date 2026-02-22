#!/bin/bash

# Run Tests in Worktree or Repo
# Usage:
#   ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/
#   ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --all
#   ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --all

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

# ============================================
# 인자 파싱
# ============================================
WORKTREE=""
TARGET=""
RUN_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --worktree) WORKTREE="$2"; shift 2 ;;
        --target) TARGET="$2"; shift 2 ;;
        --all) RUN_ALL=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--worktree <path>] [--target <test_path>] [--all]"
            echo ""
            echo "Options:"
            echo "  --worktree  Worktree 경로 (예: worktrees/ODIN-123)"
            echo "  --target    실행할 테스트 경로 (예: tests/sonar_tdd/)"
            echo "  --all       전체 테스트 실행"
            echo ""
            echo "Examples:"
            echo "  $0 --worktree worktrees/ODIN-123 --target tests/sonar_tdd/"
            echo "  $0 --worktree worktrees/ODIN-123 --all"
            echo "  $0 --all"
            exit 0
            ;;
        *) echo "Error: Unknown option: $1"; exit 1 ;;
    esac
done

# --target과 --all 동시 사용 금지
if [[ -n "$TARGET" && "$RUN_ALL" == true ]]; then
    echo "Error: --target과 --all은 동시에 사용할 수 없습니다"
    exit 1
fi

# --target이나 --all 중 하나는 필수
if [[ -z "$TARGET" && "$RUN_ALL" != true ]]; then
    echo "Error: --target 또는 --all 중 하나를 지정하세요"
    echo "Usage: $0 [--worktree <path>] [--target <test_path>] [--all]"
    exit 1
fi

# ============================================
# 실행 디렉토리 결정
# ============================================
if [[ -n "$WORKTREE" ]]; then
    WORKTREE_PATH="$SONAR_PROJECT_DIR/$WORKTREE"
    if [[ ! -d "$WORKTREE_PATH" ]]; then
        echo "Error: Worktree가 존재하지 않습니다: $WORKTREE_PATH"
        echo "먼저 create_worktree.sh로 worktree를 생성하세요"
        exit 1
    fi
    EXEC_DIR="$WORKTREE_PATH"
    echo "실행 환경: Worktree ($WORKTREE)"
else
    if [[ ! -d "$FULL_REPO_PATH" ]]; then
        echo "Error: Repository가 존재하지 않습니다: $FULL_REPO_PATH"
        exit 1
    fi
    EXEC_DIR="$FULL_REPO_PATH"
    echo "실행 환경: Repository ($REPO_PATH)"
fi

# ============================================
# 프로젝트 타입 감지
# ============================================
detect_project_type() {
    local dir="$1"

    # TEST_COMMAND가 .env에 설정되어 있으면 그대로 사용
    if [[ -n "${TEST_COMMAND:-}" ]]; then
        echo "custom"
        return
    fi

    # 자동 감지
    if [[ -f "$dir/build.gradle" || -f "$dir/build.gradle.kts" ]]; then
        echo "gradle"
    elif [[ -f "$dir/pom.xml" ]]; then
        echo "maven"
    elif [[ -f "$dir/package.json" ]]; then
        echo "node"
    elif [[ -f "$dir/setup.py" || -f "$dir/pyproject.toml" || -f "$dir/requirements.txt" ]]; then
        echo "python"
    elif [[ -f "$dir/Makefile" ]] && grep -q '^test:' "$dir/Makefile" 2>/dev/null; then
        echo "makefile"
    else
        echo "unknown"
    fi
}

PROJECT_TYPE=$(detect_project_type "$EXEC_DIR")
echo "프로젝트 타입: $PROJECT_TYPE"

if [[ "$PROJECT_TYPE" == "unknown" ]]; then
    echo "Error: 프로젝트 타입을 감지할 수 없습니다"
    echo "다음 중 하나를 수행하세요:"
    echo "  1. .env에 TEST_COMMAND를 설정 (예: TEST_COMMAND=pytest)"
    echo "  2. 프로젝트 루트에 빌드 파일을 추가 (build.gradle, pom.xml, package.json 등)"
    exit 1
fi

# ============================================
# Python venv 처리
# ============================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

activate_python_venv() {
    local venv_dir="${VENV_PATH:-}"

    # VENV_PATH 미설정 시 자동 감지
    if [[ -z "$venv_dir" ]]; then
        if [[ -d "$FULL_REPO_PATH/venv" ]]; then
            venv_dir="venv"
        elif [[ -d "$FULL_REPO_PATH/.venv" ]]; then
            venv_dir=".venv"
        fi
    fi

    # venv가 없으면 setup_test_env.sh 자동 실행
    if [[ -z "$venv_dir" ]] || [[ ! -f "$FULL_REPO_PATH/${venv_dir:-venv}/bin/activate" ]]; then
        echo "Python venv를 찾을 수 없습니다. setup_test_env.sh를 자동 실행합니다..."
        local setup_script="$SCRIPT_DIR/setup_test_env.sh"
        if [[ ! -f "$setup_script" ]]; then
            echo "Error: setup_test_env.sh를 찾을 수 없습니다: $setup_script"
            exit 1
        fi
        bash "$setup_script"

        # 재감지
        venv_dir="${VENV_PATH:-}"
        if [[ -z "$venv_dir" ]]; then
            if [[ -d "$FULL_REPO_PATH/venv" ]]; then
                venv_dir="venv"
            elif [[ -d "$FULL_REPO_PATH/.venv" ]]; then
                venv_dir=".venv"
            fi
        fi
    fi

    if [[ -z "$venv_dir" ]]; then
        echo "Error: setup_test_env.sh 실행 후에도 venv를 찾을 수 없습니다"
        exit 1
    fi

    local full_venv="$FULL_REPO_PATH/$venv_dir"

    if [[ ! -f "$full_venv/bin/activate" ]]; then
        echo "Error: venv가 유효하지 않습니다: $full_venv"
        exit 1
    fi

    echo "Python venv 활성화: $full_venv"
    source "$full_venv/bin/activate"
}

# ============================================
# 테스트 실행
# ============================================
run_test() {
    local exec_dir="$1"
    local target="${2:-}"
    local project_type="$3"

    echo ""
    echo "========================================"
    echo "테스트 실행 시작"
    echo "  디렉토리: $exec_dir"
    if [[ -n "$target" ]]; then
        echo "  대상: $target"
    else
        echo "  대상: 전체"
    fi
    echo "========================================"
    echo ""

    local exit_code=0

    case "$project_type" in
        custom)
            (
                cd "$exec_dir" || exit 1
                if [[ -n "$target" ]]; then
                    eval "$TEST_COMMAND $target"
                else
                    eval "$TEST_COMMAND"
                fi
            ) || exit_code=$?
            ;;
        python)
            activate_python_venv
            # PYTHONPATH를 worktree 루트로 강제 설정
            # editable install(pip install -e .)이 repo를 가리키더라도
            # worktree의 수정된 코드가 우선 import됨
            export PYTHONPATH="$exec_dir:${PYTHONPATH:-}"
            (
                cd "$exec_dir" || exit 1
                if [[ -n "$target" ]]; then
                    pytest "$target" -v
                else
                    pytest -v
                fi
            ) || exit_code=$?
            ;;
        gradle)
            (
                cd "$exec_dir" || exit 1
                if [[ -n "$target" ]]; then
                    ./gradlew test --tests "$target"
                else
                    ./gradlew test
                fi
            ) || exit_code=$?
            ;;
        maven)
            (
                cd "$exec_dir" || exit 1
                if [[ -n "$target" ]]; then
                    mvn test -Dtest="$target"
                else
                    mvn test
                fi
            ) || exit_code=$?
            ;;
        node)
            (
                cd "$exec_dir" || exit 1
                if [[ -n "$target" ]]; then
                    npm test -- "$target"
                else
                    npm test
                fi
            ) || exit_code=$?
            ;;
        makefile)
            (
                cd "$exec_dir" || exit 1
                make test
            ) || exit_code=$?
            ;;
    esac

    echo ""
    if [[ $exit_code -eq 0 ]]; then
        echo "테스트 결과: GREEN (PASS)"
    else
        echo "테스트 결과: RED (FAIL)"
        exit $exit_code
    fi
}

# ============================================
# 실행
# ============================================
if [[ "$RUN_ALL" == true ]]; then
    run_test "$EXEC_DIR" "" "$PROJECT_TYPE"
else
    run_test "$EXEC_DIR" "$TARGET" "$PROJECT_TYPE"
fi
