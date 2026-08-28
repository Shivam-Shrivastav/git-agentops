// Tiny, dependency-free Markdown renderer for assistant messages.
//
// Handles the subset the github-agent emits: headings, ordered/unordered
// lists (with nested indentation), bold, italic, inline code, and links.
// Intentionally minimal — not a full CommonMark parser. Swap for
// react-markdown + remark-gfm later if richer input appears.

import { Fragment } from "react";

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const UL_RE = /^(\s*)[-*]\s+(.*)$/;
const OL_RE = /^(\s*)(\d+)\.\s+(.*)$/;

const INLINE_PATTERNS = [
  {
    re: /\*\*([^*]+?)\*\*/,
    wrap: (m, k) => <strong key={k}>{m[1]}</strong>,
  },
  {
    re: /`([^`]+?)`/,
    wrap: (m, k) => (
      <code key={k} className="md-code">
        {m[1]}
      </code>
    ),
  },
  {
    re: /\[([^\]]+?)\]\(([^)]+?)\)/,
    wrap: (m, k) => (
      <a
        key={k}
        className="md-a"
        href={m[2]}
        target="_blank"
        rel="noopener noreferrer"
      >
        {m[1]}
      </a>
    ),
  },
  {
    re: /\*([^*]+?)\*/,
    wrap: (m, k) => <em key={k}>{m[1]}</em>,
  },
];


function renderInline(text, keyPrefix) {
  if (!text) {
    return null;
  }
  const nodes = [];
  let rest = text;
  let key = 0;

  while (rest.length) {
    let best = null;
    for (const p of INLINE_PATTERNS) {
      const m = p.re.exec(rest);
      if (m && (best === null || m.index < best.m.index)) {
        best = { m, p };
      }
    }
    if (!best) {
      nodes.push(
        <Fragment key={`${keyPrefix}-${key++}`}>{rest}</Fragment>,
      );
      break;
    }
    const { m, p } = best;
    if (m.index > 0) {
      nodes.push(
        <Fragment key={`${keyPrefix}-${key++}`}>
          {rest.slice(0, m.index)}
        </Fragment>,
      );
    }
    nodes.push(p.wrap(m, `${keyPrefix}-${key++}`));
    rest = rest.slice(m.index + m[0].length);
  }
  return nodes;
}


function renderMultilineInline(text, keyPrefix) {
  const lines = text.split("\n");
  const out = [];
  lines.forEach((ln, idx) => {
    out.push(
      <Fragment key={`${keyPrefix}-l${idx}`}>
        {renderInline(ln, `${keyPrefix}-i${idx}`)}
      </Fragment>,
    );
    if (idx < lines.length - 1) {
      out.push(<br key={`${keyPrefix}-br${idx}`} />);
    }
  });
  return out;
}


function parseBlocks(text) {
  const lines = (text || "").split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i += 1;
      continue;
    }

    const h = HEADING_RE.exec(line);
    if (h) {
      blocks.push({ type: "heading", level: h[1].length, text: h[2] });
      i += 1;
      continue;
    }

    if (UL_RE.test(line) || OL_RE.test(line)) {
      const items = [];
      while (i < lines.length) {
        const l = lines[i];
        if (l.trim() === "") {
          // A blank line still belongs to the list if the next non-blank
          // line is another list item.
          let j = i + 1;
          while (j < lines.length && lines[j].trim() === "") j += 1;
          if (j < lines.length && (UL_RE.test(lines[j]) || OL_RE.test(lines[j]))) {
            i = j;
            continue;
          }
          break;
        }
        const u = UL_RE.exec(l);
        if (u) {
          items.push({ ordered: false, indent: u[1].length, text: u[2] });
          i += 1;
          continue;
        }
        const o = OL_RE.exec(l);
        if (o) {
          items.push({ ordered: true, indent: o[1].length, num: o[2], text: o[3] });
          i += 1;
          continue;
        }
        // Continuation line of the previous item.
        if (items.length) {
          items[items.length - 1].text += "\n" + l.replace(/^\s{0,4}/, "");
          i += 1;
          continue;
        }
        break;
      }
      blocks.push({ type: "list", items });
      continue;
    }

    // Paragraph: contiguous non-blank, non-list, non-heading lines.
    const para = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") break;
      if (HEADING_RE.test(l) || UL_RE.test(l) || OL_RE.test(l)) break;
      para.push(l);
      i += 1;
    }
    blocks.push({ type: "paragraph", text: para.join("\n") });
  }

  return blocks;
}


function renderBlock(b, i) {
  if (b.type === "heading") {
    const Tag = `h${Math.min(6, b.level + 3)}`;
    return (
      <Tag key={i} className="md-heading">
        {renderInline(b.text, `h${i}`)}
      </Tag>
    );
  }
  if (b.type === "paragraph") {
    return (
      <p key={i} className="md-p">
        {renderMultilineInline(b.text, `p${i}`)}
      </p>
    );
  }
  if (b.type === "list") {
    return (
      <div key={i} className="md-list">
        {b.items.map((it, idx) => (
          <div
            key={idx}
            className="md-li"
            style={{ marginLeft: `${it.indent * 1.1}em` }}
          >
            <span className="md-marker">
              {it.ordered ? `${it.num}.` : "•"}
            </span>
            <span className="md-li-text">
              {renderMultilineInline(it.text, `li${i}-${idx}`)}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
}


function Markdown({ text }) {
  const blocks = parseBlocks(text || "");
  return <div className="md">{blocks.map((b, i) => renderBlock(b, i))}</div>;
}


export default Markdown;