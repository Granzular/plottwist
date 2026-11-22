(() => {
    const form = document.querySelector('#run-form');
    const source = document.querySelector('#matlab-code');
    const button = document.querySelector('#run-button');
    const label = document.querySelector('#run-label');
    const status = document.querySelector('#run-help');
    const results = document.querySelector('#results');
    let running = false;

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (running) return;
        if (!source.value.trim()) {
            status.textContent = 'Enter MATLAB source code to run.';
            source.focus();
            return;
        }
        if (new TextEncoder().encode(source.value).length > Number(form.dataset.maxBytes)) {
            status.textContent = 'MATLAB source exceeds the 64 KiB limit.';
            return;
        }
        const data = new FormData(form);
        running = true;
        button.disabled = true;
        source.readOnly = true;
        results.setAttribute('aria-busy', 'true');
        label.textContent = 'Running…';
        status.textContent = 'Translating and running your code…';
        try {
            const response = await fetch(form.action, {
                method: 'POST', body: data, credentials: 'same-origin',
                headers: {'Accept': 'application/json'},
            });
            if (!response.headers.get('Content-Type')?.includes('application/json')) {
                throw new Error(response.status === 403
                    ? 'The request was rejected. Refresh the page and try again.'
                    : 'The request could not complete. Try again.');
            }
            const result = await response.json();
            if (typeof result.html !== 'string') throw new Error('The response could not be read. Try again.');
            // HTML is rendered by Django with autoescaping; provider text is never inserted directly.
            results.innerHTML = result.html;
            status.textContent = result.success ? 'Run completed.' : 'Run could not complete. See the result details.';
        } catch (error) {
            status.textContent = error instanceof TypeError
                ? 'Connection failed. Your source has been kept. Try again.'
                : error instanceof SyntaxError ? 'The response could not be read. Try again.' : error.message;
        } finally {
            running = false;
            button.disabled = false;
            source.readOnly = false;
            results.removeAttribute('aria-busy');
            label.textContent = 'Run';
        }
    });
})();
