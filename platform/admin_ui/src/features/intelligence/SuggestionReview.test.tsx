import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi, type IntelligenceSuggestion, type MetadataTableDetail } from "../../api/admin";
import { SuggestionReview } from "./SuggestionReview";
afterEach(()=>{cleanup();vi.restoreAllMocks()});
const suggestion:IntelligenceSuggestion={suggestion_id:"related",target_type:"column",target_ref:"openmetadata://column/svc.db.schema.contracts.amount",suggestion_type:"description",proposed_value:{description:"제안 설명"},confidence:.9,rationale:"source evidence",risk_level:"low",model_provider:"test",model_name:"test",policy_version:"test",status:"pending",created_at:"2026-10-13T00:00:00Z",evidence:[]};
test("uses the asset's authoritative context and shows current and proposed descriptions",async()=>{
 const page=vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[suggestion],next_cursor:null});
 const all=vi.spyOn(adminApi,"intelligenceSuggestions");
 vi.spyOn(adminApi,"metadataTable").mockResolvedValue({reference:{fully_qualified_name:"svc.db.schema.contracts"},columns:[{name:"amount",description:"현재 설명"}],tags:[]} as unknown as MetadataTableDetail);
 render(<MemoryRouter initialEntries={["/admin/review-queue?asset=svc.db.schema.contracts&assetId=table-id"]}><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("현재 설명")).toBeInTheDocument();
 expect(screen.getAllByText("제안 설명").length).toBeGreaterThan(0);
 expect(page).toHaveBeenCalledWith("pending",undefined,"table-id");expect(all).not.toHaveBeenCalled();
 expect(screen.getByRole("link",{name:"자산으로 돌아가기"})).toHaveAttribute("href","/admin/data-catalog/assets/svc.db.schema.contracts?tab=governance");
});
test("does not describe an unavailable review source as an empty queue",async()=>{
 vi.spyOn(adminApi,"suggestionPage").mockRejectedValue(new Error("review source unavailable"));
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("review source unavailable")).toBeInTheDocument();
 expect(screen.queryByText("이 페이지에 제안이 없습니다")).not.toBeInTheDocument();
});

test("fetches status before pagination and navigates beyond the first fifty suggestions",async()=>{
 const page=vi.spyOn(adminApi,"suggestionPage").mockImplementation(async(status,after)=>({
  items:[{...suggestion,suggestion_id:after?"older":"newer",rationale:after?"오래된 대기 제안":"첫 페이지 제안",status:status==="failed"?"failed":"pending"}],
  next_cursor:after?null:"older-cursor",
 }));
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("첫 페이지 제안")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"다음 페이지"}));
 expect(await screen.findByText("오래된 대기 제안")).toBeInTheDocument();
 expect(page).toHaveBeenLastCalledWith("pending","older-cursor",undefined);
 fireEvent.click(screen.getByRole("button",{name:"적용 실패"}));
 await waitFor(()=>expect(page).toHaveBeenLastCalledWith("failed",undefined,undefined));
 expect(await screen.findByText("첫 페이지 제안")).toBeInTheDocument();
 expect(screen.getByRole("button",{name:"이전 페이지"})).toBeDisabled();
 fireEvent.click(screen.getByRole("button",{name:"다음 페이지"}));
 await screen.findByText("오래된 대기 제안");
 fireEvent.click(screen.getByRole("button",{name:"이전 페이지"}));
 await screen.findByText("첫 페이지 제안");
 expect(page).toHaveBeenLastCalledWith("failed",undefined,undefined);
});

test("retries only pre-effect failures and reconciles uncertain effects",async()=>{
 const application={status:"failed",target_system:"openmetadata",attempts:1,error_code:"source_unavailable",attempted_at:null,applied_at:null,lease_active:false,effect_started_at:null,effect_succeeded_at:null,external_change_ref:null};
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[
  {...suggestion,suggestion_id:"retry",status:"failed",next_action:"retry",application},
  {...suggestion,suggestion_id:"uncertain",status:"failed",next_action:"reconcile",application:{...application,effect_started_at:"2026-10-14T00:00:00Z"}},
 ],next_cursor:null});
 const retry=vi.spyOn(adminApi,"retrySuggestionApplication").mockResolvedValue({...suggestion,status:"applied"});
 const reconcile=vi.spyOn(adminApi,"reconcileSuggestionApplication").mockResolvedValue({...suggestion,status:"applied"});
 const review=vi.spyOn(adminApi,"reviewSuggestion");
 render(<MemoryRouter initialEntries={["/?status=failed"]}><SuggestionReview/></MemoryRouter>);
 fireEvent.click(await screen.findByRole("button",{name:"기존 승인으로 다시 적용"}));
 await waitFor(()=>expect(retry).toHaveBeenCalledWith("retry"));
 fireEvent.click(await screen.findByRole("button",{name:"기존 적용 결과 확인"}));
 await waitFor(()=>expect(reconcile).toHaveBeenCalledWith("uncertain"));
 expect(review).not.toHaveBeenCalled();
 expect(screen.getAllByText("source_unavailable")).toHaveLength(2);
});

test("links persisted application results to the exact draft after a reload",async()=>{
 const id="00000000-0000-4000-8000-000000000001";
 const application={status:"applied",target_system:"teoria_binding",attempts:1,error_code:null,attempted_at:null,applied_at:null,lease_active:false,effect_started_at:"2026-10-14T00:00:00Z",effect_succeeded_at:"2026-10-14T00:00:01Z",external_change_ref:`teoria://binding/${id}`};
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[
  {...suggestion,status:"applied",suggestion_type:"binding",application},
  {...suggestion,suggestion_id:"ontology",status:"applied",suggestion_type:"ontology_change",application:{...application,external_change_ref:`teoria://ontology/draft/${id}`}},
 ],next_cursor:null});
 render(<MemoryRouter initialEntries={["/?status=applied"]}><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByRole("link",{name:"생성된 Binding 검토"})).toHaveAttribute("href",`/admin/semantic-model/bindings?binding=${id}`);
 expect(screen.getByRole("link",{name:"생성된 Ontology 초안 검토"})).toHaveAttribute("href",`/admin/semantic-model/ontology?version=${id}`);
});

