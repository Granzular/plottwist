# Runtime plotting caches

Matplotlib discovers Linux system fonts through `fc-list`. Fontconfig writes
`No writable cache directories` to stderr when its cache locations are unavailable.
The execution worker previously supplied only a fresh Matplotlib cache per run
and dropped `XDG_CACHE_HOME` from its reduced environment. PDF downloads also
initialize Matplotlib in the Django process.

Django settings now create `plottwist-cache` and `plottwist-mplconfig` under the
OS temporary directory (`/tmp` on Render) before Matplotlib imports. Nonempty
`XDG_CACHE_HOME` and `MPLCONFIGDIR` values are retained. The worker explicitly
receives these two variables and creates the directories before launch; without
startup configuration, it uses writable per-run cache directories. The reduced
environment still excludes application credentials. Caches are regenerable;
no persistent storage or deployment configuration is required.

Local Windows checks cover writable default/custom directories, both variables
inside the execution child, repeated DSP plots, credential exclusion, and PNG
artifact cleanup. Windows has no Fontconfig here; confirm the Linux warnings
disappear in Render logs after deployment, including the first PDF download.
