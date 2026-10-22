// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { renderMarkdown } from "./markdown";
describe("safe teaching content", () => {
  it("renders inline/display formulas and highlighted code", () => {
    const html = renderMarkdown(
      "递推式 $T(n)=2T(n/2)+n$\n\n$$\nn^2\n$$\n\n```python\nprint(1)\n```",
    );
    expect(html).toContain("katex");
    expect(html).toContain("katex-display");
    expect(html).toContain("hljs-built_in");
  });
  it("does not execute raw HTML, javascript links or trusted KaTeX commands", () => {
    const html = renderMarkdown(
      '<img src=x onerror="alert(1)">\n<script>alert(1)</script>\n\n[link](javascript:alert(1))\n\n$\\href{javascript:alert(1)}{click}$',
    );
    const dom = new DOMParser().parseFromString(html, "text/html");
    expect(
      dom.querySelector('script,img,[onerror],a[href^="javascript:"]'),
    ).toBeNull();
  });
  it("preserves literal markup in code without creating elements", () => {
    const html = renderMarkdown("```html\n<script>alert(1)</script>\n```");
    expect(
      new DOMParser()
        .parseFromString(html, "text/html")
        .querySelector("script"),
    ).toBeNull();
    expect(html).toContain("&lt;");
  });
});
