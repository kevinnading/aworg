/* A small markdown renderer.
 *
 * Deliberately partial. It covers what a Resident actually produces in
 * conversation -- paragraphs, emphasis, headings, lists, quotes, links, and
 * above all code -- and nothing else. Reaching for a full library would mean a
 * build step or a CDN, and an Aworg should work on a machine with no network.
 *
 * Model output is untrusted text. Everything is escaped before any markup is
 * introduced, and code spans are lifted out before emphasis is applied so that
 * asterisks inside code survive intact.
 */

const MD = (() => {
  const ENTITIES = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ENTITIES[c]);
  }

  function inline(text) {
    const spans = [];
    let out = escapeHtml(text);

    // Lift code spans out first; nothing inside them should be interpreted.
    out = out.replace(/`([^`\n]+)`/g, (_, code) => {
      spans.push(code);
      return `\u0000${spans.length - 1}\u0000`;
    });

    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/(^|[^*\w])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/(^|[^_\w])_([^_\n]+)_/g, "$1<em>$2</em>");
    out = out.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );

    return out.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${spans[i]}</code>`);
  }

  function codeBlock(code, language) {
    return (
      '<div class="code">' +
      '<div class="code-head">' +
      `<span class="code-lang">${escapeHtml(language || "text")}</span>` +
      '<button class="code-copy" type="button">Copy</button>' +
      "</div>" +
      `<pre><code>${escapeHtml(code)}</code></pre>` +
      "</div>"
    );
  }

  const BLOCK_START = /^(```|#{1,6}\s|>|\s*[-*+]\s|\s*\d+[.)]\s)/;

  function render(source) {
    const lines = (source || "").split("\n");
    const html = [];
    let listTag = null;
    let i = 0;

    const closeList = () => {
      if (listTag) {
        html.push(`</${listTag}>`);
        listTag = null;
      }
    };

    while (i < lines.length) {
      const line = lines[i];

      // Fenced code. An unclosed fence still renders, which matters while a
      // reply is still streaming in.
      const fence = line.match(/^```\s*([\w+-]*)\s*$/);
      if (fence) {
        closeList();
        const language = fence[1];
        const body = [];
        i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) {
          body.push(lines[i]);
          i++;
        }
        i++; // step past the closing fence, or past the end
        html.push(codeBlock(body.join("\n"), language));
        continue;
      }

      if (!line.trim()) {
        closeList();
        i++;
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        closeList();
        const level = Math.min(heading[1].length + 2, 6); // h1 in a chat bubble is shouting
        html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        i++;
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        closeList();
        html.push("<hr>");
        i++;
        continue;
      }

      if (/^>/.test(line)) {
        closeList();
        const quoted = [];
        while (i < lines.length && /^>/.test(lines[i])) {
          quoted.push(lines[i].replace(/^>\s?/, ""));
          i++;
        }
        html.push(`<blockquote>${render(quoted.join("\n"))}</blockquote>`);
        continue;
      }

      const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (bullet || numbered) {
        const wanted = bullet ? "ul" : "ol";
        if (listTag !== wanted) {
          closeList();
          html.push(`<${wanted}>`);
          listTag = wanted;
        }
        html.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        i++;
        continue;
      }

      closeList();
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) {
        paragraph.push(lines[i]);
        i++;
      }
      html.push(`<p>${inline(paragraph.join("\n"))}</p>`);
    }

    closeList();
    return html.join("");
  }

  return { render, escapeHtml };
})();
