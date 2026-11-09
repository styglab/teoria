import { Pipelines } from "../workflow_management/Pipelines";
import { InferenceServices, type InferenceTest } from "./InferenceServices";
import { ModelRegistry } from "./ModelRegistry";

export function ModelOperations({
  view,
  renderInferenceTest,
}: {
  view: "models" | "serving" | "pipelines";
  renderInferenceTest?: InferenceTest;
}) {
  if (view === "models") return <ModelRegistry />;
  if (view === "serving")
    return <InferenceServices renderTest={renderInferenceTest} />;
  return <Pipelines />;
}
