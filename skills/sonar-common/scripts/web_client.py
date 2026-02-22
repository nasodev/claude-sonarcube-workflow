#!/usr/bin/env python3
"""
web_client.py - 웹서비스 REST API 클라이언트

urllib 표준 라이브러리만 사용하여 웹서비스와 통신합니다.

Usage (CLI):
    python web_client.py projects            # 프로젝트 목록
    python web_client.py project <id>        # 프로젝트 상세
    python web_client.py stats <id>          # 프로젝트 통계
    python web_client.py dashboard           # 대시보드

Usage (Python API):
    from web_client import get_projects, get_project_detail, bulk_create_issues, upload_results
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------

def get_base_url() -> str:
    """
    웹서비스 기본 URL을 반환합니다.

    환경변수 WEB_SERVICE_URL (기본값: http://localhost:10010)
    """
    return os.environ.get("WEB_SERVICE_URL", "http://localhost:10010").rstrip("/")


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _request(method: str, path: str, data: dict = None) -> dict:
    """
    HTTP 요청을 수행합니다.

    Args:
        method: HTTP 메서드 (GET, POST, PUT, DELETE 등).
        path: API 경로 (예: /api/projects).
        data: 요청 바디 (POST/PUT 시 JSON 직렬화).

    Returns:
        응답 JSON 딕셔너리.

    Raises:
        RuntimeError: HTTP 에러 발생 시.
    """
    url = f"{get_base_url()}{path}"

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    api_key = os.environ.get("API_AUTH_KEY")
    if api_key:
        req.add_header("X-API-Key", api_key)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(
            f"HTTP {e.code} {method} {url}: {error_body or e.reason}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Connection error {method} {url}: {e.reason}"
        ) from e


# ---------------------------------------------------------------------------
# Projects API
# ---------------------------------------------------------------------------

def get_projects() -> list:
    """GET /api/projects - 프로젝트 목록을 반환합니다."""
    return _request("GET", "/api/projects")


def get_project_detail(project_id: int) -> dict:
    """GET /api/projects/{id}/detail - 프로젝트 상세 정보를 반환합니다."""
    return _request("GET", f"/api/projects/{project_id}/detail")


def get_project_stats(project_id: int) -> dict:
    """GET /api/projects/{id}/stats - 프로젝트 통계를 반환합니다."""
    return _request("GET", f"/api/projects/{project_id}/stats")


# ---------------------------------------------------------------------------
# Issues API
# ---------------------------------------------------------------------------

def bulk_create_issues(project_id: int, issues: list) -> dict:
    """
    POST /api/projects/{id}/issues/bulk - 이슈 일괄 등록.

    Args:
        project_id: 프로젝트 ID.
        issues: 이슈 딕셔너리 리스트.

    Returns:
        응답 결과.
    """
    return _request("POST", f"/api/projects/{project_id}/issues/bulk", {"issues": issues})


def get_issues(project_id: int, **filters) -> list:
    """
    GET /api/projects/{id}/issues - 이슈 목록 조회.

    Args:
        project_id: 프로젝트 ID.
        **filters: 쿼리 파라미터 (status, group_id 등).

    Returns:
        이슈 리스트.
    """
    query = ""
    if filters:
        params = {k: v for k, v in filters.items() if v is not None}
        if params:
            query = "?" + urllib.parse.urlencode(params)
    return _request("GET", f"/api/projects/{project_id}/issues{query}")


# ---------------------------------------------------------------------------
# Groups API
# ---------------------------------------------------------------------------

def create_group(project_id: int, name: str, rule: str = None, description: str = None) -> dict:
    """
    POST /api/projects/{id}/groups - 그룹 생성.

    Args:
        project_id: 프로젝트 ID.
        name: 그룹 이름.
        rule: SonarQube 규칙 ID.
        description: 그룹 설명.

    Returns:
        생성된 그룹 정보.
    """
    payload = {"name": name}
    if rule is not None:
        payload["rule"] = rule
    if description is not None:
        payload["description"] = description
    return _request("POST", f"/api/projects/{project_id}/groups", payload)


def get_groups(project_id: int) -> list:
    """GET /api/projects/{id}/groups - 그룹 목록을 반환합니다."""
    return _request("GET", f"/api/projects/{project_id}/groups")


# ---------------------------------------------------------------------------
# Sync API
# ---------------------------------------------------------------------------

def upload_results(project_id: int, issues: list, assignee: str, batch_size: int = 1000) -> dict:
    """
    POST /api/projects/{id}/sync/upload - 변경된 이슈를 웹서비스에 업로드.

    대량 이슈는 batch_size 단위로 나누어 전송합니다 (HTTP 413 방지).

    Args:
        project_id: 프로젝트 ID.
        issues: [{"sonarqube_key": ..., "status": ..., "jira_key": ...}, ...]
        assignee: 담당자 이름 (ASSIGNEE_NAME).
        batch_size: 배치당 이슈 수 (기본값: 1000).

    Returns:
        업로드 결과 {"success": [...], "failed": [...]}.
    """
    all_success = []
    all_failed = []

    for i in range(0, len(issues), batch_size):
        batch = issues[i:i + batch_size]
        result = _request("POST", f"/api/projects/{project_id}/results/upload", {
            "assignee": assignee,
            "items": batch,
        })
        all_success.extend(result.get("success_keys", []))
        all_failed.extend(result.get("errors", []))

    return {"success": all_success, "failed": all_failed}


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

def get_dashboard() -> dict:
    """GET /api/dashboard - 대시보드 정보를 반환합니다."""
    return _request("GET", "/api/dashboard")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_json(data):
    """데이터를 포맷된 JSON으로 출력합니다."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    if len(sys.argv) < 2:
        print("Usage: python web_client.py {projects|project <id>|stats <id>|dashboard}")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "projects":
            _print_json(get_projects())

        elif command == "project":
            if len(sys.argv) < 3:
                print("Usage: python web_client.py project <id>")
                sys.exit(1)
            _print_json(get_project_detail(int(sys.argv[2])))

        elif command == "stats":
            if len(sys.argv) < 3:
                print("Usage: python web_client.py stats <id>")
                sys.exit(1)
            _print_json(get_project_stats(int(sys.argv[2])))

        elif command == "dashboard":
            _print_json(get_dashboard())

        else:
            print(f"Unknown command: {command}")
            print("Usage: python web_client.py {projects|project <id>|stats <id>|dashboard}")
            sys.exit(1)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
