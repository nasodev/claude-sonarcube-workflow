# TDD 가이드라인 (Sonar 워크플로우)

> 이 가이드는 sonar-develop 워크플로우에서의 특성화 테스트(Characterization Test) 작성을 안내합니다.
> 참조: superpowers:test-driven-development

## 핵심 원칙

**특성화 테스트 (Characterization Test)**
- 새 기능 TDD가 아닌, 기존 동작을 캡처하는 테스트
- BEFORE: 현재 코드의 동작을 테스트로 고정 → GREEN 확인
- 코드 수정 후: 동일 테스트 재실행 → GREEN 유지 확인
- 의도적 동작 변경 시: 테스트도 함께 수정 (사유 기록)

## 테스트 파일 규약

| 언어 | 위치 | 예시 |
|------|------|------|
| Python | `tests/sonar_tdd/test_{issue_key}_{function}.py` | `test_ODIN_123_validate_email.py` |
| Java | `src/test/java/sonar/tdd/Test{IssueKey}{Function}.java` | `TestODIN123ValidateEmail.java` |

- Python: issue_key의 하이픈(-)은 언더스코어(_)로 변환
- Java: issue_key의 하이픈(-)은 제거, PascalCase 적용

## 테스트 작성 범위

1. `01_analysis_report.md`의 "해결 방안"에서 수정 대상 함수 식별
2. `01_analysis_report.md`의 "TDD 게이팅 > 대상 함수" 목록 참조
3. 해당 함수의 현재 동작을 캡처하는 최소한의 테스트
4. 엣지 케이스보다 핵심 동작 경로 우선

## 테스트 작성 절차

### 1. 대상 함수 확인

```
01_analysis_report.md → TDD 게이팅 → 대상 함수
```

### 2. 특성화 테스트 작성

현재 동작을 그대로 캡처한다. "올바른" 동작이 아니라 "현재" 동작을 테스트한다.

```python
# tests/sonar_tdd/test_ODIN_123_validate_email.py

def test_validate_email_accepts_valid_format():
    """현재 동작: 유효한 이메일을 수락"""
    result = validate_email("user@example.com")
    assert result is True

def test_validate_email_rejects_empty():
    """현재 동작: 빈 문자열을 거부"""
    result = validate_email("")
    assert result is False
```

### 3. BEFORE 실행 (GREEN 확인)

```bash
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/test_{issue_key}_{function}.py
```

- GREEN이면: 현재 동작이 정확히 캡처됨 → 코드 수정 진행
- RED이면: 테스트가 현재 동작을 잘못 캡처한 것 → 테스트 수정 (최대 3회)

### 4. 코드 수정

분석 보고서의 해결 방안에 따라 코드를 수정한다.

### 5. AFTER 실행 (GREEN 확인)

```bash
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/test_{issue_key}_{function}.py
```

- GREEN이면: 기존 동작이 보존됨 → 수정 보고서 작성
- RED이면: 코드 수정이 기존 동작을 깨뜨림 → 코드 재수정

### 6. 의도적 동작 변경 시

수정이 의도적으로 동작을 변경하는 경우:
1. 테스트의 기대값을 새 동작에 맞게 수정
2. 변경 사유를 테스트 docstring에 기록
3. fix_report.md의 TDD 결과에 "동작 변경: 있음 (사유: ...)" 기록

```python
def test_validate_email_rejects_empty():
    """변경: 빈 문자열 시 False 대신 ValueError 발생 (보안 강화)"""
    with pytest.raises(ValueError):
        validate_email("")
```

## RED/GREEN 기록

모든 테스트 실행 결과를 기록한다:

| 시점 | 기대 결과 | 실제 결과 | 비고 |
|------|-----------|-----------|------|
| BEFORE | GREEN | {PASS/FAIL} | {FAIL 시 수정 내역} |
| AFTER | GREEN | {PASS/FAIL} | {FAIL 시 수정 내역} |

## 테스트 안티패턴 (금지)

| 안티패턴 | 올바른 접근 |
|----------|------------|
| mock으로 동작 가장 | 실제 함수 호출로 캡처 |
| 구현 세부사항 테스트 | 입력/출력 동작만 테스트 |
| 너무 많은 엣지 케이스 | 핵심 경로 우선, 최소한으로 |
| 테스트에서 로직 반복 | 하드코딩된 기대값 사용 |

## 실행 환경

- 테스트는 항상 **worktree 내부**에서 실행된다
- `run_tests.sh`가 자동으로 worktree로 이동하고 테스트 환경을 구성한다
- Python: repo의 venv를 활성화 + PYTHONPATH를 worktree로 설정 후 pytest 실행 (editable install 안전)
- Java: worktree에서 빌드 도구(Gradle/Maven) 직접 실행
- 직접 pytest나 ./gradlew test를 실행하지 않는다 → 반드시 run_tests.sh 사용

## 실행 명령

```bash
# 특정 테스트 파일 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/test_{issue_key}_{function}.py

# issue의 모든 TDD 테스트 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --worktree worktrees/{issue_key} --target tests/sonar_tdd/

# repo에서 전체 테스트 실행
${CLAUDE_PLUGIN_ROOT:-$CLAUDE_PROJECT_DIR/.claude}/skills/sonar-develop/scripts/run_tests.sh --all
```

### --target 포맷 (빌드 도구별)

`--target`에 전달하는 값의 포맷은 빌드 도구마다 다르다:

| 빌드 도구 | --target 포맷 | 예시 |
|-----------|--------------|------|
| pytest (Python) | 파일/디렉토리 경로 | `tests/sonar_tdd/test_ODIN_123_validate.py` |
| Gradle (Java) | 클래스 패턴 (와일드카드 지원) | `sonar.tdd.TestODIN123*` |
| Maven (Java) | 클래스명 (쉼표 구분 가능) | `sonar.tdd.TestODIN123ValidateEmail` |
| npm (Node.js) | 테스트 러너에 전달되는 인자 | `tests/sonar_tdd/` |

> **주의**: Java 프로젝트에서는 파일 경로가 아닌 클래스 패턴을 사용해야 한다.
