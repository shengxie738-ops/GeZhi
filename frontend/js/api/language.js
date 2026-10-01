import request from '../utils/request.js';

const unwrap = (payload) => {
    if (payload && payload.status === 'error') {
        throw new Error(payload.message || '外语训练服务请求失败');
    }
    return payload?.data;
};

export const languageApi = {
    analyzeReading(text, language = 'en') {
        return request('/language/reading/analyze', {
            method: 'POST',
            body: JSON.stringify({ text, language })
        }).then(unwrap);
    },

    explainWord(word, sentence = '') {
        return request('/language/vocabulary/explain', {
            method: 'POST',
            body: JSON.stringify({ word, sentence })
        }).then(unwrap);
    },

    analyzeWriting(text, mode = 'standard', durationSec = 0) {
        return request('/language/writing/analyze', {
            method: 'POST',
            body: JSON.stringify({ text, mode, durationSec })
        }).then(unwrap);
    },

    optimizeWriting(text, mode = 'standard', issues = [], historyId = null) {
        return request('/language/writing/optimize', {
            method: 'POST',
            body: JSON.stringify({ text, mode, issues, historyId })
        }).then(unwrap);
    },

    analyzeSpeaking(payload) {
        return request('/language/speaking/analyze', {
            method: 'POST',
            body: JSON.stringify(payload)
        }).then(unwrap);
    },

    listWordbook() {
        return request('/language/wordbook').then(unwrap);
    },

    addWord(entry) {
        return request('/language/wordbook', {
            method: 'POST',
            body: JSON.stringify(entry)
        }).then(unwrap);
    },

    updateWord(word, patch) {
        return request(`/language/wordbook/${encodeURIComponent(word)}`, {
            method: 'PATCH',
            body: JSON.stringify(patch)
        }).then(unwrap);
    },

    deleteWord(word) {
        return request(`/language/wordbook/${encodeURIComponent(word)}`, {
            method: 'DELETE'
        }).then(unwrap);
    },

    recordProgress(payload) {
        return request('/language/progress', {
            method: 'POST',
            body: JSON.stringify(payload)
        }).then(unwrap);
    },

    getOverview() {
        return request('/language/overview').then(unwrap);
    },

    getInsights() {
        return request('/language/insights').then(unwrap);
    },

    getInsightsAdvice() {
        return request('/language/insights/advice').then(unwrap);
    },

    listWritingHistory() {
        return request('/language/writing/history').then(unwrap);
    },

    getWritingHistory(id) {
        return request(`/language/writing/history/${encodeURIComponent(id)}`).then(unwrap);
    },

    deleteWritingHistory(id) {
        return request(`/language/writing/history/${encodeURIComponent(id)}`, {
            method: 'DELETE'
        }).then(unwrap);
    },

    getReadingProgress() {
        return request('/language/reading/progress').then(unwrap);
    },

    markArticleRead(articleId) {
        return request('/language/reading/progress', {
            method: 'POST',
            body: JSON.stringify({ articleId })
        }).then(unwrap);
    },

    unmarkArticleRead(articleId) {
        return request(`/language/reading/progress/${encodeURIComponent(articleId)}`, {
            method: 'DELETE'
        }).then(unwrap);
    },

    listUserArticles() {
        return request('/language/reading/user-articles').then(unwrap);
    },

    importUserArticle(file) {
        const form = new FormData();
        form.append('file', file);
        return request('/language/reading/user-articles', {
            method: 'POST',
            body: form
        }).then(unwrap);
    },

    renameUserArticle(id, title) {
        return request(`/language/reading/user-articles/${encodeURIComponent(id)}`, {
            method: 'PATCH',
            body: JSON.stringify({ title })
        }).then(unwrap);
    },

    deleteUserArticle(id) {
        return request(`/language/reading/user-articles/${encodeURIComponent(id)}`, {
            method: 'DELETE'
        }).then(unwrap);
    }
};
