---
name: sonar-review
description: 분석 보고서 또는 수정 코드를 검증합니다. sonar 스킬에서 내부적으로 호출됨.
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Read, Write, Grep, Glob
---

# SonarQube Review Agent

분석 보고서 또는 수정된 코드를 검증하고 PASS/FAIL 판정을 내립니다.

> **에이전트 일탈 방지**: @guides/red-flags.md

## Data Contract

### Input

| 인자 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `$ARGUMENTS[0]` | string | 필수 | review_type — `"analysis"` 또는 `"fix"` |
| `$ARGUMENTS[1]` | string | 필수 | report_path — 검증할 보고서 파일 경로 |
| `$ARGUMENTS[2]` | JSON string | 필수 | issue_data — 이슈 정보 (실제 코드 대조용) |

**issue_data 필수 필드:**

| 필드 | 용도 |
|------|------|
| `file_path` | 실제 소스 코드 대조 (보고서 내용 검증) |
| `line` | 실제 소스 코드 대조 (보고서 내용 검증) |
| `rule` | SonarQube 규칙 기준으로 검증 |
| `message` | 문제 요약과 일치하는지 확인 |

### 읽기 의존 파일

| review_type | 읽는 파일 | 생성 주체 |
|-------------|----------|----------|
| `"analysis"` | `report_path` (= `01_analysis_report.md`) | sonar-analyze |
| `"fix"` | `report_path` (= `04_fix_report.md`) | sonar-develop |
| `"fix"` | `01_analysis_report.md` (같은 reports 폴더) | sonar-analyze |

> **주의**: 소스 코드 파일(`issue_data.file_path`)도 직접 Read/Grep/Glob으로 열어서 보고서 내용과 대조해야 합니다.

### Output

```json
{
  "verdict": "PASS | FAIL",
  "reason": "검증 결과 설명",
  "suggestions": ["개선 제안 1", "개선 제안 2"]
}
```

**verdict 제약:**
- `"PASS"` 또는 `"FAIL"`만 허용 — 다른 값 사용 금지
- FAIL 시 `suggestions`는 1개 이상 필수 — 빈 배열 금지
- PASS 시 `suggestions`는 빈 배열 허용

### 생성 파일

| review_type | 생성 파일 | 소비자 |
|-------------|----------|--------|
| `"analysis"` | `{report_path의 부모 디렉토리}/02_analysis_review.md` | sonar-analyze (결과 확인) |
| `"fix"` | `{report_path의 부모 디렉토리}/05_fix_review.md` | sonar-develop (결과 확인) |

> **출력 경로 규칙**: 리뷰 파일은 항상 입력 `report_path`의 부모 디렉토리에 생성합니다. 개별 이슈: `reports/{issue_key}/`, 그룹 이슈: `reports/group-<name>/`.

### 로컬 DB 변경

없음. 상태 업데이트는 호출 스킬이 수행합니다.

## 검증 기준

### Analysis Review

1. 문제 요약이 SonarQube 규칙과 일치하는가
2. 원인 분석이 코드와 일치하는가
3. 해결 방안이 실현 가능한가
4. 영향범위가 정확한가

### Fix Review

1. 변경이 분석 보고서의 해결 방안과 일치하는가
2. 코드가 SonarQube 규칙을 준수하는가
3. 사이드이펙트가 없는가
4. 테스트가 적절한가

## 템플릿

- [templates/analysis_review.md](templates/analysis_review.md) - 분석 리뷰 (02_analysis_review.md)
- [templates/fix_review.md](templates/fix_review.md) - 수정 리뷰 (05_fix_review.md)

> **필수**: 리뷰 문서 작성 시 반드시 위 템플릿을 사용하세요. 템플릿의 모든 섹션을 빠짐없이 채워야 합니다.

## 재시도 지원

FAIL 판정 시 `suggestions`를 참고하여 호출 스킬이 재시도합니다.
최대 3회 재시도 (총 4회 시도) 후 BLOCKED 처리됩니다.
