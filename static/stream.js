/* SSE 是文本协议：网络块不等于事件，更不一定是完整的 UTF-8 字符。 */
(function (root) {
    function createSSEParser(onEvent) {
        let buffer = '';
        function dispatch(frame) {
            let event = 'message';
            const data = [];
            for (const line of frame.split(/\r?\n/)) {
                if (line.startsWith('event:')) event = line.slice(6).trim();
                if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
            }
            if (data.length) onEvent(event, JSON.parse(data.join('\n')));
        }
        return {
            push(text) {
                buffer += text;
                let separator;
                while ((separator = /\r?\n\r?\n/.exec(buffer))) {
                    dispatch(buffer.slice(0, separator.index));
                    buffer = buffer.slice(separator.index + separator[0].length);
                }
            },
            finish() {
                if (buffer.trim()) throw new Error('回复数据不完整，请重试');
            },
        };
    }

    async function readSSE(body, onEvent) {
        if (!body) throw new Error('浏览器没有收到流式响应');
        const reader = body.getReader();
        const decoder = new TextDecoder();
        const parser = createSSEParser(onEvent);
        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                parser.push(decoder.decode(value, { stream: true }));
            }
            parser.push(decoder.decode());
            parser.finish();
        } finally {
            await reader.cancel().catch(() => {});
            reader.releaseLock();
        }
    }

    const api = { createSSEParser, readSSE };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.StudyStream = api;
})(globalThis);
