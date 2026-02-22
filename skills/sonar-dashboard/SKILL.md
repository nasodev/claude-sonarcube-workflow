---
name: sonar-dashboard
description: 워크플로우 실행 결과를 시각화하는 HTML 대시보드를 생성합니다.
argument-hint: "[--no-sheets] [--output PATH]"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# SonarQube Workflow Dashboard Generator

SQLite 추적 DB와 Google Sheets 데이터를 기반으로 HTML 대시보드를 생성합니다.

## 사용법

사용자 인자를 그대로 스크립트에 전달합니다:

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-dashboard/scripts/generate_dashboard.py [OPTIONS]
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `--no-sheets` | Google Sheets 없이 DB 데이터만으로 생성 |
| `--output PATH` | 출력 파일 경로 지정 (기본: `reports/dashboard_{timestamp}.html`) |
| `--open` | 생성 후 브라우저에서 열기 (macOS `open` 명령) |

## 실행 절차

1. 사용자 인자를 파싱하여 스크립트 실행
2. 결과 JSON 출력을 확인
3. 성공 시 생성된 파일 경로를 사용자에게 안내

```bash
python ${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-dashboard/scripts/generate_dashboard.py $ARGUMENTS
```

## 출력

스크립트는 JSON을 stdout으로 출력합니다:

```json
{"status": "success", "output_path": "reports/dashboard_20260208_1630.html", "issues_count": 12}
```

실패 시:

```json
{"status": "failed", "error": "No tracking data found"}
```

## 의존 모듈

- `sonar-common/scripts/env_loader.py` — 환경변수 로드
- `sonar-common/scripts/tracking_db.py` — SQLite DB 접근
- `sonar-common/scripts/sheets_client.py` — Google Sheets 접근 (선택)

## 에러 처리

| 상황 | 동작 |
|------|------|
| DB 파일 없음 | `{"status":"failed","error":"..."}` 출력, exit 1 |
| DB 데이터 0건 | 빈 대시보드 + "No data" 메시지 |
| Sheets 인증/API 실패 | warning 로그, DB만으로 계속 |
| 출력 디렉토리 없음 | 자동 생성 |
| `open` 명령 실패 | warning만, 파일은 정상 생성 |
