# Source verification cases

Source Operation별 Build/Live 검증 입력이다.

```text
registries/source/verification_cases/{source_id}/{operation_id}.yaml
```

각 파일의 자리값을 실제 테스트 데이터로 교체한 후 실행한다.

```bash
python3 -m teoria.cli verify source \
  --profile build \
  --source nts_business_registration \
  --operation get_business_registration_status \
  --input registries/source/verification_cases/nts_business_registration/get_business_registration_status.yaml
```

대표자명 등 민감한 실제 데이터는 이 디렉터리에 커밋하지 않고 `.local/verification_cases/`에 복사하여 관리한다. API 인증키는 `.env`에만 둔다.
