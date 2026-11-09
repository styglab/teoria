import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { resetServerQueries } from "./api/server_queries";

afterEach(() => {
  cleanup();
  resetServerQueries();
});
