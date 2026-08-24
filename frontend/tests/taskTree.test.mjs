import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    DEFAULT_PROJECT_ID,
    groupMessagesIntoConversations,
    groupConversationsByProjects
} from '../js/utils/conversations.js';

test('TaskTree: groupConversationsByProjects should organize conversations under projects', () => {
    const projects = [
        { id: 'proj-default', name: '默认项目', expanded: true },
        { id: 'proj-data-struct', name: '数据结构与算法', expanded: true }
    ];

    const messages = [
        { id: 1, senderType: 'user', content: '什么是线性表？', projectId: 'proj-default' },
        { id: 2, senderType: 'agent', content: '线性表是...', projectId: 'proj-default' },
        { id: 3, senderType: 'user', content: '什么是二叉树？', projectId: 'proj-data-struct' },
        { id: 4, senderType: 'agent', content: '二叉树是...', projectId: 'proj-data-struct' },
        { id: 5, senderType: 'user', content: '堆排序如何实现？', projectId: 'proj-data-struct' },
        { id: 6, senderType: 'agent', content: '堆排序原理...', projectId: 'proj-data-struct' },
    ];

    const tree = groupConversationsByProjects(messages, projects);
    assert.equal(tree.length, 2, '应返回 2 个项目分组');

    const defaultProj = tree.find(p => p.id === 'proj-default');
    assert.ok(defaultProj, '应包含默认项目');
    assert.equal(defaultProj.tasks.length, 1, '默认项目下有 1 个小任务');
    assert.equal(defaultProj.tasks[0].title, '什么是线性表？');

    const dsProj = tree.find(p => p.id === 'proj-data-struct');
    assert.ok(dsProj, '应包含数据结构项目');
    assert.equal(dsProj.tasks.length, 2, '数据结构项目下有 2 个小任务');
    assert.equal(dsProj.tasks[0].title, '什么是二叉树？');
    assert.equal(dsProj.tasks[1].title, '堆排序如何实现？');
});
