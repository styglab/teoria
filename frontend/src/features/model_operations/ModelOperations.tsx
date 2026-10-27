import { ModelRegistry } from "./ModelRegistry";
import { InferenceServices } from "./InferenceServices";
import { Pipelines } from "../workflow_management/Pipelines";

export function ModelOperations({
  view,
}: {
  view: "models" | "serving" | "pipelines";
}) {
  if (view === "models") return <ModelRegistry />;
  if (view === "serving") return <InferenceServices />;
  return <Pipelines />;
}
