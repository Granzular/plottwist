(() => {
    const toggle = document.querySelector('#site-menu-toggle');
    const links = document.querySelector('#site-links');
    if (!toggle || !links || !window.matchMedia) return;

    const mobile = window.matchMedia('(max-width: 767px)');
    const setOpen = (open) => {
        toggle.setAttribute('aria-expanded', String(open));
        links.hidden = !open;
    };
    const update = () => {
        toggle.hidden = !mobile.matches;
        setOpen(!mobile.matches);
    };
    toggle.addEventListener('click', () => setOpen(links.hidden));
    links.addEventListener('click', (event) => {
        if (mobile.matches && event.target.closest('a')) setOpen(false);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && mobile.matches && !links.hidden) {
            setOpen(false);
            toggle.focus();
        }
    });
    mobile.addEventListener('change', update);
    update();
})();
