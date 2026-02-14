# Red Flags — 에이전트 일탈 방지 규칙 (필수 준수)

> 이 문서는 sonar 워크플로우의 모든 에이전트(메인 + 서브)에 적용됩니다.
> 아래 패턴이 감지되면 **즉시 중단**하고 올바른 프로세스로 돌아가야 합니다.

---

## Iron Laws (절대 원칙)

```
1. 1이슈 = 1서브에이전트. 예외 없음.
2. 상태 전이는 순서대로만. 건너뛰기 없음.
3. 리뷰 없이 다음 단계 없음.
4. git commit, git push, gh pr create 실행 금지. 예외 없음.
5. 스프레드시트 상태 확인 없이 다음 단계 없음.
```

---

## 1. 이슈 그룹화 금지

### Red Flags — 이런 생각이 들면 STOP

- "같은 파일에 있으니 같이 처리하면 효율적"
- "동일 규칙(예: S3457)이니 묶어서 한 번에"
- "비슷한 수정이라 하나의 서브에이전트로 충분"
- "3개밖에 안 되니 굳이 3개 에이전트를 띄울 필요 없이"
- "하나의 브랜치에서 여러 이슈를 수정하면 PR이 깔끔"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "같은 파일이니 묶는 게 효율적" | 각 이슈의 리뷰/상태 추적이 불가능해진다. 1:1 매핑은 추적성을 위한 것 |
| "동일 규칙이니 같이 수정" | 동일 규칙이라도 맥락, 영향범위, 수정 방법이 다르다 |
| "에이전트 수를 줄여야 리소스 절약" | `MAX_CONCURRENT_AGENTS` 설정(기본값 5)이 이미 리소스를 관리한다 |
| "하나의 PR로 만들면 리뷰가 쉬움" | PR은 사용자가 수동으로 판단한다. 에이전트가 결정할 사항이 아님 |

---

## 2. 상태 전이 건너뛰기 금지

### 유효한 상태 전이 (이것만 허용)

```
Jira 모드:
대기 → CLAIMED → ANALYZING ⟷ REVIEW_ANALYSIS → JIRA_CREATED
                    ↓ (4회 실패)
                 BLOCKED

JIRA_CREATED → DEVELOPING ⟷ REVIEW_FIX → TESTING → DONE
                   ↓ (4회 실패)
                BLOCKED

DONE → APPROVED (승인) / BLOCKED (반려)

리포트 모드:
대기 → CLAIMED → ANALYZING ⟷ REVIEW_ANALYSIS → REPORT_CREATED
                    ↓ (4회 실패)
                 BLOCKED

REPORT_CREATED → DEVELOPING ⟷ REVIEW_FIX → TESTING → DONE
                     ↓ (4회 실패)
                  BLOCKED

DONE → APPROVED (승인) / BLOCKED (반려)
```

### 무효 전이 예시 (절대 금지)

```
CLAIMED → DONE              ← 분석/개발 전체 생략
CLAIMED → DEVELOPING        ← 분석 단계 생략
ANALYZING → JIRA_CREATED    ← REVIEW_ANALYSIS 생략
ANALYZING → DEVELOPING      ← 리뷰 + Jira/리포트 생략
DEVELOPING → DONE           ← REVIEW_FIX + TESTING 생략
REVIEW_FIX → DONE           ← TESTING 생략
```

### Red Flags — 이런 생각이 들면 STOP

- "분석이 명확하니 REVIEW_ANALYSIS를 건너뛰어도"
- "간단한 수정이라 REVIEW_FIX 없이 바로 TESTING"
- "이미 테스트 통과했으니 바로 DONE으로"
- "CLAIMED에서 바로 DEVELOPING으로 가면 빠를 텐데"
- "리뷰가 형식적이니 생략해도 결과는 같다"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "분석이 명확하니 리뷰 불필요" | 에이전트 자기 검증은 신뢰할 수 없다. 리뷰 에이전트가 독립 검증해야 함 |
| "간단한 수정이라 리뷰 생략 가능" | 간단한 수정이 사이드이펙트를 일으키는 경우가 가장 많다 |
| "이미 테스트 통과했으니 바로 DONE" | TESTING 상태는 테스트 결과를 기록하기 위해 존재한다. 보고서 없이 DONE 전환은 무효 |
| "리뷰가 형식적" | sonar-review는 독립 에이전트다. 형식이 아니라 실질 검증이다 |

