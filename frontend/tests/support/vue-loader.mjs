// Repository-shipped Vue 3.3.4. No package resolution or dependency fetch.
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const vueURL = new URL('../../libs/vue.esm-browser.js', import.meta.url).href;
export const vueSource = fileURLToPath(vueURL);
const vueSHA256 = 'ff0c8fcaa207637d20372a08af75cee5dda3d870168a01fa110f3af7eb4500fd';
export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'vue' || specifier === '/libs/vue.esm-browser.js') return { url: vueURL, shortCircuit: true };
  return nextResolve(specifier, context);
}
export async function load(url, context, nextLoad) {
  if (url !== vueURL) return nextLoad(url, context);
  const source = await readFile(vueSource);
  if (createHash('sha256').update(source).digest('hex') !== vueSHA256) throw new Error('OFFLINE_VUE_PIN_MISMATCH');
  return { format: 'module', source: source.toString('utf8'), shortCircuit: true };
}
