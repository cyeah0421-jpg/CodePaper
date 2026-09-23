const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
    testDir: './tests/browser',
    workers: 1,
    timeout: 30000,
    use: {
        baseURL: 'http://127.0.0.1:8017',
        channel: 'msedge',
        headless: true,
        viewport: { width: 1440, height: 960 },
        screenshot: 'only-on-failure',
    },
    webServer: {
        command: 'python -m tests.browser_server',
        url: 'http://127.0.0.1:8017',
        reuseExistingServer: false,
        timeout: 15000,
    },
});