---

## 3. 자동 커밋/PR 금지

### Red Flags — 이런 생각이 들면 STOP

- "검증 완료했으니 커밋해도 안전"
- "사용자 시간을 절약해주기 위해 커밋"
- "커밋 메시지도 작성했으니 자동으로 커밋하면 편리"
- "테스트 통과했으니 push해도 문제없을 것"
- "PR 설명도 다 준비됐으니 PR까지 만들어주면 좋겠다"
- "`07_final_deliverable.md`에 커밋 명령어를 적었으니 실행만 하면"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "검증 완료했으니 커밋해도 안전" | 에이전트의 검증과 사용자의 검증은 다르다. 사용자가 코드를 직접 확인해야 함 |
| "시간 절약을 위해" | 잘못된 커밋을 되돌리는 시간이 훨씬 크다 |
| "테스트 통과했으니 push 가능" | 테스트 통과 ≠ 코드 품질. 사용자의 판단 영역 |
| "PR 설명도 준비됐으니" | PR 생성은 사용자의 권한이자 책임. `07_final_deliverable.md`에 작성까지만 |

### 금지 명령어 (settings.json `permissions.deny`로 기술적 차단)

```
git commit*           ← 모든 형태의 커밋
git push*             ← 모든 형태의 푸시
gh pr create*         ← PR 생성
gh pr *               ← PR 관련 모든 조작
git worktree remove*  ← worktree 삭제
*cleanup_worktree*    ← 정리 스크립트 실행
rm -rf *              ← 재귀적 강제 삭제
git reset --hard*     ← 변경사항 폐기
git checkout .        ← 워킹 디렉토리 변경 폐기
git clean -f*         ← 추적되지 않는 파일 삭제
```

> 위 명령어는 `.claude/settings.json`의 `permissions.deny`에 등록되어 있어
> 에이전트가 실행을 시도해도 시스템 레벨에서 거부됩니다.

---

## 4. 워크플로우 조기 종료 금지

### Red Flags — 이런 생각이 들면 STOP

- "분석까지만 하고 나머지는 사용자가 알아서"
- "이 단계에서 충분한 정보를 제공했다"
- "개발 단계는 복잡하니 다음에"
- "에러가 발생했으니 여기서 멈추자"
- "JIRA_CREATED까지만 하면 된다" (develop 단계가 남아 있는 경우)

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "분석까지만 하면 충분" | DONE 또는 BLOCKED까지가 워크플로우의 범위. 중간 종료는 미완성 |
| "에러 발생했으니 중단" | 에러 시 재시도 (최대 3회, 총 4회 시도). 4회 실패 시 BLOCKED로 전환해야 함. 그냥 멈추면 안 됨 |
| "나머지는 사용자가" | 사용자의 역할은 DONE 이후 커밋/PR 생성. 워크플로우 내부는 에이전트의 책임 |
| "다음 세션에서 계속" | 서브에이전트는 상태가 보존되지 않는다. 지금 완료해야 함 |

### 올바른 종료 조건

에이전트가 종료할 수 있는 조건은 **2가지뿐**:

```
1. 상태가 DONE → 정상 완료
2. 상태가 BLOCKED → 4회 재시도 실패 후 전환
```

그 외 모든 상태에서의 종료는 **일탈**입니다.

---

## 5. 리뷰 결과 무시 금지

### Red Flags — 이런 생각이 들면 STOP

