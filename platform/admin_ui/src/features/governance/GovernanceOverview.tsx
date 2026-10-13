import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { adminApi, type MetadataEntity } from "../../api/admin";

type Coverage = { total: number; missingDescription: number; missingOwner: number; missingTags: number };

export function GovernanceOverview() {
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      const assets: MetadataEntity[] = [];
      const visited = new Set<string>();
      let after: string | undefined;
      do {
        const page = await adminApi.metadataTables({ limit: 100, after });
        if (!active) return;
        assets.push(...page.items);
        after = page.after || undefined;
        if (after) {
          if (visited.has(after)) throw new Error("자산 페이지가 반복됩니다.");
          visited.add(after);
        }
      } while (after);
      const unique = [...new Map(assets.map((asset) => [asset.reference.entity_id, asset])).values()];
      if (active) setCoverage({
        total: unique.length,
        missingDescription: unique.filter((asset) => !asset.description?.trim()).length,
        missingOwner: unique.filter((asset) => !asset.owners.length).length,
        missingTags: unique.filter((asset) => !asset.tags.length).length,
      });
    };
    load().catch((reason: Error) => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, []);

  return <div className="workspace-page governance-page">
    <header className="workspace-page-header"><div><h2>메타데이터 공백</h2><p>현재 데이터 자산에서 설명·소유자·분류가 필요한 항목을 확인합니다.</p></div></header>
    {error && <p role="alert" className="workspace-error">거버넌스 현황 조회 실패: {error}</p>}
    <div className="overview-grid">
      <Link className="overview-stat" to="/admin/data-catalog"><span>전체 자산</span><strong>{coverage?.total ?? "—"}</strong><small>OpenMetadata 테이블</small></Link>
      <Link className="overview-stat" to="/admin/data-catalog?filter=description"><span>설명 없음</span><strong>{coverage?.missingDescription ?? "—"}</strong><small>설명 보강 대상</small></Link>
      <Link className="overview-stat" to="/admin/data-catalog?filter=owner"><span>소유자 미지정</span><strong>{coverage?.missingOwner ?? "—"}</strong><small>책임 지정 대상</small></Link>
      <Link className="overview-stat" to="/admin/data-catalog?filter=tags"><span>태그·용어 없음</span><strong>{coverage?.missingTags ?? "—"}</strong><small>분류와 의미 검토 대상</small></Link>
    </div>
    <div className="overview-columns">
      <section className="workspace-card"><h3>분류와 책임</h3><p>소유자·도메인·태그·Glossary Term의 권위 원천은 OpenMetadata입니다.</p><Link to="/admin/data-catalog?filter=owner"><strong>소유자 공백 확인</strong><span>자산별 담당 책임을 확인합니다.</span></Link><Link to="/admin/data-catalog?filter=tags"><strong>분류 공백 확인</strong><span>태그와 업무 용어가 없는 자산을 확인합니다.</span></Link></section>
      <section className="workspace-card"><h3>의미와 변경 통제</h3><p>온톨로지와 의미 연결은 Teoria에서 관리하며, AI 결과는 승인 전까지 제안입니다.</p><Link to="/admin/semantic-model/bindings"><strong>의미 연결 관리</strong><span>자산·용어와 업무 개념의 연결 상태를 확인합니다.</span></Link><Link to="/admin/changes/review"><strong>변경 제안 검토</strong><span>근거와 적용 효과를 검토한 뒤 승인합니다.</span></Link></section>
    </div>
  </div>;
}
