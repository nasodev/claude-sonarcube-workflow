#!/bin/bash

# Create Git Worktree for Jira Issue
# Usage: ./create_worktree.sh -j JIRA-123 [-b base_branch]

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

WORKTREE_DIR="$PROJECT_ROOT/worktrees"

# Load .env file
ENV_FILE="$PROJECT_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
    source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }
fi

# Repository settings (from .env or defaults)
REPO_PATH="${REPO_PATH:-repo/odin_addsvc_extsvc-backend}"
REPO_URL="${REPO_URL:-}"
REPO_BRANCH="${REPO_BRANCH:-main}"

# Default values
BASE_BRANCH="${REPO_BRANCH}"
JIRA_KEY=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -j|--jira) JIRA_KEY="$2"; shift 2 ;;
        -b|--base) BASE_BRANCH="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 -j JIRA_KEY [-b base_branch]"
            echo ""
            echo "Options:"
            echo "  -j, --jira   Jira issue key (required)"
            echo "  -b, --base   Base branch (default: $REPO_BRANCH from .env)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$JIRA_KEY" ]]; then
    echo "Error: JIRA_KEY (-j) is required"
    exit 1
fi

FULL_REPO_PATH="$PROJECT_ROOT/$REPO_PATH"

# ============================================
# Step 1: Clone repository if not exists
# ============================================
if [[ ! -d "$FULL_REPO_PATH" ]]; then
    if [[ -z "$REPO_URL" ]]; then
        echo "Error: Repository not found at $FULL_REPO_PATH"
        echo "Set REPO_URL in .env to enable auto-clone"
        exit 1
    fi

    echo "Repository not found. Cloning from $REPO_URL..."
    mkdir -p "$(dirname "$FULL_REPO_PATH")"
    git clone -b "$REPO_BRANCH" "$REPO_URL" "$FULL_REPO_PATH" 2>&1
    echo "Clone complete!"
fi

# ============================================
# Step 2: Ensure correct branch and update (서브셸 격리)
# ============================================
(
    cd "$FULL_REPO_PATH" || exit 1

    CURRENT_BRANCH=$(git branch --show-current)

    echo "Fetching latest changes..."
    git fetch origin 2>&1 || { echo "Error: git fetch 실패"; exit 1; }

    if [[ "$CURRENT_BRANCH" != "$BASE_BRANCH" ]]; then
        echo "Switching to $BASE_BRANCH branch..."
        git checkout "$BASE_BRANCH" 2>&1 || { echo "Error: git checkout 실패"; exit 1; }
    fi

    LOCAL_COMMIT=$(git rev-parse HEAD)
    REMOTE_COMMIT=$(git rev-parse "origin/$BASE_BRANCH")

    if [[ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]]; then
        echo "Local branch is not up to date. Pulling latest changes..."
        git pull origin "$BASE_BRANCH" 2>&1 || { echo "Error: git pull 실패"; exit 1; }
        echo "Pull complete!"
    else
        echo "Branch $BASE_BRANCH is up to date."
    fi
) || exit 1

# ============================================
# Step 3: Create worktree (서브셸 격리)
# ============================================
mkdir -p "$WORKTREE_DIR"

WORKTREE_PATH="$WORKTREE_DIR/$JIRA_KEY"
BRANCH_NAME="fix/$JIRA_KEY"

if [[ -d "$WORKTREE_PATH" ]]; then
    echo "Worktree already exists: $WORKTREE_PATH"
    echo "Branch: $BRANCH_NAME"
    exit 0
fi

echo ""
echo "Creating worktree..."
echo "  Path: $WORKTREE_PATH"
echo "  Branch: $BRANCH_NAME"
echo "  Base: origin/$BASE_BRANCH"

(
    cd "$FULL_REPO_PATH" || exit 1
    git worktree add -b "$BRANCH_NAME" "$WORKTREE_PATH" "origin/$BASE_BRANCH" 2>&1 || {
        echo "Error: worktree 생성 실패"
        exit 1
    }
) || exit 1

echo ""
echo "Worktree created successfully!"
echo "  cd $WORKTREE_PATH"
