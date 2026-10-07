import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Braces, Check, ChevronRight, CircleDashed, Database, GitFork, Search, ShieldCheck, Workflow } from "lucide-react";
import { adminApi, type CapabilityCoverage, type CapabilitySummary, type LineageLink, type MappingSummary, type SourceSummary, type ValidationReport } from "../../api/admin";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Progress } from "../../components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../components/ui/tabs";

type Props = { capabilities: CapabilitySummary[]; sources: SourceSummary[]; mappings: MappingSummary[]; lineage: LineageLink[]; validation: ValidationReport | null; onOpenBindings?: () => void };
type Readiness = { label: string; value: number; state: "ready" | "attention" | "blocked"; detail: string };

function shortId(value: string) { return value.split(".").at(-1) ?? value; }

function ReadinessCard({ item }: { item: Readiness }) {
  const Icon = item.state === "ready" ? Check : item.state === "blocked" ? AlertTriangle : CircleDashed;
  return <Card className={`readiness-card ${item.state}`}><CardHeader><div className="readiness-title"><span><Icon size={14} />{item.label}</span><strong>{item.value}%</strong></div></CardHeader><CardContent><Progress value={item.value} /><CardDescription>{item.detail}</CardDescription></CardContent></Card>;
}

function ContractList({ label, items, empty }: { label: string; items: string[]; empty: string }) {
  return <section className="contract-list"><h4>{label}<Badge variant="outline">{items.length}</Badge></h4>{items.length ? items.map((item) => <div key={item}><code>{item}</code></div>) : <p>{empty}</p>}</section>;
}

