# Ontology source profile — 2026-10-06

이 보고서는 운영 Teoria Data DB를 읽기 전용으로 측정한 결과다. 새 shared
operational ontology의 cardinality와 optionality를 결정하는 baseline이며 데이터
품질 보증서가 아니다.

재실행 명령:

```bash
docker exec teoria-admin-api-1 \
  teoria profile-ontology-sources --deep --statement-timeout-ms 30000
```

Admin profile은 최소권한 때문에 `ingestion` raw schema를 읽지 않는다. raw
provenance 집계는 Pipeline 소유 권한으로 별도 확인했다.

## 모집단

| 대상 | 행 수 |
|---|---:|
| 공고 | 2,915,745 |
| 낙찰 | 1,522,428 |
| 개찰 참여 | 4,628,795 |
| 계약 snapshot | 12,149,096 |
| 계약업체 관계 행 | 12,772,675 |

`contracts`는 현재 snapshot 테이블이다. 이 수를 원계약 사건 수 또는 계약 버전
수라고 단정할 수 없다.

## 주요 측정 결과

### 공고 분류

| 항목 | 수 | 비율 |
|---|---:|---:|
| 공식 분류 있음 | 1,143,653 | 39.22% |
| 미분류 | 1,772,092 | 60.78% |

`ProcurementClassification` Link는 optional이어야 한다. 미분류를 제목으로 채우지
않고 명시적 `unclassified` 상태로 보존해야 한다.

### 공고 계보

| 항목 | 수 |
|---|---:|
| 재공고 | 189,580 |
| 이전 공고번호 보유 | 189,580 |
| 계보 root 보유 | 189,580 |

현재 수집된 재공고는 모두 이전/root 정보를 갖는다. `ProcurementCase`와
`BidNotice.SUPERSEDES`를 source-confirmed Link로 구성할 근거가 충분하다. 다만
원천 참조가 없는 과거 데이터까지 같은 완전성을 가정하지 않는다.

### 낙찰·참여 연결

| 항목 | 전체 | 식별/연결 | 누락 |
|---|---:|---:|---:|
| 낙찰업체 사업자번호 | 1,522,428 | 1,522,428 | 0 |
| 낙찰 -> 공고 | 1,522,428 | 1,522,422 | 6 |
| 참여업체 사업자번호 | 4,628,795 | 4,628,795 | 0 |
| 참여 -> 공고 | 4,628,795 | 4,628,760 | 35 |

`AwardRecipient`와 `BidParticipation -> BusinessRegistration`은 현재 데이터에서
강한 식별 기반을 가진다. 연결 실패 행은 삭제하지 않고 orphan provenance로
유지해야 한다.

### 계약 구조

| 항목 | 수 | 비율 |
|---|---:|---:|
| 계약 snapshot | 12,149,096 | 100% |
| 공고번호 보유 계약 | 4,643,538 | 38.22% |
| 보유 공고번호가 현재 공고 테이블에 연결 | 1,337,033 | 공고번호 보유 계약의 28.79% |
| 공식 분류 있음 | 9,943,164 | 81.84% |
| 공동계약 표시 | 273,036 | 2.25% |

계약은 공고·낙찰 없이 존재할 수 있도록 모델링해야 한다. `Contract ->
ProcurementCase`와 `Award -> Contract`는 required Link가 될 수 없다. 공고번호가
있지만 연결되지 않는 원인은 과거 공고 미수집, 번호 정규화, 다른 조달시스템 또는
원천 오류로 나누어 추가 조사해야 한다.

### 계약업체 관계

| 항목 | 수 | 비율 |
|---|---:|---:|
| 계약업체 관계 행 | 12,772,675 | 100% |
| 업체 사업자번호 식별 | 12,772,675 | 100% |
| 지분율 확인 | 8,455,310 | 66.20% |
| 지분율 미확인 | 4,317,365 | 33.80% |
| 업체 관계가 하나 이상 있는 계약 | 12,149,096 | 계약 snapshot 100% |

`ContractParty`는 필수 객체지만 `sharePercent`는 optional이다. 미확인 지분을 100%
또는 균등분배로 원천 사실처럼 저장해서는 안 된다. 계산 정책이 균등배분을 사용할
경우 derived attribution과 completeness를 별도로 반환해야 한다.

## Raw provenance

Pipeline 권한으로 확인한 raw 저장 현황:

| 항목 | 수 |
|---|---:|
| raw observations | 16,656,521 |
| raw payloads | 11,845,537 |
| PPS 공고 payloads | 3,433,121 |
| PPS 계약 payloads | 8,409,500 |
| PPS 업종 payloads | 2,916 |

현재 Admin read role이 `ingestion` schema에 접근하지 못하는 것은 올바른 권한
분리다. provenance coverage 검사는 Platform 권한을 넓히지 말고 Pipeline 검증
명령으로 제공해야 한다. 또한 현재 payload connector별 집계에는 낙찰 connector가
나타나지 않으므로 낙찰 raw 보존 경로를 별도로 점검해야 한다.

## 측정하지 못한 항목

### 사업자번호 ↔ 법인번호 연결률

Procurement Data DB에는 통합 identity assertion store가 없다. FSC 조회 결과를
Capability 실행 시 조합할 수는 있지만 confirmed/candidate/rejected 연결 상태를
지속적으로 집계할 수 없다. 새 `IdentityAssertion` support model이 필요하다.

### 계약 버전

현재 `contracts`는 unified contract number당 한 행의 snapshot이다. 원계약,
변경계약, 차수계약의 전체 history와 기준일별 상태를 재구성할 수 없다.
`ContractVersion` Ontology를 publish하기 전에 raw 계약 payload를 이용한 version
projection이 Data DB에 필요하다.

### 업체명 충돌

전체 계약·낙찰·참여 이름을 정규화해 비교하는 심층 쿼리는 30초 제한시간을
초과했다. 운영 OLTP DB에서 반복 실행하지 않고 별도 profiling view/materialized
sample 또는 Pipeline batch로 옮겨야 한다. 업체명은 어떤 경우에도 identity key로
사용하지 않는다.

## Ontology 결정에 미치는 영향

1. `BusinessRegistration`은 조달 참여·낙찰·계약에서 직접 확인되는 identity이고,
   사용자 관점의 업체는 상위 `BusinessEntity`다.
2. `ProcurementCase`와 공고 계보 Link는 source-confirmed 관계부터 생성한다.
3. `BidNotice -> Award`와 `BidParticipation -> BidNotice`는 거의 완전하지만 optional
   orphan을 허용한다.
4. `Contract`는 공고/낙찰과 독립적으로 존재할 수 있어야 한다.
5. `ContractParty.sharePercent`는 optional이며 completeness를 함께 관리한다.
6. `ContractVersion`은 현재 snapshot을 그대로 Ontology에 옮겨서는 안 된다.
7. 공식 분야 Link는 optional이고 미분류를 정상 상태로 취급한다.
8. identity resolution과 provenance는 별도 support model이 필요하다.

## 다음 데이터 작업

1. Pipeline에 raw-to-canonical provenance coverage 검사를 추가한다.
2. PPS 낙찰 raw payload 보존 경로를 확인한다.
3. 계약 version projection을 설계한다.
4. 업체명·기관명 충돌 분석은 batch profiling으로 실행한다.
5. 사업자번호-법인번호 `IdentityAssertion` 저장 모델을 설계한다.
6. 이 작업 이후 shared operational ontology Draft를 생성한다.