test("compares a global suggestion with live values and preserves the original evidence",async()=>{
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[{...suggestion,submitted_by:"user:author",proposed_value:{description:"제안 설명",table_id:"table-id",column_fqn:"svc.db.schema.contracts.amount",source_description:"제안 당시 설명",source_version:"1.0"}}],next_cursor:null});
 const target=vi.spyOn(adminApi,"suggestionTarget").mockResolvedValue({reference:{fully_qualified_name:"svc.db.schema.contracts",version:2.0},columns:[{name:"amount",description:"최신 설명"}],tags:[]} as unknown as MetadataTableDetail);
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("최신 설명")).toBeInTheDocument();
 expect(screen.getByText("제안 당시 설명")).toBeInTheDocument();
 expect(screen.getByText(/제안 생성 후 자산 버전이 변경됐습니다/)).toBeInTheDocument();
 expect(screen.getByText(/제출 user:author/)).toBeInTheDocument();
 expect(screen.getByText("위험도 낮음")).toBeInTheDocument();
 expect(target).toHaveBeenCalledWith("related");
 expect(screen.getByRole("link",{name:"최신 자산 확인·재분석"})).toHaveAttribute("href","/admin/data-catalog/assets/svc.db.schema.contracts?tab=governance");
});

test("does not present snapshot evidence as a live value when the current source fails",async()=>{
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[{...suggestion,proposed_value:{description:"제안 설명",table_id:"table-id",source_description:"이전 근거"}}],next_cursor:null});
 vi.spyOn(adminApi,"suggestionTarget").mockRejectedValue(new Error("unavailable"));
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText(/최신 값을 조회하지 못했습니다/)).toBeInTheDocument();
 expect(screen.getAllByText("이전 근거")).toHaveLength(1);
});

test("loads attempt history on demand, pages older attempts and distinguishes uncertain attempts",async()=>{
 const application={status:"failed",target_system:"openmetadata",attempts:2,error_code:"stale_evidence",attempted_at:null,applied_at:null,lease_active:false,effect_started_at:null,effect_succeeded_at:null,external_change_ref:null};
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[{...suggestion,status:"failed",next_action:"reanalyze",application}],next_cursor:null});
 const attempt={attempt_id:"attempt-2",actor:"user:retry",target_system:"openmetadata",started_at:"2026-10-14T00:00:00Z",finished_at:null,outcome:null,error_code:null};
 const history=vi.spyOn(adminApi,"suggestionAttempts").mockResolvedValueOnce({items:[attempt],next_cursor:"older"}).mockResolvedValueOnce({items:[{...attempt,attempt_id:"attempt-1",actor:"user:first",outcome:"failed",error_code:"source_unavailable"}],next_cursor:null});
 render(<MemoryRouter initialEntries={["/?status=failed"]}><SuggestionReview/></MemoryRouter>);
 fireEvent.click(await screen.findByRole("button",{name:"적용 이력 보기"}));
 expect(await screen.findByText(/실행자 user:retry/)).toBeInTheDocument();
 expect(screen.getByText("종료 기록 없음")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"이전 시도 더 보기"}));
 expect(await screen.findByText(/실행자 user:first/)).toBeInTheDocument();
 expect(history).toHaveBeenLastCalledWith("related","older");
 expect(screen.queryByRole("button",{name:"기존 승인으로 다시 적용"})).not.toBeInTheDocument();
});

test("treats OpenMetadata numeric versions as equal regardless of decimal formatting",async()=>{
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[{...suggestion,proposed_value:{description:"제안 설명",table_id:"table-id",source_version:"1.0"}}],next_cursor:null});
 vi.spyOn(adminApi,"suggestionTarget").mockResolvedValue({reference:{fully_qualified_name:"svc.db.schema.contracts",version:1},columns:[{name:"amount",description:"동일 버전 설명"}],tags:[]} as unknown as MetadataTableDetail);
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 expect(await screen.findByText("동일 버전 설명")).toBeInTheDocument();
 expect(screen.queryByText(/제안 생성 후 자산 버전이 변경됐습니다/)).not.toBeInTheDocument();
});

test("retries a history read failure without issuing an application write",async()=>{
 const application={status:"failed",target_system:"openmetadata",attempts:1,error_code:null,attempted_at:null,applied_at:null,lease_active:false,effect_started_at:null,effect_succeeded_at:null,external_change_ref:null};
 vi.spyOn(adminApi,"suggestionPage").mockResolvedValue({items:[{...suggestion,status:"failed",application}],next_cursor:null});
 const history=vi.spyOn(adminApi,"suggestionAttempts").mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({items:[],next_cursor:null});
 const retry=vi.spyOn(adminApi,"retrySuggestionApplication");
 render(<MemoryRouter><SuggestionReview/></MemoryRouter>);
 fireEvent.click(await screen.findByRole("button",{name:"적용 이력 보기"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("적용 이력을 조회하지 못했습니다.");
 expect(screen.queryByText("기록된 적용 시도가 없습니다.")).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"다시 조회"}));
 expect(await screen.findByText("기록된 적용 시도가 없습니다.")).toBeInTheDocument();
 expect(history).toHaveBeenCalledTimes(2);
 expect(retry).not.toHaveBeenCalled();
});