export function CapabilityStudio({ capabilities, sources, mappings, lineage, validation, onOpenBindings }: Props) {
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [coverage, setCoverage] = useState<CapabilityCoverage | null>(null);
  const [coverageError, setCoverageError] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

  useEffect(() => { adminApi.capabilityCoverage().then(setCoverage).catch(() => setCoverageError(true)); }, []);
  useEffect(() => { if (!selectedId && capabilities.length) setSelectedId(capabilities[0].id); }, [capabilities, selectedId]);

  const filtered = useMemo(() => capabilities.filter((item) => `${item.name} ${item.id} ${item.description}`.toLowerCase().includes(query.toLowerCase())), [capabilities, query]);
  const selected = capabilities.find((item) => item.id === selectedId) ?? filtered[0];
  const selectedCoverage = coverage?.items.find((item) => item.capability_id === selected?.id);
  const sourceIds = new Set((selected?.steps ?? []).map((step) => step.split(".")[0]));
  const relatedSources = sources.filter((source) => sourceIds.has(source.id));
  const relatedLineage = lineage.filter((item) => item.via === selected?.id || sourceIds.has(item.from));
  const targetIds = new Set(relatedLineage.map((item) => item.to));
  const relatedMappings = mappings.filter((item) => sourceIds.has(item.id.split(".")[0]) || targetIds.has(item.ontology) || relatedLineage.some((link) => link.via === item.id));

  const semanticTotal = 1 + (selectedCoverage?.inputs.total ?? selected?.inputs.length ?? 0) + (selectedCoverage?.outputs.total ?? selected?.returns.length ?? 0);
  const semanticBound = (selectedCoverage?.capability_bound ? 1 : 0) + (selectedCoverage?.inputs.bound ?? 0) + (selectedCoverage?.outputs.bound ?? 0);
  const semanticValue = selectedCoverage ? Math.round((semanticBound / Math.max(semanticTotal, 1)) * 100) : 0;
  const dataValue = selected?.steps.length ? Math.round((relatedSources.length / new Set(selected.steps.map((step) => step.split(".")[0])).size) * 100) : 100;
  const executionValue = validation?.status === "valid" ? 100 : 35;
  const releaseValue = Math.round((semanticValue + dataValue + executionValue) / 3);
  const readiness: Readiness[] = [
    { label: "의미 준비도", value: semanticValue, state: semanticValue === 100 ? "ready" : semanticValue === 0 ? "blocked" : "attention", detail: selectedCoverage ? `${semanticBound}/${semanticTotal} Capability·입출력 의미 연결` : coverageError ? "Binding coverage를 불러올 수 없습니다" : "Binding coverage 확인 중" },
    { label: "데이터 준비도", value: dataValue, state: dataValue === 100 ? "ready" : "attention", detail: selected?.steps.length ? `${relatedSources.length}개 Source · ${selected.steps.length}개 실행 단계` : "외부 데이터가 필요 없는 계산 기능" },
    { label: "실행 준비도", value: executionValue, state: executionValue === 100 ? "ready" : "blocked", detail: validation?.status === "valid" ? "Registry 교차 계약 검증 통과" : `${validation?.diagnostic_count ?? 0}개 진단을 해결해야 합니다` },
    { label: "릴리스 준비도", value: releaseValue, state: releaseValue === 100 ? "ready" : releaseValue < 50 ? "blocked" : "attention", detail: releaseValue === 100 ? "bundle 발행 전 최종 검토 가능" : "미완료 항목을 검토하세요" },
  ];

  if (!capabilities.length) return <div className="loading-state">등록된 Capability가 없습니다.</div>;
  return <div className="capability-studio">
    <aside className="capability-catalog">
      <div className="catalog-heading"><div><span>REGISTRY CAPABILITIES</span><strong>{capabilities.length}개 등록 기능</strong></div><Button size="icon" variant="outline" aria-label="새 Capability" title="Capability 생성 workflow는 준비 중입니다" disabled><Braces size={15} /></Button></div>
      <p className="catalog-help">Registry에 정의된 실행 기능입니다. 화면이나 사용자 메뉴의 개수가 아닙니다.</p>
      <label className="catalog-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="기능, 입력, 업무 질문 검색" /></label>
      <div className="catalog-items">{filtered.map((item) => { const itemCoverage = coverage?.items.find((entry) => entry.capability_id === item.id); const statusLabel = itemCoverage?.status === "covered" ? "연결 완료" : itemCoverage?.status === "partial" ? "일부 연결" : itemCoverage?.status === "unbound" ? "연결 필요" : "확인 중"; return <button key={item.id} className={item.id === selected?.id ? "selected" : ""} onClick={() => setSelectedId(item.id)}><div><strong>{item.name}</strong><code>{item.id}</code></div><span className={`coverage-label ${itemCoverage?.status ?? "unknown"}`}>{statusLabel}</span><ChevronRight size={14} /></button>; })}</div>
    </aside>

    {selected && <section className="capability-workbench">
      <div className="capability-guide"><strong>Capability 검증 순서</strong><span>업무 의미 확인</span><ChevronRight size={13} /><span>데이터 근거 확인</span><ChevronRight size={13} /><Button size="sm" variant="ghost" onClick={onOpenBindings}>Binding 검토</Button><ChevronRight size={13} /><span>실행 결과 검증</span></div>
      <header className="capability-hero"><div><div className="hero-badges"><Badge>{selected.kind ?? "capability"}</Badge><Badge variant={releaseValue === 100 ? "success" : "outline"}>{releaseValue === 100 ? "릴리스 준비 완료" : "준비 중"}</Badge></div><h2>{selected.name}</h2><code>{selected.id}</code><p>{selected.description || "설명이 아직 없습니다. 사용자가 내리는 결정과 제공할 근거를 작성하세요."}</p></div><div className="hero-actions"><Button variant="outline" onClick={() => setActiveTab("checks")}>검토 항목 보기</Button><Button disabled title="릴리스 발행 workflow는 후속 단계에서 연결합니다"><ShieldCheck size={15} />릴리스</Button></div></header>

      <div className="readiness-grid">{readiness.map((item) => <ReadinessCard key={item.label} item={item} />)}</div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="capability-tabs">
        <TabsList><TabsTrigger value="overview">개요</TabsTrigger><TabsTrigger value="semantics">의미 연결</TabsTrigger><TabsTrigger value="execution">데이터와 실행</TabsTrigger><TabsTrigger value="checks">검토 항목</TabsTrigger></TabsList>
        <TabsContent value="overview">
          <div className="studio-grid two-columns">
            <Card><CardHeader><CardTitle>기능 계약</CardTitle><CardDescription>사용자가 제공하는 값과 Runtime이 반환하는 결과입니다.</CardDescription></CardHeader><CardContent className="contract-columns"><ContractList label="입력" items={selected.inputs} empty="입력 없음" /><ContractList label="출력" items={selected.returns} empty="출력 없음" /></CardContent></Card>
            <Card><CardHeader><CardTitle>다음 작업</CardTitle><CardDescription>릴리스 가능 상태까지 사람이 처리해야 할 항목입니다.</CardDescription></CardHeader><CardContent className="next-actions">{semanticValue < 100 && <div><GitFork size={15} /><span><strong>의미 연결 검토</strong><small>{semanticTotal - semanticBound}개 Capability 또는 필드가 미연결 상태입니다.</small></span><Button size="sm" variant="outline" onClick={onOpenBindings}>Bindings 열기</Button></div>}{dataValue < 100 && <div><Database size={15} /><span><strong>데이터 계약 확인</strong><small>실행 단계가 참조하는 Source를 확인할 수 없습니다.</small></span></div>}{executionValue < 100 && <div><AlertTriangle size={15} /><span><strong>Registry 진단 해결</strong><small>{validation?.diagnostic_count ?? 0}개 교차 계약 오류가 있습니다.</small></span></div>}{releaseValue === 100 && <div><Check size={15} /><span><strong>릴리스 준비 완료</strong><small>승인자에게 bundle 발행 검토를 요청할 수 있습니다.</small></span></div>}</CardContent></Card>
          </div>
        </TabsContent>
        <TabsContent value="semantics">
          <Card><CardHeader><CardTitle>Semantic connection coverage</CardTitle><CardDescription>Capability 전체와 각 입출력이 Published Ontology stable concept에 연결되었는지 보여줍니다.</CardDescription></CardHeader><CardContent className="semantic-coverage"><div className={selectedCoverage?.capability_bound ? "done" : "missing"}><Braces size={16} /><span><strong>Capability 의미</strong><small>{selectedCoverage?.capability_bound ? "승인된 연결이 있습니다" : "Ontology concept 연결이 필요합니다"}</small></span></div>{selected.inputs.map((field) => <div key={`input-${field}`} className={selectedCoverage && !selectedCoverage.inputs.unbound_fields.includes(field) ? "done" : "missing"}><ArrowRight size={16} /><span><strong>입력 · {field}</strong><small>{selectedCoverage && !selectedCoverage.inputs.unbound_fields.includes(field) ? "연결됨" : "stable concept을 선택하세요"}</small></span></div>)}{selected.returns.map((field) => <div key={`output-${field}`} className={selectedCoverage && !selectedCoverage.outputs.unbound_fields.includes(field) ? "done" : "missing"}><ArrowRight size={16} /><span><strong>출력 · {field}</strong><small>{selectedCoverage && !selectedCoverage.outputs.unbound_fields.includes(field) ? "연결됨" : "stable concept을 선택하세요"}</small></span></div>)}</CardContent></Card>
        </TabsContent>
        <TabsContent value="execution">
          <div className="execution-flow"><div><small>USER INPUT</small><strong>{selected.inputs.length} fields</strong></div><ArrowRight /><div><small>SOURCES</small><strong>{relatedSources.length || sourceIds.size} contracts</strong></div><ArrowRight /><div><small>MAPPINGS</small><strong>{relatedMappings.length} transforms</strong></div><ArrowRight /><div><small>RUNTIME OUTPUT</small><strong>{selected.returns.length} objects</strong></div></div>
          <div className="studio-grid two-columns"><Card><CardHeader><CardTitle>실행 단계</CardTitle></CardHeader><CardContent className="step-list">{selected.steps.map((step, index) => <div key={step}><Badge variant="outline">{index + 1}</Badge><Workflow size={14} /><code>{step}</code></div>)}</CardContent></Card><Card><CardHeader><CardTitle>연결된 데이터 계약</CardTitle></CardHeader><CardContent className="source-list">{relatedSources.map((source) => <div key={source.id}><Database size={15} /><span><strong>{source.name}</strong><small>{source.type} · {source.provider ?? "Teoria Data DB"}</small></span></div>)}{!relatedSources.length && <p>Source 세부 정보를 연결하지 못했습니다. Registry reference를 확인하세요.</p>}</CardContent></Card></div>
        </TabsContent>
        <TabsContent value="checks"><Card><CardHeader><CardTitle>사람의 최종 판단이 필요한 항목</CardTitle><CardDescription>자동 검증 성공은 업무 의미의 정확성을 보장하지 않습니다.</CardDescription></CardHeader><CardContent className="review-checklist">{["사용자 질문과 Capability 출력이 실제 의사결정을 지원하는가", "Ontology stable concept이 API·DB 컬럼 이름이 아니라 업무 의미를 나타내는가", "OpenMetadata description·Glossary·lineage가 Binding 근거를 뒷받침하는가", "Mapping의 identity, null, 단위, 시점 변환이 명시되었는가", "부분 실패와 불확실성이 결과에 보존되는가"].map((item) => <label key={item}><input type="checkbox" /><span>{item}</span></label>)}</CardContent></Card></TabsContent>
      </Tabs>
    </section>}
  </div>;
}
