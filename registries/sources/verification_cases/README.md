# Source verification cases

Source Operation별 Build/Live 검증 입력이다.

```text
registries/sources/verification_cases/{source_id}/{operation_id}.yaml
```

각 파일의 자리값을 실제 테스트 데이터로 교체한 후 실행한다.

```bash
teoria verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/sources/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

`--profile build`는 네트워크를 사용하지 않고 요청 생성까지만 확인한다. 실제 API와 응답 계약을 확인할 때는 `--profile live`로 바꾼다.

대표자명 등 민감한 실제 데이터는 이 디렉터리에 커밋하지 않고 `.local/verification_cases/`에 복사하여 관리한다. API 인증키는 로컬 `.env` 또는 배포 secret에만 둔다.
