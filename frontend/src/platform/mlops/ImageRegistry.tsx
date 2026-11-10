import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useServerQuery } from "../../api/server_queries";
import { SelectionCatalog } from "../../components/workspace/SelectionCatalog";
import {
  PageHeader,
  PageState,
} from "../../components/workspace/WorkspaceLayout";
import { imageRegistryApi } from "./api";

export function ImageRegistry() {
  const [params, setParams] = useSearchParams();
  const [refresh, setRefresh] = useState(0);
  const after = params.get("after") || "";
  const query = params.get("q") || "";
  const tagsAfter = params.get("tags_after") || "";
  const update = (values: Record<string, string>) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        Object.entries(values).forEach(([key, value]) =>
          value ? next.set(key, value) : next.delete(key),
        );
        return next;
      },
      { replace: true },
    );
  const status = useServerQuery(
    ["image-registry", "status"],
    (signal) => imageRegistryApi.status(signal),
    { refresh },
  );
  const repositories = useServerQuery(
    ["image-registry", "repositories", after],
    (signal) => imageRegistryApi.repositories(after, signal),
    { enabled: !!status.data?.configured, refresh },
  );
  const repository =
    params.get("repository") || repositories.data?.items[0] || "";
  const tags = useServerQuery(
    ["image-registry", "tags", repository, tagsAfter],
    (signal) => imageRegistryApi.tags(repository, tagsAfter, signal),
    { enabled: !!repository && !!status.data?.configured, refresh },
  );
  const tag = params.get("tag") || tags.data?.items[0] || "";
  const manifest = useServerQuery(
    ["image-registry", "manifest", repository, tag],
    (signal) => imageRegistryApi.manifest(repository, tag, signal),
    { enabled: !!repository && !!tag && !!status.data?.configured, refresh },
  );
  const error =
    status.error || repositories.error || tags.error || manifest.error;
  return (
    <SelectionCatalog
      title="컨테이너 이미지"
      search={query}
      onSearch={(value) => update({ q: value })}
      selected={repository}
      onSelect={(value) =>
        update({ repository: value, tag: "", tags_after: "" })
      }
      items={(repositories.data?.items || [])
        .filter((name) => name.includes(query))
        .map((name) => ({
          id: name,
          title: name,
          subtitle: status.data?.host || "",
        }))}
      footer={
        <>
          <span>페이지당 최대 25개</span>
          <div>
            <button
              disabled={!after}
              onClick={() =>
                update({ after: "", repository: "", tag: "", tags_after: "" })
              }
            >
              처음
            </button>
            <button
              disabled={!repositories.data?.next}
              onClick={() =>
                update({
                  after: repositories.data!.next!,
                  repository: "",
                  tag: "",
                  tags_after: "",
                })
              }
            >
              다음 목록
            </button>
          </div>
        </>
      }
    >
      <PageHeader
        title="컨테이너 이미지"
        description="플랫폼·학습·서빙 이미지와 고정된 버전 참조를 확인합니다."
        actions={
          <button
            className="page-icon-button"
            aria-label="이미지 새로고침"
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={16} />
          </button>
        }
      />
      {error && (
        <p role="alert" className="workspace-error">
          {error}
        </p>
      )}
      {!status.data ? (
        <PageState
          loading={!status.error}
          title="이미지 저장소를 확인하고 있습니다…"
        />
      ) : !status.data.configured ? (
        <PageState
          title="이미지 저장소가 연결되지 않았습니다"
          description="이미지 저장소 연결을 설정한 뒤 다시 조회하세요."
        />
      ) : !repositories.data ? (
        <PageState loading={!error} title="이미지를 불러오고 있습니다…" />
      ) : !repository ? (
        <PageState title="등록된 이미지가 없습니다" />
      ) : (
        <>
          <div className="operations-detail-heading">
            <div>
              <span>{status.data.host}</span>
              <h3>{repository}</h3>
            </div>
          </div>
          <section className="operations-section">
            <h4>이미지 태그</h4>
            <label>
              태그{" "}
              <select
                aria-label="이미지 태그"
                value={tag}
                onChange={(event) => update({ tag: event.target.value })}
              >
                {(tags.data?.items || []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            {tags.data && !tags.data.items.length && (
              <p>등록된 태그가 없습니다.</p>
            )}
            <div className="operations-pagination">
              <button
                disabled={!tagsAfter}
                onClick={() => update({ tags_after: "", tag: "" })}
              >
                처음 태그
              </button>
              <button
                disabled={!tags.data?.next}
                onClick={() =>
                  update({ tags_after: tags.data!.next!, tag: "" })
                }
              >
                다음 태그
              </button>
            </div>
          </section>
          {manifest.data && (
            <section className="operations-section">
              <h4>고정 버전 참조</h4>
              <dl className="operations-facts">
                <div>
                  <dt>이미지</dt>
                  <dd>
                    <code>{manifest.data.image}</code>
                  </dd>
                </div>
                <div>
                  <dt>Digest</dt>
                  <dd>
                    <code>{manifest.data.digest}</code>
                  </dd>
                </div>
                <div>
                  <dt>실행 환경</dt>
                  <dd>
                    {manifest.data.platforms
                      .map((item) =>
                        [item.os, item.architecture, item.variant]
                          .filter(Boolean)
                          .join("/"),
                      )
                      .filter(Boolean)
                      .join(", ") || "단일 이미지"}
                  </dd>
                </div>
              </dl>
              <p className="operations-note">
                태그가 변경되어도 이 참조는 같은 이미지 내용을 가리킵니다.
              </p>
            </section>
          )}
        </>
      )}
    </SelectionCatalog>
  );
}
