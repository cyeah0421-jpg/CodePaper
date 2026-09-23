const test = require('node:test');
const assert = require('node:assert/strict');
const { createSSEParser, readSSE } = require('../static/stream.js');

test('SSE parses frames and JSON split at every character, including CRLF', () => {
    const events = [];
    const parser = createSSEParser((name, data) => events.push([name, data]));
    const text = ': keepalive\r\n\r\nevent: delta\r\ndata: {"content":"中文\\n代码"}\r\n\r\nevent: done\ndata: {}\n\n';
    for (const char of text) parser.push(char);
    parser.finish();
    assert.deepEqual(events, [['delta', { content: '中文\n代码' }], ['done', {}]]);
});

test('UTF-8 characters survive single-byte network chunks', async () => {
    const bytes = new TextEncoder().encode('event: delta\ndata: {"content":"你好🌱"}\n\nevent: done\ndata: {}\n\n');
    const body = new ReadableStream({ start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
    } });
    const events = [];
    await readSSE(body, (name, data) => events.push([name, data]));
    assert.equal(events[0][1].content, '你好🌱');
    assert.equal(events[1][0], 'done');
});

test('truncated frames and invalid JSON fail rather than silently saving', () => {
    const parser = createSSEParser(() => {});
    parser.push('event: delta\ndata: {');
    assert.throws(() => parser.finish(), /不完整/);
    assert.throws(() => createSSEParser(() => {}).push('data: wrong\n\n'), SyntaxError);
});