- "리뷰 FAIL이지만 suggestions가 사소해서 무시해도"
- "리뷰어가 틀렸다, 내 분석이 맞다"
- "리뷰 피드백 일부만 반영하고 진행"
- "이미 3번 재시도했으니 그냥 통과시키자"
- "FAIL이지만 실질적으로는 PASS"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "suggestions가 사소" | sonar-review가 FAIL 판정했으면 FAIL이다. suggestions를 반영하고 재시도 |
| "리뷰어가 틀렸다" | sonar-review는 SonarQube 규칙 기준으로 검증한다. 규칙이 기준이지 에이전트 판단이 아님 |
| "일부만 반영" | 부분 반영 후 재리뷰 필수. 리뷰어가 PASS 판정해야 다음 단계 |
| "3번 재시도했으니 통과" | 4회 실패 시 유일한 선택지는 BLOCKED. 임의 PASS 전환은 금지 |

---

## 6. 스프레드시트 상태 확인 생략 금지

### Red Flags — 이런 생각이 들면 STOP

- "방금 상태를 업데이트했으니 확인 불필요"
- "이전 단계에서 확인했으니 변하지 않았을 것"
- "API 응답이 성공이었으니 스프레드시트도 반영됐을 것"
- "네트워크 호출을 줄이기 위해 확인 생략"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "방금 업데이트했으니 확인 불필요" | 업데이트 ≠ 반영 확인. API 성공이어도 시트 반영은 별도 확인 필요 |
| "변하지 않았을 것" | 병렬 처리 시 다른 에이전트가 같은 시트를 수정할 수 있다 |
| "네트워크 호출 절약" | 잘못된 상태로 진행하면 전체 워크플로우를 처음부터 다시 해야 함 |

### 올바른 패턴

```
1. 상태 업데이트 API 호출
2. 업데이트 성공 확인
3. 스프레드시트에서 현재 상태 재조회 (sheets_get_issue.py)
4. 재조회 결과가 예상 상태와 일치하는지 확인
5. 일치하면 다음 단계 진행
```

---

## 7. 보고서 작성 생략 금지

### Red Flags — 이런 생각이 들면 STOP

- "코드 수정이 핵심이지, 보고서는 부수적"
- "분석 내용을 기억하고 있으니 보고서 없이 진행"
- "보고서 형식을 간소화해도 괜찮겠다"
- "이전 보고서를 복사해서 약간만 수정"

### 필수 보고서 목록

각 단계에서 해당 보고서가 생성되지 않으면 다음 단계로 전이할 수 없음:

#### Jira 모드 (`JIRA_ENABLED=true`)

| 전이 | 필수 보고서 | 생성 주체 |
|------|-----------|----------|
| ANALYZING → REVIEW_ANALYSIS | `01_analysis_report.md` | sonar-analyze |
| REVIEW_ANALYSIS 검증 완료 | `02_analysis_review.md` | sonar-review |
| REVIEW_ANALYSIS → JIRA_CREATED | `03_jira_created.md` | sonar-analyze |
| DEVELOPING → REVIEW_FIX | `04_fix_report.md` | sonar-develop |
| REVIEW_FIX 검증 완료 | `05_fix_review.md` (PASS 판정) | sonar-review |
| TESTING → DONE | `06_test_report.md` | sonar-develop |
| DONE (최종) | `07_final_deliverable.md` | sonar-develop |
| DONE (최종) | `08_cto_approval.md` | sonar-develop |

#### 리포트 모드 (`JIRA_ENABLED=false`)

| 전이 | 필수 보고서 | 생성 주체 |
|------|-----------|----------|
| ANALYZING → REVIEW_ANALYSIS | `01_analysis_report.md` | sonar-analyze |
| REVIEW_ANALYSIS 검증 완료 | `02_analysis_review.md` | sonar-review |
| REVIEW_ANALYSIS → REPORT_CREATED | `03_jira_report.md` | sonar-analyze |
| DEVELOPING → REVIEW_FIX | `04_fix_report.md` | sonar-develop |
| REVIEW_FIX 검증 완료 | `05_fix_review.md` (PASS 판정) | sonar-review |
| TESTING → DONE | `06_test_report.md` | sonar-develop |
| DONE (최종) | `07_final_deliverable.md` | sonar-develop |
| DONE (최종) | `08_cto_approval.md` | sonar-develop |

