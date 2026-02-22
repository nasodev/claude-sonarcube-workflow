# [{issue_key}] 개발완료 보고서

> CTO 승인 요청용 — 코드 수정 및 검증 완료 후 커밋/PR 전 최종 승인 단계

| 항목 | 값 |
|------|-----|
| Issue Key | {JIRA-KEY 또는 SonarQube키} |
| SonarQube 규칙 | {규칙 ID} |
| 심각도 / 타입 | {심각도} / {타입} |
| 담당자 | {이름} |
| 작업 브랜치 | `fix/{issue_key}` |
| Worktree | `worktrees/{issue_key}` |
| 승인 요청일 | {timestamp} |

---

## 1. 작업 개요

- **SonarQube 이슈**: {메시지 한 줄 요약}
- **원인**: {원인 분석 요약 (01_analysis_report 기반)}
- **해결 방안**: {적용한 해결 방안 (Option A/B 중 선택한 것)}

## 2. 변경 사항

### 2.1 변경 파일 목록

| 파일 경로 | 변경 유형 | 설명 |
|----------|----------|------|
| {파일1} | {수정/신규/삭제} | {변경 내용} |
| {파일2} | {수정/신규/삭제} | {변경 내용} |

### 2.2 변경 요약

{무엇을 왜 바꾸었는지 간결하게 서술}

## 3. 검증 결과

### 3.1 자동 검증

| # | 검증 항목 | 결과 | 비고 |
|---|----------|------|------|
| 1 | lint 통과 | {PASS / FAIL} | |
| 2 | build 통과 | {PASS / FAIL} | |
| 3 | unit test 통과 | {PASS / FAIL} | |
| 4 | SonarQube 규칙 준수 | {PASS / FAIL} | {규칙 ID} 위반 해소 확인 |
| 5 | 사이드이펙트 없음 | {PASS / FAIL} | |

### 3.2 TDD 검증

| 항목 | 값 |
|------|-----|
| TDD 적용 | {Yes / No (스킵 사유)} |
| 테스트 파일 | {tests/sonar_tdd/test_{...}.py / N/A} |
| BEFORE 결과 | {GREEN / N/A} |
| AFTER 결과 | {GREEN / N/A} |
| 동작 변경 | {없음 / 있음 (사유)} |

### 3.3 리뷰 검증

| 리뷰 단계 | 판정 | 시도 횟수 |
|----------|------|----------|
| 분석 리뷰 (02) | {PASS} | {N회} |
| 수정 리뷰 (05) | {PASS} | {N회} |

## 4. 리스크 평가

| 항목 | 평가 |
|------|------|
| 영향범위 | {영향받는 모듈/기능} |
| 회귀 위험 | {낮음 / 보통 / 높음} — {근거} |
| 롤백 난이도 | {낮음 / 보통 / 높음} — {근거} |

## 5. 참고 자료

| 보고서 | 경로 |
|--------|------|
| 분석 보고서 | `reports/{issue_key}/01_analysis_report.md` |
| 분석 리뷰 | `reports/{issue_key}/02_analysis_review.md` |
| Jira 생성/리포트 | `reports/{issue_key}/03_jira_created.md` 또는 `03_jira_report.md` |
| 수정 보고서 | `reports/{issue_key}/04_fix_report.md` |
| 수정 리뷰 | `reports/{issue_key}/05_fix_review.md` |
| 테스트 보고서 | `reports/{issue_key}/06_test_report.md` |
| 최종 산출물 | `reports/{issue_key}/07_final_deliverable.md` |

---

## 승인 요청

위 검증을 모두 통과하였으며, 커밋 및 PR 생성을 위한 CTO 승인을 요청합니다.

- 커밋 메시지: `07_final_deliverable.md` 참조
- PR 설명: `07_final_deliverable.md` 참조

| 승인 | 값 |
|------|-----|
| 승인자 | |
| 승인일시 | |
| 승인 의견 | |
