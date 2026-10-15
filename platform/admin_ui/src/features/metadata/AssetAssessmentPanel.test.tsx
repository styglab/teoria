import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi, type AssetAssessment, type MetadataTableDetail } from "../../api/admin";
import { AssetAssessmentPanel } from "./AssetAssessmentPanel";

vi.mock("../access/AdminAccess",()=>({useAdminAccess:()=>({principal:{actor:"user:test",roles:["metadata_admin"]},requestLogin:vi.fn()})}));
afterEach(()=>{cleanup();vi.restoreAllMocks()});
const detail:MetadataTableDetail={reference:{system:"openmetadata",entity_id:"table-id",entity_type:"table",fully_qualified_name:"s.d.c.table",version:1},name:"table",display_name:null,description:null,tags:[],owners:[],domains:[],database:null,database_schema:null,columns:[{name:"amount"}],glossary_terms:[],test_suite:null};
const result:AssetAssessment={assessment_id:"assessment-id",status:"completed",scopes:["metadata_enrichment"],model_name:"synthetic",created_at:"2026-10-15T00:00:00Z",error_code:null,suggestion_ids:["suggestion-id"],findings:[]};

test("starts a bounded assessment and links pending suggestions for review",async()=>{
 vi.spyOn(adminApi,"assetAssessments").mockResolvedValue({items:[]});
 const start=vi.spyOn(adminApi,"createAssetAssessment").mockResolvedValue(result);
 render(<MemoryRouter><AssetAssessmentPanel detail={detail}/></MemoryRouter>);
 fireEvent.click(screen.getByRole("checkbox",{name:"개방 적합성 진단"}));
 fireEvent.click(screen.getByRole("button",{name:"진단 실행"}));
 expect(await screen.findByText("진단 완료 · 제안 1건")).toBeInTheDocument();
 expect(start).toHaveBeenCalledWith({table_fqn:"s.d.c.table",scopes:["metadata_enrichment","semantic_alignment","disclosure_assessment"],column_names:[],disclosure_context:"public_release"});
 expect(screen.getByRole("link",{name:/변경 제안 검토/})).toHaveAttribute("href","/admin/changes/review?suggestion=suggestion-id");
});

test("restores previous findings and explains missing model configuration",async()=>{
 vi.spyOn(adminApi,"assetAssessments").mockResolvedValue({items:[{...result,status:"partial",findings:[{summary:"법령 근거 추가 확인 필요"}]}]});
 vi.spyOn(adminApi,"createAssetAssessment").mockRejectedValue(new Error("asset_assessment_not_configured"));
 render(<MemoryRouter><AssetAssessmentPanel detail={detail}/></MemoryRouter>);
 expect(await screen.findByText("법령 근거 추가 확인 필요")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"진단 실행"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("진단 모델과 Worker 설정이 필요합니다.");
});

test("searches columns and submits the checked selection",async()=>{
 vi.spyOn(adminApi,"assetAssessments").mockResolvedValue({items:[]});
 const start=vi.spyOn(adminApi,"createAssetAssessment").mockResolvedValue(result);
 render(<MemoryRouter><AssetAssessmentPanel detail={{...detail,columns:[{name:"amount"},{name:"contract_date"}]}}/></MemoryRouter>);
 fireEvent.click(screen.getByText("대상 컬럼 선택"));
 fireEvent.change(screen.getByRole("textbox",{name:"진단 대상 컬럼 검색"}),{target:{value:"amount"}});
 expect(screen.queryByRole("checkbox",{name:"contract_date"})).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("checkbox",{name:"amount"}));
 expect(screen.getByText("1개 선택")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"진단 실행"}));
 await screen.findByText("진단 완료 · 제안 1건");
 expect(start.mock.calls[0][0].column_names).toEqual(["amount"]);
});
