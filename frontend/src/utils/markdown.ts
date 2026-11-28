/**
 * Zero-dependency XSS-safe Markdown renderer for Strategy Ops Copilot messages.
 * Escapes raw HTML first, then formats headings, tables, fenced code blocks,
 * blockquotes, lists, bold/italic, inline code, and safe https? links.
 */

function escapeHtml(raw: string): string {
  return String(raw || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeHref(rawHref: string): string {
  const trimmed = rawHref.trim()
  if (/^https?:\/\/[^\s"'<>]+$/i.test(trimmed)) return trimmed
  if (/^\/[^\s"'<>]*$/.test(trimmed)) return trimmed
  return '#'
}

function renderInline(escapedLine: string): string {
  // Preserve inline code spans first so markers inside backticks are not re-parsed
  const codes: string[] = []
  let s = escapedLine.replace(/`([^`\n]+)`/g, (_m, code) => {
    const idx = codes.length
    codes.push(`<code>${code}</code>`)
    return `\u0000CODE${idx}\u0000`
  })

  // Markdown links [label](url) — allow only safe http(s) or root-relative paths
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, label, href) => {
    const safeUrl = sanitizeHref(href)
    if (safeUrl === '#') return label
    const externalAttrs = safeUrl.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : ''
    return `<a href="${safeUrl}"${externalAttrs}>${label}</a>`
  })

  // Bold & italic
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>')

  // Restore inline code
  return s.replace(/\u0000CODE(\d+)\u0000/g, (_m, idx) => codes[Number(idx)] ?? '')
}

function isTableSeparator(line: string): boolean {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  if (!trimmed.includes('-')) return false
  return trimmed.split('|').every((cell) => /^:?-{2,}:?$/.test(cell.trim()))
}

function splitTableRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim())
}

export function renderSafeMarkdown(input: string): string {
  const normalized = String(input || '').replace(/\r\n/g, '\n').trim()
  if (!normalized) return ''

  const lines = normalized.split('\n')
  const out: string[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Blank line
    if (!trimmed) {
      i += 1
      continue
    }

    // Fenced code block ```lang
    if (trimmed.startsWith('```')) {
      const langRaw = trimmed.slice(3).trim().replace(/[^a-zA-Z0-9_-]/g, '')
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(escapeHtml(lines[i]))
        i += 1
      }
      if (i < lines.length) i += 1
      const cls = langRaw ? ` class="language-${langRaw}"` : ''
      out.push(`<pre><code${cls}>${codeLines.join('\n')}</code></pre>`)
      continue
    }

    // Markdown table: header + separator + body rows
    if (
      line.includes('|') &&
      i + 1 < lines.length &&
      lines[i + 1].includes('|') &&
      isTableSeparator(lines[i + 1])
    ) {
      const headers = splitTableRow(line).map((h) => `<th>${renderInline(escapeHtml(h))}</th>`)
      i += 2
      const rows: string[] = []
      while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
        const cells = splitTableRow(lines[i]).map((c) => `<td>${renderInline(escapeHtml(c))}</td>`)
        rows.push(`<tr>${cells.join('')}</tr>`)
        i += 1
      }
      const bodyHtml = rows.length ? `<tbody>${rows.join('')}</tbody>` : ''
      out.push(`<table><thead><tr>${headers.join('')}</tr></thead>${bodyHtml}</table>`)
      continue
    }

    // Headings (#..#### -> h2/h3/h4 within message bubble hierarchy)
    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (headingMatch) {
      const level = Math.min(4, Math.max(2, headingMatch[1].length + 1))
      out.push(`<h${level}>${renderInline(escapeHtml(headingMatch[2]))}</h${level}>`)
      i += 1
      continue
    }

    // Blockquote
    if (trimmed.startsWith('>')) {
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(renderInline(escapeHtml(lines[i].trim().replace(/^>\s?/, ''))))
        i += 1
      }
      out.push(`<blockquote><p>${quoteLines.join('<br />')}</p></blockquote>`)
      continue
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      out.push('<hr />')
      i += 1
      continue
    }

    // Unordered list
    if (/^[-*+]\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(`<li>${renderInline(escapeHtml(lines[i].trim().replace(/^[-*+]\s+/, '')))}</li>`)
        i += 1
      }
      out.push(`<ul>${items.join('')}</ul>`)
      continue
    }

    // Ordered list
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(`<li>${renderInline(escapeHtml(lines[i].trim().replace(/^\d+\.\s+/, '')))}</li>`)
        i += 1
      }
      out.push(`<ol>${items.join('')}</ol>`)
      continue
    }

    // Paragraph (consume consecutive plain text lines until next block syntax)
    const paraLines: string[] = []
    while (i < lines.length) {
      const cur = lines[i]
      const curTrim = cur.trim()
      if (!curTrim) break
      if (
        curTrim.startsWith('```') ||
        curTrim.startsWith('>') ||
        /^(#{1,4})\s+/.test(curTrim) ||
        /^[-*+]\s+/.test(curTrim) ||
        /^\d+\.\s+/.test(curTrim) ||
        /^(-{3,}|\*{3,})$/.test(curTrim)
      ) {
        break
      }
      if (
        cur.includes('|') &&
        i + 1 < lines.length &&
        lines[i + 1].includes('|') &&
        isTableSeparator(lines[i + 1])
      ) {
        break
      }
      paraLines.push(renderInline(escapeHtml(cur)))
      i += 1
    }
    if (paraLines.length) {
      out.push(`<p>${paraLines.join('<br />')}</p>`)
    }
  }

  return out.join('')
}
