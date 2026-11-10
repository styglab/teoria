Teoria 루트에서 실행하면 됩니다.

# 업로드할 변경 확인
bash archive/publish_kory_parser.sh

# 커밋·업로드
bash archive/publish_kory_parser.sh --push --message "Fix parser"

main이 PR 필수라면:

bash archive/publish_kory_parser.sh --push \
  --branch fix-parser --message "Fix parser"
