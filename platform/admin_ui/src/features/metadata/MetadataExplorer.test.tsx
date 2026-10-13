import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { adminApi } from "../../api/admin";
import { MetadataExplorer } from "./MetadataExplorer";
beforeEach(()=>{vi.spyOn(adminApi,"metadataSchemas").mockResolvedValue({items:[],total:0,after:null,before:null})});
afterEach(()=>{cleanup();vi.restoreAllMocks();window.sessionStorage.clear()});
test("offers masked token entry and reloads the catalog after authentication",async()=>{
 vi.spyOn(adminApi,"metadataStatus").mockRejectedValueOnce(new Error("Admin API 요청 실패 (401)")).mockResolvedValueOnce({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"teoria_postgresql",reason:null});
 vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[],total:0,after:null,before:null});
 render(<MemoryRouter><MetadataExplorer /></MemoryRouter>);
 await waitFor(()=>expect(screen.getByText("관리자 인증이 필요합니다")).toBeInTheDocument());
 const input=screen.getByLabelText("관리자 토큰");expect(input).toHaveAttribute("type","password");
 fireEvent.change(input,{target:{value:"synthetic-test-token"}});fireEvent.click(screen.getByRole("button",{name:"연결"}));
 await waitFor(()=>expect(screen.getByRole("heading",{name:"전체 자산"})).toBeInTheDocument());
 expect(window.sessionStorage.getItem("teoria-admin-token")).toBe("synthetic-test-token");
 expect(screen.queryByText("synthetic-test-token")).not.toBeInTheDocument();
});
test("shows rejected token feedback and allows a successful retry",async()=>{
 vi.spyOn(adminApi,"metadataStatus")
  .mockRejectedValueOnce(new Error("Admin API 요청 실패 (401)"))
  .mockRejectedValueOnce(new Error("Admin API 요청 실패 (401)"))
  .mockResolvedValueOnce({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"teoria_postgresql",reason:null});
 vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[],total:0,after:null,before:null});
 render(<MemoryRouter><MetadataExplorer /></MemoryRouter>);
 const input=await screen.findByLabelText("관리자 토큰");
 fireEvent.change(input,{target:{value:"incorrect-test-token"}});
 fireEvent.click(screen.getByRole("button",{name:"연결"}));
 expect(await screen.findByRole("alert")).toHaveTextContent("운영 서버가 이 토큰을 거절했습니다");
 expect(window.sessionStorage.getItem("teoria-admin-token")).toBeNull();
 fireEvent.change(input,{target:{value:"valid-test-token"}});
 expect(screen.queryByRole("alert")).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"연결"}));
 expect(await screen.findByRole("heading",{name:"전체 자산"})).toBeInTheDocument();
 expect(window.sessionStorage.getItem("teoria-admin-token")).toBe("valid-test-token");
});
test("keeps the login form visible with disabled controls while connecting",async()=>{
 let resolveStatus!:(value:Awaited<ReturnType<typeof adminApi.metadataStatus>>)=>void;
 vi.spyOn(adminApi,"metadataStatus")
  .mockRejectedValueOnce(new Error("Admin API 요청 실패 (401)"))
  .mockImplementationOnce(()=>new Promise(resolve=>{resolveStatus=resolve}));
 vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[],total:0,after:null,before:null});
 render(<MemoryRouter><MetadataExplorer /></MemoryRouter>);
 const input=await screen.findByLabelText("관리자 토큰");
 fireEvent.change(input,{target:{value:"valid-test-token"}});
 fireEvent.click(screen.getByRole("button",{name:"연결"}));
 expect(screen.getByRole("button",{name:"연결 중…"})).toBeDisabled();
 expect(input).toBeDisabled();
 expect(screen.getByText("관리자 인증이 필요합니다")).toBeInTheDocument();
 resolveStatus({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"teoria_postgresql",reason:null});
 expect(await screen.findByRole("heading",{name:"전체 자산"})).toBeInTheDocument();
});