---

## 8. Worktree 삭제 금지

### Red Flags — 이런 생각이 들면 STOP

- "작업 완료했으니 정리 차원에서 worktree 삭제"
- "디스크 공간 절약을 위해"
- "깔끔하게 마무리하려면 정리해야"
- "BLOCKED 상태니 worktree가 필요 없을 것"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "정리 차원에서" | 사용자가 코드 리뷰를 위해 worktree가 필요하다. 삭제는 사용자 권한 |
| "디스크 공간 절약" | 에이전트가 판단할 사항이 아니다 |
| "BLOCKED이니 불필요" | BLOCKED 이슈도 사용자가 수동으로 재시도할 수 있다 |

---

## 9. 동시 작업 충돌 방지

### Red Flags — 이런 생각이 들면 STOP

- "다른 에이전트가 이 이슈를 처리 중인지 확인 안 해도 되겠지"
- "스프레드시트 상태가 CLAIMED인데 내가 처리해도 괜찮을 것"
- "같은 파일을 수정하지만 다른 부분이니 충돌 안 날 것"
- "이미 다른 에이전트가 시작했지만 내가 더 빨리 끝낼 수 있다"

### Rationalization Table

| 변명 | 현실 |
|------|------|
| "상태 확인은 오버헤드" | 중복 처리 후 두 에이전트의 작업이 모두 무효화되는 비용이 훨씬 크다 |
| "같은 파일이지만 다른 부분" | Git 워크트리 충돌은 줄 단위가 아니라 파일 단위로 발생할 수 있다 |
| "CLAIMED 상태인데 내 담당이 아닌 것 같다" | 스프레드시트의 담당자(ASSIGNEE) 필드를 반드시 확인. 다른 담당자의 이슈 처리 금지 |

### 올바른 패턴

```
1. 작업 시작 전 스프레드시트에서 담당자 + 상태 확인
2. 내 담당이 아닌 이슈 → 건너뛰기
3. 이미 ANALYZING/DEVELOPING 등 진행 중 상태 → 건너뛰기
4. 상태가 CLAIMED이고 내 담당인 경우에만 작업 시작
```

---

## 공통 합리화 패턴 (모든 규칙에 적용)

아래 사고 패턴은 **모든 규칙에 대한 일탈 징후**입니다:

| 패턴 | 대응 |
|------|------|
| "이번 한 번만 예외로" | 예외 없음. 한 번이 선례가 된다 |
| "시간을 절약하기 위해" | 잘못된 결과를 되돌리는 시간이 더 크다 |
| "사용자가 원할 것이다" | 사용자 의도를 추측하지 마라. 규칙을 따르라 |
| "실질적으로 같은 결과" | 프로세스가 결과만큼 중요하다. 과정을 생략하면 추적성이 사라진다 |
| "에이전트 효율을 위해" | 에이전트 효율보다 결과의 정확성이 우선이다 |
| "이전에는 괜찮았으니" | 이전 성공은 다음 성공을 보장하지 않는다 |
| "너무 엄격한 규칙" | 규칙이 엄격한 이유는 실패 경험에서 나왔기 때문이다 |

---

## 위반 시 대응 절차

```
1. 위반 징후 감지 → 즉시 STOP
2. 현재 상태 확인 (스프레드시트 재조회)
3. 마지막 유효 상태로 복귀
4. 올바른 프로세스로 재시작
5. 최대 3회 재시도 (총 4회 시도) 초과 시 → BLOCKED 전환 (임의 판단 금지)
```
