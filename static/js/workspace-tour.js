(() => {
    const workspace = document.querySelector('#workspace');
    const panel = document.querySelector('#workspace-tour');
    const invitation = document.querySelector('#tour-invitation');
    const replay = document.querySelector('#tour-replay');
    if (!workspace || !panel || !invitation || !replay) return;

    const storageKey = 'plottwist.workspaceTour.v1';
    let storage;
    // If storage is blocked, keep replay available without repeating invitations.
    try {
        storage = window.localStorage;
        invitation.hidden = Boolean(storage.getItem(storageKey));
    } catch {
        invitation.hidden = true;
    }

    const steps = [
        {
            selector: '#run-form', title: 'Start with MATLAB',
            text: 'Write or paste your script in the editable MATLAB source panel. The sampled sine wave is a useful first run.',
        },
        {
            selector: '#run-button', title: 'One Run, two stages',
            text: 'Run sends the source to Groq for translation, then starts Python execution in a separate process. Wait for the status beside Run.',
        },
        {
            selector: '#python-panel', title: 'Review the generated Python',
            text: 'This panel is read-only. Inspect the translation, then copy or download Python. Download MATLAB in the source header preserves the displayed run’s original input.',
        },
        {
            selector: '#figure-workspace', title: 'Explore your plots',
            text: 'Generated figures appear here in creation order. Check the labels, units, and scales. A successful calculation can also finish without creating figures.',
        },
        {
            selector: '#command-panel', title: 'Read the command window',
            text: 'Find printed values, translation warnings, and errors here. Translation failure stops before execution; execution failure keeps the generated Python for review.',
        },
        {
            selector: '#figure-selection figcaption', fallback: '#figure-workspace',
            title: 'Choose your figures',
            text: () => document.querySelector('#figure-selection')
                ? 'Use the checkbox beside each Figure label. New results start with all figures selected. Select all and Clear selection control the combined document.'
                : 'After a run creates figures, a checkbox appears beside each Figure label. Those checkboxes choose the figures for a combined document.',
        },
        {
            selector: '#figure-selection [aria-label="Export selected figures"]',
            fallback: '#figure-workspace', title: 'Export the results',
            text: () => document.querySelector('#figure-selection')
                ? 'Use PNG, PDF, or DOCX beneath a figure for an individual download. Combined PDF and Combined DOCX use checked figures in their original order. Downloads reuse this run.'
                : 'When figures are available, individual PNG, PDF, and DOCX links appear beneath them. Combined PDF and DOCX controls export checked figures. Run the sample to try them.',
        },
    ];
    const back = panel.querySelector('#tour-back');
    const next = panel.querySelector('#tour-next');
    const title = panel.querySelector('#tour-title');
    let index = 0;
    let highlighted;
    let returnFocus;
    let positioning = false;

    const position = () => {
        if (panel.hidden || !highlighted) return;
        const rect = highlighted.getBoundingClientRect();
        const width = panel.offsetWidth;
        const height = panel.offsetHeight;
        const viewportHeight = window.visualViewport?.height || window.innerHeight;
        const margin = 16;
        const gap = 16;
        let left = window.innerWidth - width - margin;
        let top = viewportHeight - height - margin;

        if (window.innerWidth >= 768 && rect.right + gap + width <= window.innerWidth - margin) {
            left = rect.right + gap;
            top = rect.top;
        } else if (window.innerWidth >= 768 && rect.left - gap - width >= margin) {
            left = rect.left - gap - width;
            top = rect.top;
        } else if (rect.bottom + gap + height <= viewportHeight - margin) {
            top = rect.bottom + gap;
        } else if (rect.top - gap - height >= margin) {
            top = rect.top - gap - height;
        }
        panel.style.left = `${Math.max(margin, Math.min(left, window.innerWidth - width - margin))}px`;
        panel.style.top = `${Math.max(margin, Math.min(top, viewportHeight - height - margin))}px`;
    };
    const schedulePosition = () => {
        if (positioning || panel.hidden) return;
        positioning = true;
        window.requestAnimationFrame(() => {
            positioning = false;
            position();
        });
    };
    const render = (scroll = false) => {
        const step = steps[index];
        highlighted?.classList.remove('tour-highlight');
        highlighted = document.querySelector(step.selector)
            || (step.fallback && document.querySelector(step.fallback));
        if (!highlighted) return;
        highlighted.classList.add('tour-highlight');
        panel.dataset.step = String(index + 1);
        panel.querySelector('#tour-progress').textContent = `Step ${index + 1} of ${steps.length}`;
        title.textContent = step.title;
        panel.querySelector('#tour-text').textContent = typeof step.text === 'function' ? step.text() : step.text;
        back.disabled = index === 0;
        next.textContent = index === steps.length - 1 ? 'Finish' : 'Next';
        if (scroll) {
            const rect = highlighted.getBoundingClientRect();
            if (rect.height > window.innerHeight - panel.offsetHeight - 48) {
                window.scrollTo({top: Math.max(0, window.scrollY + rect.top - 32), behavior: 'instant'});
            } else {
                highlighted.scrollIntoView({block: 'center', behavior: 'instant'});
            }
        }
        position();
    };
    const dismiss = (state = 'dismissed') => {
        invitation.hidden = true;
        const wasOpen = !panel.hidden;
        panel.hidden = true;
        highlighted?.classList.remove('tour-highlight');
        highlighted = null;
        try { storage?.setItem(storageKey, state); } catch { /* Replay remains available. */ }
        if (wasOpen) {
            const target = returnFocus?.isConnected && returnFocus.getClientRects().length ? returnFocus : replay;
            target.focus({preventScroll: true});
        } else replay.focus({preventScroll: true});
    };
    const start = () => {
        returnFocus = document.activeElement;
        invitation.hidden = true;
        panel.hidden = false;
        index = 0;
        render(true);
        title.focus({preventScroll: true});
    };

    replay.hidden = false;
    replay.addEventListener('click', start);
    invitation.querySelector('[data-tour-start]').addEventListener('click', start);
    document.querySelectorAll('[data-tour-dismiss]').forEach(button => {
        button.addEventListener('click', () => dismiss());
    });
    back.addEventListener('click', () => {
        if (index > 0) {
            index--;
            render(true);
            if (back.disabled) next.focus({preventScroll: true});
        }
    });
    next.addEventListener('click', () => {
        if (index === steps.length - 1) dismiss('completed');
        else { index++; render(true); }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !panel.hidden) {
            event.preventDefault();
            dismiss();
        }
    });
    window.addEventListener('resize', schedulePosition);
    window.addEventListener('scroll', schedulePosition, {passive: true});
    window.visualViewport?.addEventListener('resize', schedulePosition);
    // Results are replaced by the existing Run script. Resolve current elements
    // without changing the tour step or registering workflow event handlers.
    if (window.MutationObserver) {
        new MutationObserver(() => { if (!panel.hidden) render(); })
            .observe(document.querySelector('#results'), {childList: true, subtree: true});
    }
})();
