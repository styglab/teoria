import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { metadataApi, type MetadataTableDetail } from "../../api/metadata";
import { authApi } from "../../api/auth";
import { suggestionApi } from "../../api/suggestions";
import { MetadataAssetPage } from "./MetadataAssetPage";
import { AdminAccessProvider } from "../access/AdminAccess";
vi.mock("./AssetContext",()=>({AssetContext:({section}:{section:string})=><p>context:{section}</p>}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();window.sessionStorage.clear()});
const detail:MetadataTableDetail={reference:{system:"openmetadata",entity_id:"table-id",entity_type:"table",fully_qualified_name:"svc.db.schema.contracts",version:1},name:"contracts",display_name:null,description:"contract table",tags:[],owners:[],domains:[],database:null,database_schema:null,columns:[{name:"amount",description:"contract amount"}],glossary_terms:[],test_suite:null};
test("opens a shareable asset URL and selected tab without a modal",async()=>{
 const get=vi.spyOn(metadataApi,"metadataTable").mockResolvedValue(detail);
 render(<MemoryRouter initialEntries={["/admin/data-catalog/assets/svc.db.schema.contracts?tab=columns&returnTo=%2Fadmin%2Fdata-catalog%3Fq%3Dcontracts%26filter%3Downer"]}><Routes><Route path="/admin/data-catalog/assets/:fqn" element={<MetadataAssetPage/>}/></Routes></MemoryRouter>);
 expect(await screen.findByText("contract amount")).toBeInTheDocument();
 expect(get).toHaveBeenCalledWith("svc.db.schema.contracts");
 expect(screen.getByRole("link",{name:"← 목록으로"})).toHaveAttribute("href","/admin/data-catalog?q=contracts&filter=owner");
 expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
 expect(screen.getByRole("link",{name:"이 자산의 제안"})).toHaveAttribute("href","/admin/changes/review?asset=svc.db.schema.contracts&assetId=table-id");
 fireEvent.click(screen.getByRole("button",{name:"운영"}));
 expect(await screen.findByText("context:operations")).toBeInTheDocument();
 expect(screen.queryByText("contract amount")).not.toBeInTheDocument();
});

test("submits a description change for review without applying it",async()=>{
 window.sessionStorage.setItem("teoria-admin-token","test-token");
 vi.spyOn(authApi,"session").mockResolvedValue({actor:"user:metadata-admin",roles:["metadata_admin"]});
 vi.spyOn(metadataApi,"metadataTable").mockResolvedValue(detail);
 const submit=vi.spyOn(suggestionApi,"suggestDescriptionChange").mockResolvedValue({
  suggestion_id:"suggestion-1",target_type:"openmetadata_table",target_ref:"openmetadata://table/svc.db.schema.contracts",
  suggestion_type:"description",proposed_value:{description:"계약 테이블 설명"},confidence:1,rationale:null,risk_level:"low",
  model_provider:"teoria",model_name:"admin-metadata-editor",policy_version:"manual-metadata-change-v1",status:"pending",created_at:new Date().toISOString(),evidence:[],
 });
 render(<MemoryRouter initialEntries={["/admin/data-catalog/assets/svc.db.schema.contracts"]}><AdminAccessProvider><Routes><Route path="/admin/data-catalog/assets/:fqn" element={<MetadataAssetPage/>}/></Routes></AdminAccessProvider></MemoryRouter>);
 await screen.findByText("관리자 · user:metadata-admin");
 fireEvent.click(screen.getByRole("button",{name:"설명 변경안"}));
 const dialog=await screen.findByRole("dialog",{name:"설명 변경안 작성"});
 fireEvent.change(screen.getByRole("textbox",{name:"제안 설명"}),{target:{value:"계약 테이블 설명"}});
 fireEvent.click(screen.getByRole("button",{name:"검토 요청"}));
 expect(await screen.findByText("설명 변경안을 검토 대기열에 등록했습니다.")).toBeInTheDocument();
 expect(submit).toHaveBeenCalledWith("table-id","계약 테이블 설명",undefined);
 expect(dialog).not.toBeInTheDocument();
});

test("copies scoped diagnosis requests without starting or applying an analysis",async()=>{
 const writeText=vi.fn().mockResolvedValue(undefined);
 vi.stubGlobal("navigator",{clipboard:{writeText}});
 vi.spyOn(metadataApi,"metadataTable").mockResolvedValue(detail);
 render(<MemoryRouter initialEntries={["/admin/data-catalog/assets/svc.db.schema.contracts"]}><Routes><Route path="/admin/data-catalog/assets/:fqn" element={<MetadataAssetPage/>}/></Routes></MemoryRouter>);
 await screen.findByRole("button",{name:"진단 요청"});
 expect(screen.queryByRole("region",{name:"자산 진단"})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"진단 요청"}));
 await screen.findByRole("region",{name:"자산 진단"});
 for(const [label,skill] of [["메타데이터 정비","enrich-metadata-asset"],["업무 의미 연결","align-metadata-semantics"],["개방 적합성 진단","assess-data-disclosure"]]){
  fireEvent.click(screen.getByRole("button",{name:`${label} 요청 복사`}));
  expect(writeText).toHaveBeenLastCalledWith(expect.stringContaining(`$${skill}\nOpenMetadata 테이블 svc.db.schema.contracts`));
  expect(writeText.mock.calls.at(-1)?.[0]).toContain("승인하거나 적용하지는 마");
 }
 expect(writeText.mock.calls.at(-1)?.[0]).toContain("지원하지 않는 제안 유형은 Review Queue에 제출하지 마");
});
