import { useEffect, useState, type FormEvent } from "react";
import { goodsDictionaryApi } from "../../api/goods_dictionary";
import { Button } from "../../components/ui/button";

export function ClassificationSelector({
  value,
  onSelect,
}: {
  value: string;
  onSelect: (code: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState<{
    items: Array<{ classification_code: string; expression_count: number }>;
    total: number;
  }>({ items: [], total: 0 });
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    goodsDictionaryApi
      .classifications(query, page, controller.signal)
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, [query, page]);
  function submit(e: FormEvent) {
    e.preventDefault();
    if (/^[0-9]{10}$/.test(query)) onSelect(query);
  }
  return (
    <section className="dictionary-scope" aria-label="품목 선택">
      <form onSubmit={submit}>
        <label>
          품목코드 검색·직접 입력
          <input
            inputMode="numeric"
            pattern="[0-9]{10}"
            maxLength={10}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value.replace(/\D/g, ""));
              setPage(0);
            }}
            placeholder="품목코드 10자리"
          />
        </label>
        <Button size="sm" variant="outline" disabled={query.length !== 10}>
          이 품목 보기
        </Button>
      </form>
      <label>
        등록된 품목
        <select
          value={value === "all" ? "" : value}
          onChange={(e) => onSelect(e.target.value)}
        >
          <option value="">품목을 선택하세요</option>
          {value &&
            !["all", "unclassified"].includes(value) &&
            !data.items.some((r) => r.classification_code === value) && (
              <option value={value}>{value}</option>
            )}
          {data.items.map((row) => (
            <option
              key={row.classification_code}
              value={row.classification_code}
            >
              {row.classification_code} · 원문 표현 {row.expression_count}개
            </option>
          ))}
          <option value="unclassified">품목 미확인</option>
        </select>
      </label>
      <div className="dictionary-actions">
        <Button
          size="sm"
          variant="outline"
          disabled={!page}
          onClick={() => setPage((p) => p - 1)}
        >
          이전 품목
        </Button>
        <span>{data.total}개 품목</span>
        <Button
          size="sm"
          variant="outline"
          disabled={(page + 1) * 25 >= data.total}
          onClick={() => setPage((p) => p + 1)}
        >
          다음 품목
        </Button>
      </div>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
