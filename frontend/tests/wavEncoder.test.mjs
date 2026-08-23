import assert from 'node:assert/strict';
import { encodeWavBase64 } from '../js/utils/wav.js';

const b64ToBytes = (base64) => Uint8Array.from(Buffer.from(base64, 'base64'));

// 1kHz 正弦波 0.1s @16kHz
const sampleRate = 16000;
const samples = new Float32Array(1600);
for (let i = 0; i < samples.length; i += 1) {
    samples[i] = Math.sin((2 * Math.PI * 1000 * i) / sampleRate) * 0.5;
}

const base64 = encodeWavBase64(samples, sampleRate);
const bytes = b64ToBytes(base64);

const ascii = (offset, length) => String.fromCharCode(...bytes.subarray(offset, offset + length));
const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

assert.equal(ascii(0, 4), 'RIFF', 'RIFF 头');
assert.equal(ascii(8, 4), 'WAVE', 'WAVE 头');
assert.equal(ascii(12, 4), 'fmt ', 'fmt 块');
assert.equal(view.getUint32(16, true), 16, 'fmt 块长度 16');
assert.equal(view.getUint16(20, true), 1, 'PCM 编码');
assert.equal(view.getUint16(22, true), 1, '单声道');
assert.equal(view.getUint32(24, true), sampleRate, '采样率 16k 小端');
assert.equal(view.getUint32(28, true), sampleRate * 2, '字节率');
assert.equal(view.getUint16(32, true), 2, '块对齐');
assert.equal(view.getUint16(34, true), 16, '16bit 位深');
assert.equal(ascii(36, 4), 'data', 'data 块');
assert.equal(view.getUint32(4, true), 36 + samples.length * 2, 'RIFF 大小');
assert.equal(view.getUint32(40, true), samples.length * 2, 'data 大小');
assert.equal(bytes.length, 44 + samples.length * 2, '总长度');

// 采样值映射：0 → 0，正幅值 → 正 PCM16
assert.equal(view.getInt16(44, true), 0, '首采样 sin(0)=0');
const quarter = view.getInt16(44 + 2 * 4, true); // 相位 (π/8)*4=π/2 → sin=1 → 0.5*0x7fff
assert.ok(quarter > 16000 && quarter < 16400, `0.5 幅度应约为 16383，实际 ${quarter}`);

// 边界 clamp：+1 → 32767，-1 → -32768
const edge = encodeWavBase64(new Float32Array([1, -1, 2, -2]), sampleRate);
const edgeView = new DataView(b64ToBytes(edge).buffer);
assert.equal(edgeView.getInt16(44, true), 0x7fff);
assert.equal(edgeView.getInt16(46, true), -0x8000);
assert.equal(edgeView.getInt16(48, true), 0x7fff, '超界 +2 应截断');
assert.equal(edgeView.getInt16(50, true), -0x8000, '超界 -2 应截断');

console.log('wav encoder tests passed');
