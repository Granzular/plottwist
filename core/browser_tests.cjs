// Driven by Django's WorkspaceBrowserTests; uses Node's built-in WebSocket/CDP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
    const [baseUrl, port, downloadDirectory] = process.argv.slice(2);
    const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
    let nextId = 0;
    const pending = new Map();
    const scriptErrors = [];
    const requests = [];
    const responses = [];
    socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.id && pending.has(message.id)) {
            const entry = pending.get(message.id);
            clearTimeout(entry.timeout);
            pending.delete(message.id);
            message.error ? entry.reject(new Error(JSON.stringify(message.error))) : entry.resolve(message.result);
        }
        if (message.method === 'Runtime.exceptionThrown') scriptErrors.push(message.params);
        if (message.method === 'Network.requestWillBeSent') requests.push(message.params.request);
        if (message.method === 'Network.responseReceived') responses.push(message.params.response);
    };
    const call = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++nextId;
        const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 15000);
        pending.set(id, {resolve, reject, timeout});
        socket.send(JSON.stringify({id, method, params}));
    });
    const evaluate = async expression => {
        const result = await call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
        if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
        return result.result.value;
    };
    const until = async (condition, description) => {
        const deadline = Date.now() + 60000;
        while (Date.now() < deadline) {
            if (await condition()) return;
            await new Promise(resolve => setTimeout(resolve, 100));
        }
        throw new Error(`Timed out: ${description}`);
    };
    const waitFor = expression => until(() => evaluate(expression), expression);
    const key = async (name, code, keyCode) => {
        await call('Input.dispatchKeyEvent', {type: 'keyDown', key: name, code, windowsVirtualKeyCode: keyCode});
        await call('Input.dispatchKeyEvent', {type: 'keyUp', key: name, code, windowsVirtualKeyCode: keyCode});
    };
    const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const selection = () => evaluate(`({
        checked: [...document.querySelectorAll('input[name="indices"]:checked')].map(input => Number(input.value)),
        count: document.querySelector('#selection-count').textContent,
        disabled: [...document.querySelectorAll('[data-combined-export]')].map(button => button.disabled),
        help: document.querySelector('#selection-help').textContent,
        previews: [...document.querySelectorAll('#figure-workspace img')].map(image => image.src),
        links: [...document.querySelectorAll('#figure-workspace a')].map(link => link.href)
    })`);
    const screenshot = async name => {
        if (!process.env.PLOTTWIST_BROWSER_SCREENSHOTS) return;
        const directory = path.resolve(process.env.PLOTTWIST_BROWSER_SCREENSHOTS);
        fs.mkdirSync(directory, {recursive: true});
        const result = await call('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true});
        fs.writeFileSync(path.join(directory, `workspace-${name}.png`), Buffer.from(result.data, 'base64'));
    };
    const inspectLayout = async (name, width, height, mobile) => {
        await call('Emulation.setDeviceMetricsOverride', {
            width, height, deviceScaleFactor: name === 'zoom' ? 2 : 1, mobile,
        });
        await evaluate('window.scrollTo(0, 0)');
        const layout = await evaluate(`(() => {
            const box = selector => {
                const rect = document.querySelector(selector).getBoundingClientRect();
                return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            };
            return {
                width: innerWidth, pageWidth: document.scrollingElement.scrollWidth,
                source: box('#run-form'), python: box('#python-panel'),
                figures: box('#figure-workspace'), command: box('#command-panel'),
                images: [...document.querySelectorAll('#figure-workspace img')].map(image => ({
                    width: image.getBoundingClientRect().width, height: image.getBoundingClientRect().height,
                    naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight
                }))
            };
        })()`);
        assert.ok(layout.pageWidth <= width, `${name}: page horizontal overflow`);
        if (width >= 1024) {
            assert.ok(layout.python.x > layout.source.x);
            assert.equal(layout.python.y, layout.source.y);
            assert.ok(Math.abs(layout.python.width - layout.source.width) <= 1);
        } else {
            assert.ok(layout.python.y >= layout.source.y + layout.source.height);
        }
        assert.ok(layout.figures.y >= layout.python.y + layout.python.height);
        assert.ok(layout.command.y >= layout.figures.y + layout.figures.height);
        for (const image of layout.images) {
            assert.ok(image.naturalWidth > 0);
            assert.ok(Math.abs(image.width / image.height - image.naturalWidth / image.naturalHeight) < 0.01);
        }
        await screenshot(name);
    };
    const run = async marker => {
        // Read the synchronous busy state before a fast response can finish
        // between separate DevTools evaluations.
        assert.equal(await evaluate(`document.querySelector('#matlab-code').value = ${JSON.stringify(marker)};
            document.querySelector('#run-form').requestSubmit();
            document.querySelector('#run-button').disabled`), true);
        await waitFor('!document.querySelector("#run-button").disabled');
        await evaluate('document.querySelectorAll("#figure-workspace img").forEach(image => image.loading = "eager")');
        await waitFor('[...document.querySelectorAll("#figure-workspace img")].every(image => image.complete && image.naturalWidth > 0)');
    };

    try {
        await call('Page.enable');
        await call('Runtime.enable');
        await call('Network.enable');
        await call('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: downloadDirectory});
        await call('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});
        await call('Page.navigate', {url: baseUrl});
        await waitFor('document.readyState === "complete" && !!document.querySelector("#clear-source") && !document.querySelector("#clear-source").hidden');
        const identity = await evaluate(`(() => {
            const style = selector => getComputedStyle(document.querySelector(selector));
            return {
                background: style('body').backgroundColor, text: style('body').color,
                sans: style('body').fontFamily, serif: style('h1').fontFamily,
                mono: style('#matlab-code').fontFamily, accent: style('h1').color,
                wordmarkSize: style('h1').fontSize, wordmarkWeight: style('h1').fontWeight,
                headingSize: style('h2').fontSize, headingWeight: style('h2').fontWeight,
                codeSize: style('#matlab-code').fontSize, codeHeight: style('#matlab-code').lineHeight,
                pythonSize: style('#python-code').fontSize,
                label: document.querySelector('#matlab-code').labels[0].textContent,
                runHeight: document.querySelector('#run-button').getBoundingClientRect().height
            };
        })()`);
        assert.equal(identity.background, 'rgb(250, 250, 248)');
        assert.equal(identity.text, 'rgb(34, 42, 36)');
        assert.equal(identity.accent, 'rgb(49, 84, 63)');
        assert.ok(identity.sans.includes('Segoe UI'));
        assert.ok(identity.serif.includes('Georgia'));
        assert.ok(identity.mono.includes('Consolas'));
        assert.equal(identity.wordmarkSize, '48px');
        assert.equal(identity.wordmarkWeight, '600');
        assert.equal(identity.headingSize, '16px');
        assert.equal(identity.headingWeight, '600');
        assert.equal(identity.codeSize, '14px');
        assert.equal(identity.pythonSize, '14px');
        assert.equal(identity.codeHeight, '28px');
        assert.equal(identity.label, 'MATLAB source');
        assert.ok(identity.runHeight >= 44);
        assert.equal(await evaluate('document.querySelector("#matlab-download").hidden'), true);
        await inspectLayout('initial', 1280, 900, false);

        await key('Tab', 'Tab', 9);
        assert.equal(await evaluate('document.activeElement.textContent'), 'Skip to workspace');
        assert.ok(await evaluate('document.activeElement.getBoundingClientRect().width > 1'));
        await key('Enter', 'Enter', 13);
        assert.equal(await evaluate('document.activeElement.id'), 'workspace');
        await key('Tab', 'Tab', 9);
        assert.equal(await evaluate('document.activeElement.id'), 'matlab-code');
        assert.ok(await evaluate('getComputedStyle(document.querySelector("#run-form")).boxShadow !== "none"'));

        await evaluate(`window.originalFetch = window.fetch; window.runRequests = 0;
            window.fetch = (...args) => {
                if (String(args[0]).endsWith('/run/')) window.runRequests++;
                return window.originalFetch(...args);
            };
            window.submittedSource = '% Exact source π\\n\\n  x = [1, 2];  \\nplot(x);\\n';
            document.querySelector('#matlab-code').value = window.submittedSource;
            document.querySelector('#run-form').requestSubmit();
            document.querySelector('#run-form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));`);
        assert.equal(await evaluate('window.runRequests'), 1);
        assert.equal(await evaluate('document.querySelector("#matlab-code").readOnly'), true);
        assert.equal(await evaluate('document.querySelector("#clear-source").disabled'), true);
        await waitFor('!document.querySelector("#run-button").disabled && document.querySelectorAll("input[name=indices]").length === 5');
        await evaluate('document.querySelectorAll("#figure-workspace img").forEach(image => image.loading = "eager")');
        await waitFor('[...document.querySelectorAll("#figure-workspace img")].every(image => image.complete && image.naturalWidth > 0)');
        assert.equal(await evaluate('document.querySelector("#python-code").tagName'), 'PRE');
        assert.equal(await evaluate('document.querySelector("#python-code").isContentEditable'), false);
        assert.equal(await evaluate('document.querySelector("#matlab-code").readOnly'), false);
        const all = await selection();
        assert.deepEqual(all.checked, [0, 1, 2, 3, 4]);
        assert.equal(all.count, '5 of 5 selected');
        assert.deepEqual(all.disabled, [false, false]);
        await inspectLayout('desktop', 1280, 900, false);
        await inspectLayout('mobile', 360, 800, true);
        await inspectLayout('zoom', 640, 450, false);
        await evaluate(`window.savedSource = document.querySelector('#matlab-code').value;
            document.querySelector('#matlab-code').value = 'x = ' + '1234567890'.repeat(100)`);
        assert.ok(await evaluate('document.querySelector("#matlab-code").scrollWidth > document.querySelector("#matlab-code").clientWidth'));
        assert.ok(await evaluate('document.querySelector("#python-code").scrollWidth > document.querySelector("#python-code").clientWidth'));
        assert.ok(await evaluate('document.scrollingElement.scrollWidth <= innerWidth'));
        await evaluate('document.querySelector("#matlab-code").value = window.savedSource');
        await call('Emulation.setDeviceMetricsOverride', {width: 1280, height: 900, deviceScaleFactor: 1, mobile: false});

        await evaluate('document.querySelector("#figure-select-1").focus()');
        await key(' ', 'Space', 32);
        assert.deepEqual((await selection()).checked, [0, 2, 3, 4]);
        assert.equal(await evaluate('getComputedStyle(document.querySelector("#figure-select-1")).outlineWidth'), '2px');
        assert.equal(await evaluate('getComputedStyle(document.querySelector("[data-figure-index=\\"1\\"]")).borderColor'), 'rgb(217, 222, 215)');
        await click('[data-selection-action="all"]');
        assert.deepEqual((await selection()).checked, [0, 1, 2, 3, 4]);
        await click('[data-selection-action="clear"]');
        const empty = await selection();
        assert.deepEqual(empty.checked, []);
        assert.equal(empty.count, '0 of 5 selected');
        assert.deepEqual(empty.disabled, [true, true]);
        assert.ok(empty.help.includes('at least one figure'));
        assert.deepEqual(empty.previews, all.previews);
        assert.deepEqual(empty.links, all.links);
        const beforeEmpty = requests.length;
        await evaluate('document.querySelector("#figure-selection").requestSubmit(document.querySelector("[data-combined-export]"))');
        assert.equal(requests.length, beforeEmpty);
        await screenshot('empty-selection');

        // Individual downloads and source downloads stay available with no selection.
        const downloadChecks = await evaluate(`(async () => {
            const links = [document.querySelector('#matlab-download'),
                document.querySelector('#python-panel .download-link'),
                ...document.querySelectorAll('[data-figure-index="1"] a')];
            document.querySelector('#matlab-code').value = '% unsent editor changes';
            const checks = [];
            for (const link of links) {
                const response = await originalFetch(link.href);
                const bytes = await response.arrayBuffer();
                const type = response.headers.get('Content-Type');
                checks.push({status: response.status, type,
                    disposition: response.headers.get('Content-Disposition'), bytes: bytes.byteLength,
                    text: type.startsWith('text/') ? new TextDecoder().decode(bytes) : null});
            }
            return {checks, source: window.submittedSource, python: document.querySelector('#python-code code').textContent};
        })()`);
        for (const check of downloadChecks.checks) {
            assert.equal(check.status, 200);
            assert.ok(check.disposition.includes('attachment'));
            assert.ok(check.bytes > 0);
        }
        assert.equal(downloadChecks.checks[0].text, downloadChecks.source);
        assert.equal(downloadChecks.checks[0].type, 'text/x-matlab; charset=utf-8');
        assert.ok(downloadChecks.checks[0].disposition.includes('generated.m'));
        assert.equal(downloadChecks.checks[1].text, downloadChecks.python);
        assert.ok(downloadChecks.checks[1].disposition.includes('generated.py'));

        for (const index of [0, 2, 4]) await click(`#figure-select-${index}`);
        assert.deepEqual((await selection()).checked, [0, 2, 4]);
        assert.equal((await selection()).count, '3 of 5 selected');
        assert.equal(await evaluate('getComputedStyle(document.querySelector("[data-figure-index=\\"0\\"]")).borderColor'), 'rgb(49, 84, 63)');
        for (const format of ['pdf', 'docx']) {
            const requestStart = requests.length;
            await click(`[data-combined-export][formaction$="/${format}/"]`);
            await until(() => fs.existsSync(path.join(downloadDirectory, `charts.${format}`)), `${format} attachment`);
            const request = requests.slice(requestStart).find(request => request.url.includes(`/download/${format}/`));
            assert.ok(request, `${format}: no native download request`);
            assert.equal(request.method, 'GET');
            assert.deepEqual(new URL(request.url).searchParams.getAll('indices'), ['0', '2', '4']);
            assert.equal(new URL(request.url).searchParams.get('selection'), '1');
        }
        await click('[data-selection-action="all"]');
        assert.equal((await selection()).count, '5 of 5 selected');
        await evaluate('window.firstMatlabUrl = document.querySelector("#matlab-download").href');
        await run('TWO_FIGURES');
        const replacement = await selection();
        assert.deepEqual(replacement.checked, [0, 1]);
        assert.equal(replacement.count, '2 of 2 selected');
        assert.deepEqual(replacement.disabled, [false, false]);
        assert.ok(await evaluate('document.querySelector("#matlab-download").href !== window.firstMatlabUrl'));
        await click('[data-selection-action="clear"]');
        assert.deepEqual((await selection()).disabled, [true, true]);
        await click('[data-selection-action="all"]');
        assert.equal((await selection()).count, '2 of 2 selected');

        for (const [marker, expected] of [
            ['FAIL_EXECUTION', 'Execution failed'],
            ['NO_FIGURES', 'Execution completed without figures'],
            ['FAIL_TRANSLATION', 'Translation failed'],
        ]) {
            await run(marker);
            assert.ok(await evaluate(`document.querySelector('#results').textContent.includes(${JSON.stringify(expected)})`));
            assert.equal(await evaluate('document.querySelectorAll("[data-combined-export]").length'), 0);
            assert.equal(await evaluate('document.querySelector("#figure-selection")'), null);
            if (marker === 'FAIL_EXECUTION') {
                assert.ok(await evaluate('document.querySelector("#python-code").textContent.includes("raise ValueError")'));
                assert.ok(await evaluate('!!document.querySelector("#warnings-heading")'));
                assert.equal(await evaluate('document.querySelector("#matlab-download").hidden'), false);
                assert.ok(await evaluate('!document.querySelector("#results").textContent.includes("Traceback")'));
            }
            if (marker === 'FAIL_TRANSLATION') {
                assert.equal(await evaluate('document.querySelector("#matlab-download").hidden'), true);
                assert.equal(await evaluate('document.querySelector("#matlab-download").hasAttribute("href")'), false);
            }
        }
        await click('#clear-source');
        assert.equal(await evaluate('document.querySelector("#matlab-code").value'), '');
        assert.equal(await evaluate('document.activeElement.id'), 'matlab-code');
        await evaluate('document.querySelector("#run-form").dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}))');
        assert.equal(await evaluate('window.runRequests'), 5);
        assert.ok(await evaluate('document.querySelector("#run-help").textContent.includes("Enter MATLAB source")'));
        assert.deepEqual(scriptErrors, []);
        assert.ok(responses.some(response => response.url.endsWith('/static/css/app.css') && response.status === 200));
        assert.ok(responses.some(response => response.url.endsWith('/static/js/workspace.js') && response.status === 200));
        assert.deepEqual(responses.filter(response => response.url.includes('/static/') && response.status >= 400), []);
        console.log('Browser: identity, desktop/mobile/zoom layout, keyboard focus, selection, native subset downloads, source preservation, replacement, and failure states passed.');
    } finally {
        await call('Browser.close').catch(() => {});
        socket.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
