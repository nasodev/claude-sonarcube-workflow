# 분석 보고서

| 항목 | 값 |
|------|-----|
| Issue Key | {SonarQube키} |
| 담당자 | {이름} |
| 상태 | ANALYZING |
| 생성일시 | {timestamp} |
| 시도 횟수 | {attempt_analysis} |

## 문제 요약

{SonarQube 메시지 및 규칙 설명}

## 원인 분석

{코드 분석 결과}

## 영향범위

- 영향받는 모듈:
- 런타임 영향:
- 보안 영향:

## 해결 방안

### Option A (권장)
{설명}

### Option B
{설명}

## 리스크

{주의사항}

## 검증 계획

{테스트 방법}

## TDD 게이팅

| 항목 | 값 |
|------|-----|
| 판정 | {TDD_REQUIRED / TDD_SKIP} |
| 사유 | {구체적 판정 근거} |
| 대상 함수 | {TDD 필수 시: 테스트 대상 함수 목록 / TDD 스킵 시: N/A} |

### 판정 기준 참고

**TDD_REQUIRED 조건 (하나라도 해당):**
- 타입이 BUG 또는 VULNERABILITY
- 품질이 SECURITY 또는 RELIABILITY
- 수정이 함수 시그니처/반환값/동작을 변경
- 큰 리팩터링 (영향 함수 3개 이상)
- 기존 테스트가 없는 영역

**TDD_SKIP 조건 (모두 해당):**
- 타입이 CODE_SMELL이고 심각도 MINOR/INFO
- 변수명/메서드명 변경만 필요
- 주석/문서/로깅만 변경
- 사용하지 않는 import 제거
- 단순 코드 포맷팅