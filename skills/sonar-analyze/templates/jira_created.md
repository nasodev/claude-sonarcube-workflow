# Jira 생성 결과

| 항목 | 값 |
|------|-----|
| SonarQube Key | {SonarQube키} |
| Jira Key | {JIRA-KEY} |
| 담당자 | {이름} |
| 상태 | JIRA_CREATED |
| 생성일시 | {timestamp} |

## 생성된 Jira 티켓

- **프로젝트**: {PROJECT_KEY}
- **제목**: {Jira 제목}
- **우선순위**: {우선순위}
- **라벨**: `sonarqube`, `{심각도}`, `{타입}`

## 매핑 정보

| SonarQube | Jira |
|-----------|------|
| 이슈 키 | {SonarQube키} → {JIRA-KEY} |
| 심각도 | {심각도} → {Jira 우선순위} |
| 타입 | {타입} → {Jira 이슈 타입} |

## 관련 보고서

- 분석 보고서: `reports/{issue_key}/01_analysis_report.md`
- 분석 리뷰: `reports/{issue_key}/02_analysis_review.md`
