import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DetailPanel } from "./DetailPanel";

describe("DetailPanel", () => {
  it("renders link type details", () => {
    render(<DetailPanel item={{
      id: "company.legal_entity_has_address",
      ontology: "company",
      link_type: "legal_entity_has_address",
      name: "법인 주소 관계",
      description: "법인과 주소를 연결한다.",
      source: "company.legal_entity",
      target: "company.postal_address",
    }} onClose={() => undefined} />);

    expect(screen.getByText("LINK TYPE")).toBeTruthy();
    expect(screen.getByText("company.legal_entity")).toBeTruthy();
    expect(screen.getByText("company.postal_address")).toBeTruthy();
  });
});
