import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import * as http from "../../api/http_client";
import { serverQueryClient } from "../../api/server_queries";
import { workflowsApi } from "../workflow_management/api";
import { ServingDeployments } from "./ServingDeployments";

beforeEach(() => { serverQueryClient.clear(); });
afterEach(() => {cleanup(); vi.restoreAllMocks();});
function setup() {
  vi.spyOn(http, "getJson").mockResolvedValue({items:[{
    deployment_id:"forecast", backend:"docker",status:"ready",health:"ok",endpoint:"http://internal:8080",prefect_run_id:"previous-run",
    specification:{model_name:"forecast",model_version:2,image:"registry.example.com/model@sha256:abc"},
    previous_specification:{deployment_id:"forecast",model_name:"forecast",model_version:1},
  }]});
  render(<MemoryRouter><ServingDeployments /></MemoryRouter>);
}
test("sends generic inference to the selected authenticated deployment endpoint", async () => {
  const predict=vi.spyOn(http,"postJson").mockResolvedValue({prediction:42});setup();
  const input=await screen.findByRole("textbox",{name:"추론 입력(JSON)"});
  fireEvent.change(input,{target:{value:'{"values":[1,2]}'}});
  fireEvent.click(screen.getByRole("button",{name:"추론 요청"}));
  await waitFor(()=>expect(predict).toHaveBeenCalledWith("/model-operations/deployments/forecast/predict",{values:[1,2]}));
  expect(await screen.findByText(/"prediction": 42/)).toBeInTheDocument();
});
test("rolls back using the recorded previous specification without retraining", async () => {
  const run=vi.spyOn(workflowsApi,"run").mockResolvedValue({flow_run_id:"rollback-run",name:"rollback"});setup();
  fireEvent.click(await screen.findByRole("button",{name:"이전 설정으로 배포"}));
  await waitFor(()=>expect(run).toHaveBeenCalledWith("model-deploy",expect.any(String),{execution:{deployment_id:"forecast",model_name:"forecast",model_version:1}}));
  expect(await screen.findByText("실행 요청: rollback-run")).toBeInTheDocument();
});
