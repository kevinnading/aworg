/* Syntax highlighting.
 *
 * Hand-rolled for the same reason as the markdown renderer: no build step, no
 * CDN, and an Aworg that works on a machine with no network. It covers the
 * languages a Resident is most likely to write and degrades to plain escaped
 * text for anything else, which is the correct failure -- unhighlighted code
 * is still perfectly readable code.
 *
 * Each grammar is an ordered set of rules compiled into one alternation.
 * Order is meaningful: comments and strings must match before keywords, or a
 * keyword inside a string would be coloured as code.
 */

const HL = (() => {
  const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const escapeHtml = (text) => text.replace(/[&<>"']/g, (c) => ENTITIES[c]);

  const GRAMMARS = {
    python: {
      comment: /#[^\n]*/,
      string: /"""[\s\S]*?"""|'''[\s\S]*?'''|[rbfu]{0,2}"(?:\\[\s\S]|[^"\\])*"|[rbfu]{0,2}'(?:\\[\s\S]|[^'\\])*'/,
      decorator: /@[\w.]+/,
      keyword: /\b(?:def|class|return|if|elif|else|for|while|in|not|and|or|is|import|from|as|with|try|except|finally|raise|pass|break|continue|lambda|yield|global|nonlocal|assert|del|async|await|None|True|False|self)\b/,
      builtin: /\b(?:print|len|range|open|str|int|float|list|dict|set|tuple|bool|type|isinstance|super|enumerate|zip|map|filter|sorted|sum|min|max|abs|any|all|repr|format|hasattr|getattr|setattr)\b/,
      number: /\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b/,
      fn: /\b[A-Za-z_]\w*(?=\s*\()/,
    },

    javascript: {
      comment: /\/\/[^\n]*|\/\*[\s\S]*?\*\//,
      string: /`(?:\\[\s\S]|[^`\\])*`|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/,
      keyword: /\b(?:const|let|var|function|return|if|else|for|while|class|extends|new|await|async|import|from|export|default|try|catch|finally|throw|typeof|instanceof|delete|this|null|undefined|true|false|switch|case|break|continue|do|in|of|yield|static|get|set)\b/,
      builtin: /\b(?:console|document|window|Math|JSON|Object|Array|String|Number|Boolean|Promise|Map|Set|Error|fetch|setTimeout|setInterval|require|module)\b/,
      number: /\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b/,
      fn: /\b[A-Za-z_$][\w$]*(?=\s*\()/,
    },

    json: {
      key: /"(?:\\[\s\S]|[^"\\])*"(?=\s*:)/,
      string: /"(?:\\[\s\S]|[^"\\])*"/,
      keyword: /\b(?:true|false|null)\b/,
      number: /-?\b\d+\.?\d*(?:[eE][+-]?\d+)?\b/,
    },

    html: {
      comment: /<!--[\s\S]*?-->/,
      doctype: /<!DOCTYPE[^>]*>/i,
      tag: /<\/?[A-Za-z][\w:-]*|\/?>/,
      string: /"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/,
      attr: /\b[A-Za-z_:][\w:.-]*(?=\s*=)/,
    },

    css: {
      comment: /\/\*[\s\S]*?\*\//,
      string: /"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/,
      decorator: /@[\w-]+/,
      key: /[\w-]+(?=\s*:)/,
      builtin: /#[0-9a-fA-F]{3,8}\b/,
      number: /\b\d+\.?\d*(?:px|rem|em|%|vh|vw|s|ms|deg|fr)?\b/,
    },

    bash: {
      comment: /#[^\n]*/,
      string: /"(?:\\[\s\S]|[^"\\])*"|'[^']*'/,
      variable: /\$\w+|\$\{[^}]*\}/,
      keyword: /\b(?:if|then|else|elif|fi|for|while|do|done|case|esac|function|return|export|source|local|set|echo|cd|ls|rm|mkdir|cp|mv|cat|grep|sed|awk|curl|git|python|pip|npm|sudo)\b/,
      flag: /(?<=\s)--?[\w-]+/,
      number: /\b\d+\b/,
    },

    sql: {
      comment: /--[^\n]*|\/\*[\s\S]*?\*\//,
      string: /'(?:''|[^'])*'/,
      keyword: /\b(?:SELECT|FROM|WHERE|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|INDEX|DROP|ALTER|JOIN|LEFT|RIGHT|INNER|OUTER|ON|GROUP|ORDER|BY|HAVING|LIMIT|OFFSET|AS|AND|OR|NOT|NULL|PRIMARY|KEY|FOREIGN|REFERENCES|DEFAULT|UNIQUE|DISTINCT|COUNT|SUM|AVG|MIN|MAX)\b/i,
      number: /\b\d+\.?\d*\b/,
    },
  };

  const ALIASES = {
    py: "python", python3: "python",
    js: "javascript", mjs: "javascript", cjs: "javascript",
    ts: "javascript", typescript: "javascript", jsx: "javascript", tsx: "javascript",
    node: "javascript",
    htm: "html", xml: "html", vue: "html",
    scss: "css", sass: "css", less: "css",
    sh: "bash", shell: "bash", zsh: "bash", console: "bash", terminal: "bash",
    postgres: "sql", postgresql: "sql", sqlite: "sql", mysql: "sql",
  };

  function normalize(language) {
    const name = (language || "").trim().toLowerCase();
    return ALIASES[name] || name;
  }

  const compiled = new Map();

  function grammarFor(name) {
    if (compiled.has(name)) return compiled.get(name);
    const rules = GRAMMARS[name];
    const regex = rules
      ? new RegExp(
          Object.entries(rules)
            .map(([kind, rule]) => `(?<${kind}>${rule.source})`)
            .join("|"),
          "g"
        )
      : null;
    compiled.set(name, regex);
    return regex;
  }

  function highlight(code, language) {
    const regex = grammarFor(normalize(language));
    if (!regex) return escapeHtml(code);

    let out = "";
    let last = 0;
    let match;
    regex.lastIndex = 0;

    while ((match = regex.exec(code)) !== null) {
      if (match[0] === "") {
        regex.lastIndex++; // never let a zero-width match stall the scan
        continue;
      }
      const kind = Object.keys(match.groups).find((k) => match.groups[k] !== undefined);
      out += escapeHtml(code.slice(last, match.index));
      out += `<span class="t-${kind}">${escapeHtml(match[0])}</span>`;
      last = match.index + match[0].length;
    }

    return out + escapeHtml(code.slice(last));
  }

  const supports = (language) => Boolean(GRAMMARS[normalize(language)]);

  return { highlight, normalize, supports, escapeHtml };
})();
