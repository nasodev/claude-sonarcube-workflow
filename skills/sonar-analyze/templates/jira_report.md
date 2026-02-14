# Jira 리포트

> 이 문서는 Jira 티켓 대신 생성된 리포트입니다. (`JIRA_ENABLED=false`)

| 항목 | 값 |
|------|-----|
| SonarQube Key | {SonarQube키} |
| 프로젝트 | {PROJECT_KEY} |
| 담당자 | {이름} |
| 상태 | REPORT_CREATED |
| 생성일시 | {timestamp} |

---

## [BUG] {제목}

### 요약

{SonarQube 메시지 한 줄 요약}

### 설명

#### 문제 상황
{SonarQube 규칙 설명 및 발생 위치}

- **파일**: `{파일경로}`
- **라인**: {라인번호}
- **심각도**: {심각도}
- **규칙**: {규칙 ID}

#### 영향범위
{영향받는 모듈 및 기능}

#### 원인 분석
{코드 분석 결과}

### 해결 방안

#### Option A (권장)
{설명}

#### Option B
{설명}

### 수용 기준 (Acceptance Criteria)

- [ ] SonarQube 규칙 위반 해소
- [ ] 기존 테스트 통과
- [ ] 사이드이펙트 없음

### 참고 자료

- 분석 보고서: `reports/{issue_key}/01_analysis_report.md`
- SonarQube 규칙: {규칙 URL}

---

## 라벨

- `sonarqube`
- `{심각도}`
- `{타입}`

## 우선순위

{심각도에 따른 우선순위}

---

*이 리포트는 실제 Jira 티켓을 생성하지 않고, 동일한 형식의 문서로 작성되었습니다.*
