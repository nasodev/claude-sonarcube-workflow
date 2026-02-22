#!/bin/bash

# Cleanup Git Worktree
# Usage: ./cleanup_worktree.sh -j JIRA-123 [--delete-branch]

set -euo pipefail

# 프로젝트 디렉토리 (SONAR_PROJECT_DIR 필수)
if [[ -z "${SONAR_PROJECT_DIR:-}" ]]; then
    echo "Error: SONAR_PROJECT_DIR 환경변수가 설정되지 않았습니다"
    exit 1
fi
if [[ ! -d "$SONAR_PROJECT_DIR" ]]; then
    echo "Error: 프로젝트 디렉토리가 존재하지 않습니다: $SONAR_PROJECT_DIR"
    exit 1
fi

# 상대 경로를 절대 경로로 변환 (cd 후 git worktree remove에서 경로가 꼬이는 것 방지)
SONAR_PROJECT_DIR="$(cd "$SONAR_PROJECT_DIR" && pwd)"

WORKTREE_DIR="$SONAR_PROJECT_DIR/worktrees"

# Load .env file
ENV_FILE="$SONAR_PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    source "$ENV_FILE" 2>&1 || { echo "Error: .env 로드 실패"; exit 1; }
fi

# Repository path (from .env, required)
REPO_PATH="${REPO_PATH:-}"
if [[ -z "$REPO_PATH" ]]; then
    echo "Error: REPO_PATH not found in .env file"
    exit 1
fi

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

FULL_REPO_PATH="$SONAR_PROJECT_DIR/$REPO_PATH"

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
