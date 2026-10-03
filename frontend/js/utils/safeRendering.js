/** Local, fail-closed rendering boundary for all untrusted text.
 * Rich Markdown is intentionally displayed literally. Do not send this output
 * through a Markdown parser, entity decoder, or another HTML-producing step.
 * Only fixed <br> tags are emitted; CDN availability cannot change safety.
 */
export function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]));
}

// Stored HTML is not trusted. Preserve it as visible text, never active markup.
export function sanitizeHtml(value) {
    return escapeHtml(value);
}

export function renderMarkdown(value) {
    return escapeHtml(value).replace(/\r\n|\r|\n/g, '<br>');
}
