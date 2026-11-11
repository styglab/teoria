import { ServingDeployments } from "./ServingDeployments";
import { Pipelines } from "../workflow_management/Pipelines";
import { ModelRegistry } from "./ModelRegistry";

export function ModelOperations({
  view,
}: {
  view: "models" | "serving" | "pipelines";
}) {
  if (view === "models") return <ModelRegistry />;
  if (view === "serving") return <ServingDeployments />;
  return <Pipelines />;
}
