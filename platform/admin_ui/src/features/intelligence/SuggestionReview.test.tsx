import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi, type AssetContextResult, type IntelligenceSuggestion, type MetadataTableDetail } from "../../api/admin";
import { SuggestionReview } from "./SuggestionReview";
afterEach(()=>{cleanup();vi.restoreAllMocks()});
const suggestion:IntelligenceSuggestion={suggestion_id:"related",target_type:"column",target_ref:"openmetadata://column/svc.db.schema.contracts.amount",suggestion_type:"description",proposed_value:{description:"제안 설명"},confidence:.9,rationale:"source evidence",risk_level:"low",model_provider:"test",model_name:"test",policy_version:"test",status:"pending",created_at:"2026-10-13T00:00:00Z",evidence:[]};
test("uses the asset's authoritative context and shows current and proposed descriptions",async()=>{
 vi.spyOn(adminApi,"assetContext").mockResolvedValue({business:{status:"available",data:{suggestions:[{suggestion_id:"related"}],suggestions_truncated:false}}} as unknown as AssetContextResult);
 const get=vi.spyOn(adminApi,"intelligenceSuggestion").mockResolvedValue(suggestion);
 const all=vi.spyOn(adminApi,"intelligenceSuggestions");
 vi.spyOn(adminApi,"metadataTable").mockResolvedValue({reference:{fully_qualified_name:"svc.db.schema.contracts"},columns:[{name:"amount",description:"현재 설명"}],tags:[]} as unknown as MetadataTableDetail);
 render(<MemoryRouter initialEntries={["/admin/review-queue?asset=svc.db.schema.contracts&assetId=table-id"]}><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("현재 설명")).toBeInTheDocument();
 expect(screen.getAllByText("제안 설명").length).toBeGreaterThan(0);
 expect(get).toHaveBeenCalledWith("related");expect(all).not.toHaveBeenCalled();
 expect(screen.getByRole("link",{name:"자산으로 돌아가기"})).toHaveAttribute("href","/admin/data-catalog/assets/svc.db.schema.contracts?tab=governance");
});
test("does not describe an unavailable review source as an empty queue",async()=>{
 vi.spyOn(adminApi,"intelligenceSuggestions").mockRejectedValue(new Error("review source unavailable"));
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("review source unavailable")).toBeInTheDocument();
 expect(screen.queryByText("검토할 제안이 없습니다")).not.toBeInTheDocument();
});
