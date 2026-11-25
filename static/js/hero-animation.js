(() => {
    const canvas = document.querySelector('#hero-animation');
    if (!canvas) return;
    const hero = canvas.closest('.landing-hero');
    const context = canvas.getContext('2d', {alpha: true});
    if (!hero || !context || !window.matchMedia) return;

    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const events = new AbortController();
    const accent = getComputedStyle(hero).getPropertyValue('--color-accent').trim() || '#31543f';
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let uSteps = 0;
    let vSteps = 0;
    let graph;
    let ribbon;
    let projected;
    let elapsed = 0;
    let previousTime = null;
    let lastPaint = -Infinity;
    let frame = 0;
    let visible = true;
    let suspended = false;
    let disposed = false;

    const clear = () => {
        context.clearRect(0, 0, canvas.width / pixelRatio, canvas.height / pixelRatio);
    };

    const draw = () => {
        clear();
        // One eased morph over 3.5 seconds, then continued ribbon rotation.
        const progress = Math.min(elapsed / 3.5, 1);
        const morph = progress < 0.5
            ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2;
        const rotation = (1 - morph) * Math.PI * 2.5 + elapsed * 0.35;
        const cos = Math.cos(rotation);
        const sin = Math.sin(rotation);
        const scale = Math.min(width / 680, height / 580, 1.25);
        const mobile = width < 768;
        const centerX = width * (mobile ? 0.52 : 0.48);
        const centerY = height * (mobile ? 0.28 : 0.5);

        for (let i = 0; i <= uSteps; i++) {
            const wave = Math.sin(i / uSteps * 10 + elapsed * 2);
            for (let j = 0; j <= vSteps; j++) {
                const point = i * (vSteps + 1) + j;
                const offset = point * 3;
                const x = graph[offset] * (1 - morph) + ribbon[offset] * morph;
                const y = graph[offset + 1] * wave * (1 - morph) + ribbon[offset + 1] * morph;
                const z = graph[offset + 2] * (1 - morph) + ribbon[offset + 2] * morph;
                const perspective = 500 / Math.max(x * sin + z * cos + 500, 50);
                projected[point * 2] = centerX + (x * cos - z * sin) * perspective * scale;
                projected[point * 2 + 1] = centerY + y * perspective * scale;
            }
        }

        context.strokeStyle = accent;
        context.lineWidth = 0.8;
        context.globalAlpha = mobile ? 0.16 : 0.23;
        context.beginPath();
        for (let j = 0; j <= vSteps; j++) {
            for (let i = 0; i <= uSteps; i++) {
                const offset = (i * (vSteps + 1) + j) * 2;
                if (i === 0) context.moveTo(projected[offset], projected[offset + 1]);
                else context.lineTo(projected[offset], projected[offset + 1]);
            }
        }
        context.stroke();
        context.globalAlpha = mobile ? 0.09 : 0.13;
        context.beginPath();
        for (let i = 0; i <= uSteps; i++) {
            for (let j = 0; j <= vSteps; j++) {
                const offset = (i * (vSteps + 1) + j) * 2;
                if (j === 0) context.moveTo(projected[offset], projected[offset + 1]);
                else context.lineTo(projected[offset], projected[offset + 1]);
            }
        }
        context.stroke();
    };

    const resize = () => {
        const bounds = hero.getBoundingClientRect();
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        if (bounds.width === width && bounds.height === height && ratio === pixelRatio) return;
        const densityChanged = !graph || (bounds.width < 768) !== (width < 768);
        width = bounds.width;
        height = bounds.height;
        pixelRatio = ratio;
        canvas.width = Math.round(width * pixelRatio);
        canvas.height = Math.round(height * pixelRatio);
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);

        if (densityChanged) {
            uSteps = width < 768 ? 48 : 72;
            vSteps = width < 768 ? 6 : 9;
            const count = (uSteps + 1) * (vSteps + 1);
            graph = new Float32Array(count * 3);
            ribbon = new Float32Array(count * 3);
            projected = new Float32Array(count * 2);
            for (let i = 0; i <= uSteps; i++) {
                const u = i / uSteps;
                const angle = u * Math.PI * 2;
                const twist = angle * 1.5;
                for (let j = 0; j <= vSteps; j++) {
                    const v = j / vSteps;
                    const band = (v - 0.5) * 0.55;
                    const offset = (i * (vSteps + 1) + j) * 3;
                    graph[offset] = (u - 0.5) * 450;
                    graph[offset + 1] = Math.cos(v * 6) * 35;
                    graph[offset + 2] = (v - 0.5) * 260;
                    // Preserve the supplied figure-eight curve and ribbon twist.
                    ribbon[offset] = (Math.sin(angle) + 0.45 * Math.sin(2 * angle)
                        + Math.cos(twist) * band) * 130;
                    ribbon[offset + 1] = Math.cos(angle) * 1.45 * 130;
                    ribbon[offset + 2] = (Math.sin(2 * angle) * 0.8
                        + Math.sin(twist) * band) * 130;
                }
            }
        }
        if (!motion.matches && width && height) draw();
    };

    const pause = () => {
        cancelAnimationFrame(frame);
        frame = 0;
        previousTime = null;
        lastPaint = -Infinity;
    };
    const dispose = () => {
        disposed = true;
        pause();
        events.abort();
        sizeObserver?.disconnect();
        visibilityObserver?.disconnect();
        clear();
    };
    const animate = (now) => {
        frame = 0;
        if (!hero.isConnected) {
            dispose();
            return;
        }
        if (previousTime !== null) elapsed += (now - previousTime) / 1000;
        previousTime = now;
        if (Math.min(window.devicePixelRatio || 1, 2) !== pixelRatio) resize();
        // Thirty paints per second are sufficient for this restrained background.
        if (now - lastPaint >= 1000 / 30) {
            draw();
            lastPaint = now;
        }
        frame = requestAnimationFrame(animate);
    };
    const update = () => {
        if (disposed) return;
        if (motion.matches || document.hidden || !visible || suspended || !width || !height) {
            pause();
            if (motion.matches) clear();
        } else if (!frame) frame = requestAnimationFrame(animate);
    };
    const sizeObserver = window.ResizeObserver ? new ResizeObserver(() => {
        resize();
        update();
    }) : null;
    const visibilityObserver = window.IntersectionObserver ? new IntersectionObserver(entries => {
        visible = entries[0].isIntersecting;
        update();
    }) : null;

    const options = {signal: events.signal};
    motion.addEventListener('change', update, options);
    document.addEventListener('visibilitychange', update, options);
    window.addEventListener('resize', () => { resize(); update(); }, options);
    window.addEventListener('pagehide', event => {
        if (event.persisted) { suspended = true; pause(); }
        else dispose();
    }, options);
    window.addEventListener('pageshow', () => { suspended = false; update(); }, options);
    sizeObserver?.observe(hero);
    visibilityObserver?.observe(hero);
    resize();
    update();
})();
