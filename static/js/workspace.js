(() => {
    const form = document.querySelector('#run-form');
    const source = document.querySelector('#matlab-code');
    const button = document.querySelector('#run-button');
    const label = document.querySelector('#run-label');
    const status = document.querySelector('#run-help');
    const results = document.querySelector('#results');
    const clearSource = document.querySelector('#clear-source');
    const matlabDownload = document.querySelector('#matlab-download');
    const matlabDownloadHelp = document.querySelector('#matlab-download-help');
    let running = false;

    // The current checkboxes are the selection state. Delegated handlers survive
    // result replacement without registering another set of event listeners.
    const updateSelection = () => {
        const selection = results.querySelector('#figure-selection');
        if (!selection) return;
        const choices = [...selection.querySelectorAll('input[name="indices"]')];
        const count = choices.filter(choice => choice.checked).length;
        const summary = selection.querySelector('#selection-count');
        summary.hidden = false;
        summary.textContent = `${count} of ${choices.length} selected`;
        selection.querySelectorAll('[data-combined-export]').forEach(action => {
            action.disabled = count === 0;
        });
        selection.querySelectorAll('[data-selection-action]').forEach(action => {
            action.hidden = false;
            action.disabled = action.dataset.selectionAction === 'all'
                ? count === choices.length : count === 0;
        });
        selection.querySelector('#selection-help').textContent = count === 0
            ? 'Select at least one figure to enable combined exports.'
            : 'Combined exports include the checked figures in their original order.';
    };

    results.addEventListener('change', (event) => {
        if (event.target.matches('input[name="indices"]')) updateSelection();
    });
    results.addEventListener('click', (event) => {
        const action = event.target.closest('[data-selection-action]');
        if (!action) return;
        results.querySelectorAll('input[name="indices"]').forEach(choice => {
            choice.checked = action.dataset.selectionAction === 'all';
        });
        updateSelection();
    });
    results.addEventListener('submit', (event) => {
        if (event.target.id === 'figure-selection'
                && !event.target.querySelector('input[name="indices"]:checked')) {
            event.preventDefault();
            updateSelection();
            event.target.querySelector('[data-selection-action="all"]').focus();
        }
    });
    updateSelection();

    clearSource.hidden = false;
    clearSource.addEventListener('click', () => {
        if (running) return;
        source.value = '';
        status.textContent = 'Source cleared. Enter MATLAB code to run.';
        source.focus();
    });

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
        // JSON preserves source line endings instead of multipart normalization.
        const data = {matlab_code: source.value};
        running = true;
        button.disabled = true;
        clearSource.disabled = true;
        source.readOnly = true;
        results.setAttribute('aria-busy', 'true');
        label.textContent = 'Running…';
        status.textContent = 'Translating and running your code…';
        try {
            const response = await fetch(form.action, {
                method: 'POST', body: JSON.stringify(data), credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json', 'Content-Type': 'application/json',
                    'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value,
                },
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
            updateSelection();
            matlabDownload.hidden = !result.matlab_download_url;
            matlabDownloadHelp.hidden = !result.matlab_download_url;
            if (result.matlab_download_url) matlabDownload.href = result.matlab_download_url;
            else matlabDownload.removeAttribute('href');
            status.textContent = result.success ? 'Run completed.' : 'Run could not complete. See the Command window.';
        } catch (error) {
            status.textContent = error instanceof TypeError
                ? 'Connection failed. Your source has been kept. Try again.'
                : error instanceof SyntaxError ? 'The response could not be read. Try again.' : error.message;
        } finally {
            running = false;
            button.disabled = false;
            clearSource.disabled = false;
            source.readOnly = false;
            results.removeAttribute('aria-busy');
            label.textContent = 'Run';
        }
    });
})();
