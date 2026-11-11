import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ManualRunDialog } from "./ManualRunDialog";
import { workflowsApi } from "./api";

afterEach(()=>{cleanup();vi.restoreAllMocks();});
test("submits a portable image execution and reuses the idempotency key after an uncertain response",async()=>{
  const run=vi.spyOn(workflowsApi,"run").mockRejectedValueOnce(Error("connection interrupted")).mockResolvedValue({flow_run_id:"run-1",name:"training"});
  const started=vi.fn();
  render(<ManualRunDialog pipeline={{id:"model-train",name:"모델 이미지 학습",input_kind:"training",available:true,paused:false,deployment_id:"registered",requires_model_version:false}} onClose={()=>{}} onStarted={started}/>);
  const execution={image:"registry.example.com/model@sha256:abc",command:["python","train.py"],resources:{cpu:2,memory_mib:2048}};
  fireEvent.change(screen.getByRole("textbox"),{target:{value:JSON.stringify(execution)}});
  fireEvent.click(screen.getByRole("button",{name:"실행 요청"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("connection interrupted");
  fireEvent.click(screen.getByRole("button",{name:"실행 요청"}));
  await waitFor(()=>expect(started).toHaveBeenCalledWith("run-1"));
  expect(run.mock.calls[0][2]).toEqual({execution});
  expect(run.mock.calls[1][1]).toEqual(run.mock.calls[0][1]);
});
