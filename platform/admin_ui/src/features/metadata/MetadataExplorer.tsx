import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Database, Folder, RefreshCw, Table2 } from "lucide-react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { metadataApi, type MetadataEntity, type MetadataStatus } from "../../api/metadata";

import { CatalogLayout, FilterTabs, PageHeader, SearchField } from "../../components/workspace/WorkspaceLayout";

function normalizeAdminToken(input: string): string {
  let token = input.trim().replace(/^(?:export\s+)?TEORIA_ADMIN_API_TOKEN\s*=\s*/, "");
  if ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'"))) {
    token = token.slice(1, -1);
  }
  return token.replace(/^Bearer\s+/i, "").trim();
}

type Filter = "all" | "description" | "owner" | "tags";
const filters: Array<{id:Filter;label:string}>=[{id:"all",label:"전체"},{id:"description",label:"설명 없음"},{id:"owner",label:"소유자 미지정"},{id:"tags",label:"태그·용어 없음"}];
export function MetadataExplorer() {
 const navigate=useNavigate();
 const location=useLocation();
 const [params,setParams]=useSearchParams();
 const query=params.get("q")||"";
 const schema=params.get("schema")||"";
 const filter=filters.some(item=>item.id===params.get("filter"))?params.get("filter") as Filter:"all";
 const sort=params.get("sort")==="desc"?"desc":"asc";
 const page=Math.max(0,Math.floor(Number(params.get("page"))||0));
 const pageSize=params.get("size")==="50"?50:25;
 const [status,setStatus]=useState<MetadataStatus|null>(null);
 const [tables,setTables]=useState<MetadataEntity[]>([]);
 const [schemas,setSchemas]=useState<MetadataEntity[]>([]);
 const [total,setTotal]=useState<number|null>(null);
 const [loading,setLoading]=useState(true);
 const [loaded,setLoaded]=useState(0);
 const [error,setError]=useState<string|null>(null);
 const [schemaError,setSchemaError]=useState<string|null>(null);
 const [refresh,setRefresh]=useState(0);
 const [adminToken,setAdminToken]=useState("");
 const [authBusy,setAuthBusy]=useState(false);
 const [authError,setAuthError]=useState<string|null>(null);
 const [showAdminToken,setShowAdminToken]=useState(false);
 const update=(values:Record<string,string>)=>setParams(previous=>{
  const next=new URLSearchParams(previous);next.delete("page");
  Object.entries(values).forEach(([key,value])=>value?next.set(key,value):next.delete(key));return next;
 },{replace:true});
 useEffect(()=>{
  let active=true;setError(null);setStatus(null);
  metadataApi.metadataStatus().then(value=>{if(active)setStatus(value)}).catch(reason=>{if(active)setError((reason as Error).message)});
  return()=>{active=false};
 },[refresh]);
 useEffect(()=>{
  if(!status?.available)return;
  let active=true;
  const load=async()=>{
   const all:MetadataEntity[]=[];const visited=new Set<string>();let cursor:string|undefined;
   try {
    do {
     const result=await metadataApi.metadataSchemas(cursor);if(!active)return;
     all.push(...result.items);cursor=result.after||undefined;
     if(cursor){if(visited.has(cursor))throw new Error("스키마 페이지가 반복됩니다.");visited.add(cursor)}
    }while(cursor);
    if(active){setSchemas(all);setSchemaError(null)}
   }catch{if(active)setSchemaError("스키마 목록을 조회하지 못했습니다. 전체 자산은 계속 확인할 수 있습니다.")}
  };
  load();return()=>{active=false};
 },[status?.available,refresh]);
 useEffect(()=>{
  if(!status?.available)return;
  let active=true;setLoading(true);setTables([]);setTotal(null);setLoaded(0);setError(null);
  const load=async()=>{
   const all:MetadataEntity[]=[];const visited=new Set<string>();let cursor:string|undefined;
   try {
    do {
     const options:{after?:string;limit:number;databaseSchema?:string}={after:cursor,limit:100};
     if(schema)options.databaseSchema=schema;
     const result=await metadataApi.metadataTables(options);if(!active)return;
     all.push(...result.items);setTotal(result.total);setLoaded(all.length);cursor=result.after||undefined;
     if(cursor){if(visited.has(cursor))throw new Error("자산 페이지가 반복됩니다.");visited.add(cursor)}
    }while(cursor);
    if(active)setTables([...new Map(all.map(item=>[item.reference.entity_id,item])).values()]);
   }catch(reason){if(active)setError((reason as Error).message)}
   finally{if(active)setLoading(false)}
  };
  load();return()=>{active=false};
 },[schema,status?.available,refresh]);
 const counts=useMemo(()=>({all:tables.length,description:tables.filter(item=>!item.description?.trim()).length,owner:tables.filter(item=>!item.owners.length).length,tags:tables.filter(item=>!item.tags.length).length}),[tables]);
 const filtered=useMemo(()=>{
  const text=query.trim().toLocaleLowerCase();
  return tables.filter(item=>
   (filter==="all"||filter==="description"&&!item.description?.trim()||filter==="owner"&&!item.owners.length||filter==="tags"&&!item.tags.length)&&
   (!text||[item.name,item.display_name,item.description,item.reference.fully_qualified_name,...item.owners.map(owner=>String(owner.displayName||owner.name||"")),...item.tags.map(tag=>String(tag.tagFQN||tag.name||""))].some(value=>value?.toLocaleLowerCase().includes(text)))
  ).sort((a,b)=>(a.display_name||a.name).localeCompare(b.display_name||b.name,"ko",{numeric:true})*(sort==="asc"?1:-1));
 },[tables,query,filter,sort]);
 const lastPage=Math.max(0,Math.ceil(filtered.length/pageSize)-1);
 const currentPage=Math.min(page,lastPage);
 const visible=filtered.slice(currentPage*pageSize,(currentPage+1)*pageSize);
 const openTable=(table:MetadataEntity)=>{
  if(!table.reference.fully_qualified_name)return;
  const back=location.pathname+location.search;
  navigate(`/admin/data-catalog/assets/${encodeURIComponent(table.reference.fully_qualified_name)}?${new URLSearchParams({returnTo:back})}`);
 };
  if (error?.includes("(401)")) return <div className="metadata-empty"><Database size={28} /><h3>관리자 인증이 필요합니다</h3><p>관리자에게 받은 토큰으로 데이터 자산을 조회하세요.</p><form onSubmit={async event => {
    event.preventDefault();
    const token = normalizeAdminToken(adminToken);
    if (!token || authBusy) return;
    setAuthBusy(true); setAuthError(null);
    window.sessionStorage.setItem("teoria-admin-token", token);
    try { const next = await metadataApi.metadataStatus(); setStatus(next); setAdminToken(""); setShowAdminToken(false); setError(null); setRefresh(value=>value+1); }
    catch (reason) {
      window.sessionStorage.removeItem("teoria-admin-token");
      setAuthError((reason as Error).message.includes("(401)")
        ? "운영 서버가 이 토큰을 거절했습니다. deploy/compose/.env의 TEORIA_ADMIN_API_TOKEN인지 확인하세요. OpenMetadata 토큰과는 다릅니다."
        : "서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.");
    } finally { setAuthBusy(false); }
  }}><label>관리자 토큰 <input type={showAdminToken ? "text" : "password"} autoComplete="off" spellCheck={false} disabled={authBusy} value={adminToken} onChange={event => { setAdminToken(event.target.value); setAuthError(null); }} /></label><button type="button" disabled={authBusy} aria-pressed={showAdminToken} onClick={() => setShowAdminToken(value => !value)}>{showAdminToken ? "토큰 숨기기" : "토큰 보기"}</button><button type="submit" disabled={!normalizeAdminToken(adminToken) || authBusy}>{authBusy ? "연결 중…" : "연결"}</button><p>deploy/compose/.env의 TEORIA_ADMIN_API_TOKEN을 사용하세요. 설정 줄 전체를 붙여넣어도 됩니다.</p>{authError && <p role="alert">{authError}</p>}</form></div>;

 if(!status&&!error)return <div className="loading-state">자산 연결 상태를 확인하고 있습니다…</div>;
 if(status&&!status.enabled)return <div className="metadata-empty"><Database size={28}/><h3>OpenMetadata가 설정되지 않았습니다</h3></div>;
 if(status&&!status.available)return <div className="metadata-empty"><Database size={28}/><h3>OpenMetadata에 연결할 수 없습니다</h3><p>{status.reason}</p><button onClick={()=>setRefresh(value=>value+1)}>다시 시도</button></div>;
 return <CatalogLayout label="스키마 탐색" sidebar={<><h2>스키마</h2><button className={!schema?"selected":""} onClick={()=>update({schema:""})}><Database size={16}/><span>전체 자산</span></button>
 {schemas.map(item=><button key={item.reference.entity_id} className={schema===item.reference.fully_qualified_name?"selected":""} title={item.reference.fully_qualified_name||item.name} onClick={()=>update({schema:item.reference.fully_qualified_name||""})}><Folder size={16}/><span><strong>{item.display_name||item.name}</strong><small>{item.reference.fully_qualified_name}</small></span></button>)}
 {schema&&!schemas.some(item=>item.reference.fully_qualified_name===schema)&&<p className="selected-schema">선택: {schema}</p>}
 {schemaError&&<p role="alert">{schemaError}</p>}
 </>}>
 <PageHeader title={schemas.find(item=>item.reference.fully_qualified_name===schema)?.name || (schema?"선택한 스키마":"전체 자산")} description={loading?`불러오는 중 · ${loaded}${total===null?"":` / ${total}`}개`:error?"조회 실패":`${filtered.length}개 표시 · 선택 범위 ${tables.length}개`} actions={<button className="page-icon-button" aria-label="자산 새로고침" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={16}/></button>} />
 <SearchField label="전체 자산 검색" placeholder="이름, 설명, 태그, 소유자 검색" value={query} onChange={value=>update({q:value})}/>
 <div className="page-controls"><FilterTabs label="메타데이터 누락 필터" items={filters.map(item=>({...item,count:loading||error?"—":counts[item.id]}))} value={filter} onChange={value=>update({filter:value==="all"?"":value})}/><label>정렬<select value={sort} onChange={event=>update({sort:event.target.value})}><option value="asc">이름 오름차순</option><option value="desc">이름 내림차순</option></select></label></div>
 {error&&<div role="alert" className="workspace-error">자산 조회 실패: {error} <button onClick={()=>setRefresh(value=>value+1)}>다시 시도</button></div>}
 <div className="asset-catalog-table-wrap" aria-busy={loading}><table className="asset-catalog-table"><thead><tr><th>자산</th><th>설명</th><th>태그·용어</th><th>소유자</th><th><span className="sr-only">열기</span></th></tr></thead><tbody>{visible.map(table=><tr key={table.reference.entity_id} onClick={()=>openTable(table)} tabIndex={0} onKeyDown={event=>{if(event.key==="Enter")openTable(table)}}>
 <td><div className="asset-name-cell"><Table2 size={18}/><span><strong>{table.display_name||table.name}</strong><code title={table.reference.fully_qualified_name||""}>{table.reference.fully_qualified_name}</code></span></div></td>
 <td><p className={table.description?"asset-description":"asset-value-missing"} title={table.description||""}>{table.description||"설명 없음"}</p></td>
 <td><div className="asset-labels">{table.tags.slice(0,2).map((tag,index)=><span key={index} title={String(tag.tagFQN||tag.name||"")}>{String(tag.displayName||tag.name||tag.tagFQN||"태그")}</span>)}{table.tags.length>2&&<small>+{table.tags.length-2}</small>}{!table.tags.length&&<span className="asset-value-missing">없음</span>}</div></td>
 <td><span className={table.owners.length?"asset-owner":"asset-value-missing"}>{table.owners.map(owner=>String(owner.displayName||owner.name||owner.id)).join(", ")||"미지정"}</span></td><td><ChevronRight size={16}/></td>
 </tr>)}</tbody></table>{loading?<div className="asset-catalog-empty" role="status">자산을 불러오고 있습니다…</div>:!error&&!visible.length&&<div className="asset-catalog-empty">{query||filter!=="all"?"조건에 맞는 자산이 없습니다.":"등록된 자산이 없습니다."}{(query||filter!=="all")&&<button onClick={()=>update({q:"",filter:""})}>검색·필터 초기화</button>}</div>}</div>
 <footer className="asset-catalog-footer"><label>페이지당<select value={pageSize} onChange={event=>update({size:event.target.value})}><option value="25">25개</option><option value="50">50개</option></select></label><span>{loading||error?"—":filtered.length?`${currentPage*pageSize+1}–${Math.min((currentPage+1)*pageSize,filtered.length)} / ${filtered.length}개`:"0개"}</span><div><button aria-label="이전 페이지" disabled={loading||currentPage===0} onClick={()=>update({page:String(currentPage-1)})}><ChevronLeft size={16}/></button><span>{currentPage+1} / {lastPage+1}</span><button aria-label="다음 페이지" disabled={loading||currentPage===lastPage} onClick={()=>update({page:String(currentPage+1)})}><ChevronRight size={16}/></button></div></footer>
 </CatalogLayout>;
}
