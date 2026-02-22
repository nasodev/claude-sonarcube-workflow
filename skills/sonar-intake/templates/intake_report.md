# Intake 보고서

| 항목 | 값 |
|------|-----|
| 프로젝트 | {project_key} |
| 실행일시 | {timestamp} |
| 상태 | {success / failed} |

## 수집 결과

| 항목 | 건수 |
|------|------|
| 전체 수집 | {total_fetched} |
| 신규 추가 | {issues_added} |
| 중복 스킵 | {duplicates_skipped} |

## 심각도별 분포

| 심각도 | 건수 |
|--------|------|
| BLOCKER | {건수} |
| CRITICAL | {건수} |
| MAJOR | {건수} |
| MINOR | {건수} |
| INFO | {건수} |

## 타입별 분포

| 타입 | 건수 |
|------|------|
| BUG | {건수} |
| VULNERABILITY | {건수} |
| CODE_SMELL | {건수} |

## 데이터 파일

- JSON: `data/{project_key}_{timestamp}/all_issues.json`
- CSV: `data/{project_key}_{timestamp}/*.csv`
- 스프레드시트: {SPREADSHEET_ID}
