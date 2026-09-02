import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    PROJECT_DEFAULT_ID,
    PROJECT_TUTOR_ID,
    PROJECT_RAG_ID,
    PROJECT_PAPER_ID,
    INITIAL_SYSTEM_PROJECTS,
    groupMessagesIntoConversations,
    groupConversationsByProjects
} from '../js/utils/conversations.js';

test('TaskTree: groupConversationsByProjects should organize conversations under default, tutor, rag, and paper projects', () => {
    const messages = [
        { id: 1, senderType: 'user', content: '写一篇操作系统论文大纲', mode: 'chat' },
        { id: 2, senderType: 'agent', content: '大纲如下...', mode: 'chat' },
        { id: 3, senderType: 'user', content: '数据结构当中栈与队列的区别', mode: 'tutor' },
        { id: 4, senderType: 'agent', content: '栈（LIFO）与队列（FIFO）...', mode: 'tutor' },
        { id: 5, senderType: 'user', content: '检索计算机组成原理课件', mode: 'rag' },
        { id: 6, senderType: 'agent', content: '根据知识库检索结果...', mode: 'rag' },
        { id: 7, senderType: 'user', content: '查询 Transformer 论文', mode: 'paper' },
        { id: 8, senderType: 'agent', content: 'Transformer 论文核心贡献包括...', mode: 'paper' },
    ];

    const tree = groupConversationsByProjects(messages, INITIAL_SYSTEM_PROJECTS);
    assert.equal(tree.length, 4, '应返回 4 个系统核心项目分组');

    const defaultProj = tree.find(p => p.id === PROJECT_DEFAULT_ID);
    assert.ok(defaultProj, '应包含默认任务分组');
    assert.equal(defaultProj.tasks.length, 1, '默认任务下有 1 个小任务');
    assert.equal(defaultProj.tasks[0].title, '写一篇操作系统论文大纲');

    const tutorProj = tree.find(p => p.id === PROJECT_TUTOR_ID);
    assert.ok(tutorProj, '应包含引导式学习分组');
    assert.equal(tutorProj.tasks.length, 1, '引导式学习下有 1 个小任务');

    const ragProj = tree.find(p => p.id === PROJECT_RAG_ID);
    assert.ok(ragProj, '应包含知识库检索分组');
    assert.equal(ragProj.tasks.length, 1, '知识库检索下有 1 个小任务');

    const paperProj = tree.find(p => p.id === PROJECT_PAPER_ID);
    assert.ok(paperProj, '应包含论文查询分组');
    assert.equal(paperProj.name, '论文查询');
    assert.equal(paperProj.tasks.length, 1, '论文查询下有 1 个小任务');
    assert.equal(paperProj.tasks[0].title, '查询 Transformer 论文');
});

test('TaskTree: should support collapsing and expanding states for all four groups', () => {
    const projects = [
        { id: PROJECT_DEFAULT_ID, name: '默认任务', expanded: true },
        { id: PROJECT_TUTOR_ID, name: '引导式学习', expanded: false },
        { id: PROJECT_RAG_ID, name: '知识库检索', expanded: true },
        { id: PROJECT_PAPER_ID, name: '论文查询', expanded: false }
    ];

    const tree = groupConversationsByProjects([], projects);
    const defaultProj = tree.find(p => p.id === PROJECT_DEFAULT_ID);
    const tutorProj = tree.find(p => p.id === PROJECT_TUTOR_ID);
    const ragProj = tree.find(p => p.id === PROJECT_RAG_ID);
    const paperProj = tree.find(p => p.id === PROJECT_PAPER_ID);

    assert.equal(defaultProj.expanded, true, '默认任务应为展开状态');
    assert.equal(tutorProj.expanded, false, '引导式学习应为折叠状态');
    assert.equal(ragProj.expanded, true, '知识库检索应为展开状态');
    assert.equal(paperProj.expanded, false, '论文查询应为折叠状态');
});
