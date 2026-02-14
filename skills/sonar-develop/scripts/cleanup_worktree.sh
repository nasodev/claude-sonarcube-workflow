#!/bin/bash

# Cleanup Git Worktree
# Usage: ./cleanup_worktree.sh -j JIRA-123 [--delete-branch]

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

# Repository path (from .env or default)
REPO_PATH="${REPO_PATH:-repo/odin_addsvc_extsvc-backend}"

DELETE_BRANCH=false
JIRA_KEY=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -j|--jira) JIRA_KEY="$2"; shift 2 ;;
        --delete-branch) DELETE_BRANCH=true; shift ;;
        -h|--help)
            echo "Usage: $0 -j JIRA_KEY [--delete-branch]"
            echo ""
            echo "Options:"
            echo "  -j, --jira       Jira issue key (required)"
            echo "  --delete-branch  Also delete the branch (default: keep)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$JIRA_KEY" ]]; then
    echo "Error: JIRA_KEY (-j) is required"
    exit 1
fi

WORKTREE_PATH="$WORKTREE_DIR/$JIRA_KEY"
BRANCH_NAME="fix/$JIRA_KEY"

# Check if worktree exists
if [[ ! -d "$WORKTREE_PATH" ]]; then
    echo "Worktree not found: $WORKTREE_PATH"
    exit 0
fi

FULL_REPO_PATH="$PROJECT_ROOT/$REPO_PATH"

# Check if repo exists
if [[ ! -d "$FULL_REPO_PATH" ]]; then
    echo "Error: Repository not found at $FULL_REPO_PATH"
    exit 1
fi

# Remove worktree (서브셸 격리)
echo "Removing worktree: $WORKTREE_PATH"
(
    cd "$FULL_REPO_PATH" || exit 1
    git worktree remove "$WORKTREE_PATH" --force 2>&1 || {
        echo "Error: worktree 삭제 실패"
        exit 1
    }

    if [[ "$DELETE_BRANCH" == true ]]; then
        echo "Deleting branch: $BRANCH_NAME"
        git branch -D "$BRANCH_NAME" 2>&1 || echo "Branch not found locally"
    fi
) || exit 1

echo "Cleanup complete!"
