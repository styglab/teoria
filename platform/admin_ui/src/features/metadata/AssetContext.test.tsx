import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi, type AssetContextResult } from "../../api/admin";
import { AssetContext } from "./AssetContext";
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const data = {observed_at:"2026-10-13T00:00:00Z",technical:{reference:{fully_qualified_name:"service.db.schema.contracts"},name:"contracts", columns:[],description:"계약 데이터",owners:[],tags:[], database_schema:{name:"public_procurement"}},operations:{status:"not_linked", source:"teoria_data.pipeline_audit"},business:{status:"available",source:"teoria_app",glossary_terms:["Procurement.Contract"],data:{bindings:[],suggestions:[],bindings_truncated:false,suggestions_truncated:false}}} as unknown as AssetContextResult;
test("shows four metadata areas even when a pipeline is not linked",async()=>{
 vi.spyOn(adminApi,"assetContext").mockResolvedValue(data);
 render(<MemoryRouter><AssetContext tableId="first" /></MemoryRouter>);
 await waitFor(()=>expect(screen.getByText("개요 · OpenMetadata")).toBeInTheDocument());
 expect(screen.getByText("명시적으로 연결된 수집 파이프라인이 없습니다.")).toBeInTheDocument();
 expect(screen.getByText("용어: Procurement.Contract")).toBeInTheDocument();
 expect(screen.getByText("거버넌스 · 소유자·태그·검토")).toBeInTheDocument();
 expect(screen.getByRole("link",{name:"의미 연결 관리"})).toHaveAttribute("href","/admin/semantic-model/bindings?asset=service.db.schema.contracts&assetId=first");
});
test("ignores the previous asset's late response",async()=>{
 let resolve!: (value:AssetContextResult)=>void;
 vi.spyOn(adminApi,"assetContext").mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValueOnce({...data,technical:{...data.technical,description:"새 자산"}});
 const view=render(<MemoryRouter><AssetContext tableId="first" /></MemoryRouter>);
 view.rerender(<MemoryRouter><AssetContext tableId="second" /></MemoryRouter>);
 await waitFor(()=>expect(screen.getByText("새 자산")).toBeInTheDocument());resolve(data);
 await waitFor(()=>expect(screen.queryByText("계약 데이터")).not.toBeInTheDocument());
});
