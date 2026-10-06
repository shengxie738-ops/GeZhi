/** Schema-1 facts intersect fixed shipped adapters. No URLs or dynamic execution. */
const adapters = new Map([
    ['plugin_arxiv', { implementation: 'backend-proxy', source_key: 'arxiv' }],
    ['plugin_openalex', { implementation: 'backend-proxy', source_key: 'openalex' }],
    ['plugin_crossref', { implementation: 'backend-proxy', source_key: 'crossref' }],
    ['plugin_europepmc', { implementation: 'client-direct', source_key: 'europepmc' }],
    ['plugin_peer_review', { implementation: 'prompt-only', skill_id: 'academic-review' }],
    ...['plugin_semanticscholar', 'plugin_zotero', 'plugin_python_sandbox', 'plugin_chart_renderer'].map(id => [id, { implementation: 'metadata-only' }])
]);
const parsedFacts = new WeakMap();
const common = ['plugin_id', 'implementation', 'implemented', 'configuration_status', 'live_verified'];
function record(value, keys) {
    if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) return false;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    return Reflect.ownKeys(descriptors).length === keys.length && keys.every(key => Object.hasOwn(descriptors, key)
        && Object.hasOwn(descriptors[key], 'value') && descriptors[key].enumerable);
}
function exactList(value, expected) {
    if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length !== expected.length) return false;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    return Reflect.ownKeys(descriptors).length === expected.length + 1 && expected.every((item, i) =>
        Object.hasOwn(descriptors[String(i)] || {}, 'value') && descriptors[String(i)].value === item);
}
export function registeredPluginId(value) {
    if (typeof value === 'string') return adapters.has(value) ? value : '';
    if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) return '';
    const id = Object.getOwnPropertyDescriptor(value, 'id');
    return id && Object.hasOwn(id, 'value') && adapters.has(id.value) ? id.value : '';
}
export function isRegisteredPaperSource(value) {
    return Boolean(adapters.get(registeredPluginId(value))?.source_key);
}
export function parseStudentWorkCapabilities(raw) {
    try {
        if (!record(raw, ['schema_version', 'scope', 'revision', 'items']) || raw.schema_version !== 1
            || raw.scope !== 'student-work' || typeof raw.revision !== 'string' || !/^[a-f0-9]{64}$/.test(raw.revision)
            || !Array.isArray(raw.items) || Object.getPrototypeOf(raw.items) !== Array.prototype
            || raw.items.length !== adapters.size) return null;
        const rows = Object.getOwnPropertyDescriptors(raw.items), entries = new Map();
        if (Reflect.ownKeys(rows).length !== raw.items.length + 1) return null;
        for (let i = 0; i < raw.items.length; i++) {
            if (!Object.hasOwn(rows[String(i)] || {}, 'value')) return null;
            const item = rows[String(i)].value;
            if (!item || Object.getPrototypeOf(item) !== Object.prototype) return null;
            const fields = Object.getOwnPropertyDescriptors(item);
            if (Reflect.ownKeys(fields).some(key => typeof key !== 'string' || !Object.hasOwn(fields[key], 'value'))) return null;
            const adapter = adapters.get(item.plugin_id);
            if (!adapter || entries.has(item.plugin_id) || typeof item.live_verified !== 'boolean') return null;
            if (item.implementation === 'metadata-only') {
                if (!record(item, common) || item.implemented !== false || item.configuration_status !== 'not_applicable') return null;
            } else if (item.implementation === 'prompt-only') {
                if (!record(item, [...common, 'skill_id', 'policy_version', 'allowed_modes', 'requirements'])
                    || adapter.implementation !== item.implementation || item.skill_id !== adapter.skill_id
                    || item.policy_version !== 1 || item.implemented !== true || item.configuration_status !== 'checked_on_execution'
                    || !exactList(item.allowed_modes, ['chat', 'paper']) || !exactList(item.requirements, ['owned_model'])) return null;
            } else {
                if (!record(item, [...common, 'source_key', 'adapter_version', 'allowed_modes'])
                    || !['backend-proxy', 'client-direct'].includes(item.implementation)
                    || adapter.implementation !== item.implementation || item.source_key !== adapter.source_key
                    || item.adapter_version !== 1 || item.implemented !== true || item.configuration_status !== 'not_required'
                    || !exactList(item.allowed_modes, ['paper_search'])) return null;
            }
            const frozen = Object.freeze({ ...item,
                ...(item.allowed_modes ? { allowed_modes: Object.freeze([...item.allowed_modes]) } : {}),
                ...(item.requirements ? { requirements: Object.freeze([...item.requirements]) } : {}) });
            entries.set(item.plugin_id, frozen);
        }
        const facts = Object.freeze({ revision: raw.revision });
        parsedFacts.set(facts, entries);
        return facts;
    } catch { return null; }
}
export function capabilityForPlugin(facts, plugin) {
    return parsedFacts.get(facts)?.get(registeredPluginId(plugin)) || null;
}
