import { chromium } from "playwright";

const baseUrl = process.env.TEORIA_VERIFY_BASE_URL || "http://localhost:8081";
const token = process.env.TEORIA_ADMIN_API_TOKEN;
if (!token)
  throw new Error("Set TEORIA_ADMIN_API_TOKEN before verifying the deployment");
const parsedUrl = new URL(baseUrl);
if (
  !["http:", "https:"].includes(parsedUrl.protocol) ||
  parsedUrl.username ||
  parsedUrl.password
) {
  throw new Error(
    "TEORIA_VERIFY_BASE_URL must be an HTTP(S) URL without credentials",
  );
}
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  // Exercise the login dialog itself before tracking authenticated page requests.
  await page.goto(`${baseUrl.replace(/\/$/, "")}/admin/overview`);
  await page
    .getByRole("button", { name: "관리자 연결", exact: true })
    .first()
    .click();
  await page.getByLabel("관리자 토큰").fill(token);
  await page.getByRole("button", { name: "연결", exact: true }).click();
  await page
    .getByRole("button", { name: "로그아웃", exact: true })
    .waitFor({ timeout: 30000 });
  console.log("PASS browser administrator login");
  const errors = [];
  page.on("pageerror", () => errors.push("JavaScript error"));
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED")
      errors.push("Network request failed");
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      errors.push(
        `HTTP ${response.status()}: ${new URL(response.url()).pathname}`,
      );
    }
  });
  const pages = [
    ["data-catalog", "전체 자산 검색"],
    ["semantic-model/ontology", "온톨로지 검색"],
    ["semantic-model/bindings", "의미 연결 검색"],
    ["changes/review", null],
    ["governance", null],
    ["overview", null],
    ["developer/capabilities", "기능 계약 검색"],
    ["operations", null],
    ["developer/ask", "업무 질문"],
  ];
  if (process.env.TEORIA_VERIFY_TABLE_FQN) {
    pages.push([
      "data-catalog/assets/" +
        encodeURIComponent(process.env.TEORIA_VERIFY_TABLE_FQN),
      null,
    ]);
  }
  for (const [route, input] of pages) {
    const response = await page.goto(
      `${baseUrl.replace(/\/$/, "")}/admin/${route}`,
    );
    if (response?.status() !== 200)
      throw new Error("UI route did not return HTTP 200");
    await page
      .getByRole("button", { name: "로그아웃", exact: true })
      .waitFor({ timeout: 30000 });
    if (input)
      await page
        .getByRole("textbox", { name: input, exact: true })
        .waitFor({ timeout: 30000 });
    await page.waitForLoadState("networkidle");
    if (route.startsWith("data-catalog/assets/")) {
      await page
        .getByRole("heading", { name: "자산 진단", exact: true })
        .waitFor();
    }
    if (await page.getByRole("alert").count())
      errors.push(`Visible error on ${route}`);
    console.log("PASS browser", route);
  }
  if (errors.length) throw new Error([...new Set(errors)].join("\n"));
  console.log("PASS deployed UI; no JavaScript, network or HTTP errors");
} finally {
  await browser.close();
}