test.each(['TEORIA_ADMIN_API_TOKEN="synthetic-test-token"', " export TEORIA_ADMIN_API_TOKEN='synthetic-test-token' ", 'Bearer synthetic-test-token'])("accepts pasted credential formatting: %s",async inputValue=>{
 vi.spyOn(adminApi,"metadataStatus").mockRejectedValueOnce(new Error("Admin API 요청 실패 (401)")).mockResolvedValueOnce({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"teoria_postgresql",reason:null});
 vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[],total:0,after:null,before:null});
 render(<MemoryRouter><MetadataExplorer /></MemoryRouter>);
 const input=await screen.findByLabelText("관리자 토큰");
 fireEvent.change(input,{target:{value:inputValue}});
 fireEvent.click(screen.getByRole("button",{name:"토큰 보기"}));
 expect(input).toHaveAttribute("type","text");
 fireEvent.click(screen.getByRole("button",{name:"토큰 숨기기"}));
 expect(input).toHaveAttribute("type","password");
 fireEvent.click(screen.getByRole("button",{name:"연결"}));
 expect(await screen.findByRole("heading",{name:"전체 자산"})).toBeInTheDocument();
 expect(window.sessionStorage.getItem("teoria-admin-token")).toBe("synthetic-test-token");
});

test("searches assets beyond the current server page",async()=>{
 vi.spyOn(adminApi,"metadataStatus").mockResolvedValue({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"teoria_postgresql",reason:null});
 const table={reference:{system:"openmetadata" as const,entity_id:"second-page",entity_type:"table",fully_qualified_name:"service.db.schema.hidden",version:null},name:"hidden",display_name:null,description:"",tags:[],owners:[],domains:[]};
 const pages=vi.spyOn(adminApi,"metadataTables").mockImplementation(async options=>options?.limit===25?{items:[],total:2,after:"first-cursor",before:null}:options?.after?{items:[table],total:2,after:null,before:null}:{items:[],total:2,after:"second-cursor",before:null});
 render(<MemoryRouter><MetadataExplorer /></MemoryRouter>);
 await screen.findByRole("heading",{name:"전체 자산"});
 fireEvent.change(screen.getByRole("textbox",{name:"전체 자산 검색"}),{target:{value:"hidden"}});
 expect(await screen.findByText("hidden")).toBeInTheDocument();
 expect(pages).toHaveBeenCalledWith({after:"second-cursor",limit:100});
});

test("filters authoritative schema results and shows owner names",async()=>{
 vi.spyOn(adminApi,"metadataStatus").mockResolvedValue({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"service",reason:null});
 vi.mocked(adminApi.metadataSchemas).mockResolvedValue({items:[{reference:{system:"openmetadata",entity_id:"schema-id",entity_type:"databaseSchema",fully_qualified_name:"service.db.procurement",version:null},name:"procurement",display_name:null,description:null,tags:[],owners:[],domains:[]}],total:1,after:null,before:null});
 const table={reference:{system:"openmetadata" as const,entity_id:"asset",entity_type:"table",fully_qualified_name:"service.db.procurement.contracts",version:null},name:"contracts",display_name:null,description:"계약 데이터",tags:[],owners:[{name:"Metadata Team"}],domains:[]};
 const pages=vi.spyOn(adminApi,"metadataTables").mockResolvedValue({items:[table],total:1,after:null,before:null});
 render(<MemoryRouter><MetadataExplorer/></MemoryRouter>);
 expect(await screen.findByText("Metadata Team")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:/^procurement/}));
 await waitFor(()=>expect(pages).toHaveBeenCalledWith({after:undefined,limit:100,databaseSchema:"service.db.procurement"}));
 fireEvent.click(screen.getByRole("button",{name:/^소유자 미지정/}));
 expect(await screen.findByText("조건에 맞는 자산이 없습니다.")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"검색·필터 초기화"}));
 expect(await screen.findByText("Metadata Team")).toBeInTheDocument();
});
test("does not report failed asset collection as an empty catalog",async()=>{
 vi.spyOn(adminApi,"metadataStatus").mockResolvedValue({enabled:true,available:true,provider:"openmetadata",base_url:null,database_service:"service",reason:null});
 vi.spyOn(adminApi,"metadataTables").mockRejectedValue(new Error("source unavailable"));
 render(<MemoryRouter><MetadataExplorer/></MemoryRouter>);
 expect(await screen.findByRole("alert")).toHaveTextContent("source unavailable");
 expect(screen.queryByText("등록된 자산이 없습니다.")).not.toBeInTheDocument();
});
