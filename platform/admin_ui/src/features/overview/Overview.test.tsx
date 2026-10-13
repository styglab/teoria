import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { adminApi } from "../../api/admin";
import { Overview } from "./Overview";
afterEach(()=>{cleanup();vi.restoreAllMocks()});
test("shows operational facts without introductory marketing copy",async()=>{
 vi.spyOn(adminApi,"metadataStatus").mockResolvedValue({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"service",reason:null});
 vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[],total:36,after:null,before:null});
 render(<MemoryRouter><Overview/></MemoryRouter>);
 expect(await screen.findByText("36")).toBeInTheDocument();
 expect(screen.queryByText("TEORIA WORKSPACE")).not.toBeInTheDocument();
 expect(screen.queryByText("데이터에서 업무 의미까지")).not.toBeInTheDocument();
 expect(screen.queryByText("자산을 확인하고, 근거를 검토한 뒤 의미 연결과 변경을 적용합니다.")).not.toBeInTheDocument();
});
