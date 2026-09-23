// 构建步骤：把锁定版本的第三方浏览器文件复制到本地静态目录。
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const assets = {
  'marked/lib/marked.umd.js': 'marked.js',
  'marked/LICENSE.md': 'marked-LICENSE.md',
  'dompurify/dist/purify.min.js': 'purify.min.js',
  'dompurify/LICENSE': 'dompurify-LICENSE.txt',
  '@highlightjs/cdn-assets/highlight.min.js': 'highlight.min.js',
  '@highlightjs/cdn-assets/styles/github-dark.min.css': 'highlight.css',
  '@highlightjs/cdn-assets/LICENSE': 'highlight-LICENSE.txt',
};
fs.mkdirSync(path.join(root, 'static/vendor'), { recursive: true });
for (const [source, target] of Object.entries(assets)) {
  fs.copyFileSync(path.join(root, 'node_modules', source), path.join(root, 'static/vendor', target));
}
console.log('本地 Markdown、清洗和高亮依赖已就绪。');
