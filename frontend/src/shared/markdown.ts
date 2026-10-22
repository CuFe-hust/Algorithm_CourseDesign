import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import katex from "katex";
import hljs from "highlight.js/lib/common";
const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
  highlight(code, language): string {
    return language && hljs.getLanguage(language)
      ? hljs.highlight(code, { language, ignoreIllegals: true }).value
      : md.utils.escapeHtml(code);
  },
});
function math(source: string, displayMode: boolean) {
  return katex.renderToString(source, {
    displayMode,
    throwOnError: false,
    trust: false,
    strict: "ignore",
    maxExpand: 200,
    maxSize: 10,
  });
}
md.inline.ruler.before("escape", "math", (state, silent) => {
  if (state.src[state.pos] !== "$" || state.src[state.pos + 1] === "$")
    return false;
  let end = state.pos + 1;
  while (
    (end = state.src.indexOf("$", end)) >= 0 &&
    state.src[end - 1] === "\\"
  )
    end++;
  if (
    end < 0 ||
    end === state.pos + 1 ||
    state.src.slice(state.pos, end).includes("\n")
  )
    return false;
  if (!silent) {
    const token = state.push("math_inline", "math", 0);
    token.content = state.src.slice(state.pos + 1, end);
  }
  state.pos = end + 1;
  return true;
});
md.renderer.rules.math_inline = (tokens, i) => math(tokens[i]!.content, false);
md.block.ruler.before("fence", "math_block", (state, start, end, silent) => {
  const begin = state.bMarks[start]! + state.tShift[start]!,
    first = state.src.slice(begin, state.eMarks[start]).trim();
  if (!first.startsWith("$$")) return false;
  let last = start,
    content = first.slice(2);
  if (content.endsWith("$$")) content = content.slice(0, -2);
  else {
    const parts = [content];
    let closed = false;
    while (++last < end) {
      const line = state.src.slice(state.bMarks[last], state.eMarks[last]);
      if (line.trim().endsWith("$$")) {
        parts.push(line.slice(0, line.lastIndexOf("$$")));
        closed = true;
        break;
      }
      parts.push(line);
    }
    if (!closed) return false;
    content = parts.join("\n");
  }
  if (silent) return true;
  const token = state.push("math_block", "math", 0);
  token.content = content;
  token.block = true;
  token.map = [start, last + 1];
  state.line = last + 1;
  return true;
});
md.renderer.rules.math_block = (tokens, i) =>
  `<div class="math-display">${math(tokens[i]!.content, true)}</div>`;
export function renderMarkdown(source: string) {
  return DOMPurify.sanitize(md.render(source), {
    USE_PROFILES: { html: true, mathMl: true, svg: true },
    FORBID_TAGS: ["style", "iframe", "form"],
    FORBID_ATTR: ["srcdoc"],
  });
}
