/**
 * 浏览器录音 → 16kHz 单声道 WAV(base64) 编码工具。
 * 后端全模态模型要求 input_audio 为 wav（data URI），故浏览器端完成重采样与 PCM16 封装。
 */

const WAV_HEADER_BYTES = 44;

function writeString(view, offset, text) {
    for (let i = 0; i < text.length; i += 1) {
        view.setUint8(offset + i, text.charCodeAt(i));
    }
}

function floatSamplesToInt16(samples) {
    const pcm = new Int16Array(samples.length);
    for (let i = 0; i < samples.length; i += 1) {
        const clamped = Math.max(-1, Math.min(1, samples[i]));
        // 标准 float→PCM16 舍入：正数 x0.7FFF，负数满幅
        pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    }
    return pcm;
}

function bytesToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
    }
    return typeof btoa === 'function'
        ? btoa(binary)
        : Buffer.from(bytes).toString('base64');
}

/** Float32 单声道采样 → 完整 WAV 文件 ArrayBuffer（PCM16 little-endian）。 */
export function encodeWavBuffer(samples, sampleRate) {
    const pcm = floatSamplesToInt16(samples);
    const buffer = new ArrayBuffer(WAV_HEADER_BYTES + pcm.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + pcm.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // fmt chunk size
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true); // byte rate = rate * channels * 2
    view.setUint16(32, 2, true); // block align
    view.setUint16(34, 16, true); // bits per sample
    writeString(view, 36, 'data');
    view.setUint32(40, pcm.length * 2, true);

    let offset = WAV_HEADER_BYTES;
    for (let i = 0; i < pcm.length; i += 1, offset += 2) {
        view.setInt16(offset, pcm[i], true);
    }
    return buffer;
}

export function encodeWavBase64(samples, sampleRate) {
    return bytesToBase64(encodeWavBuffer(samples, sampleRate));
}

/** 把 AudioBuffer 重采样为 16kHz 单声道 Float32Array（需浏览器 AudioContext 环境）。 */
export async function resampleToMono16k(audioBuffer) {
    const targetRate = 16000;
    const length = Math.max(1, Math.ceil(audioBuffer.duration * targetRate));
    const offline = new OfflineAudioContext(1, length, targetRate);
    const source = offline.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return rendered.getChannelData(0);
}
