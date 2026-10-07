# SolarGuard Space — deployment

How SolarGuard is served, how to prove a deploy worked, and how to roll back. Every command
below was run against the live host on 2026-10-07; the output shown is the actual output.

---

## 1. Shape of the deployment

SolarGuard ships as a **FastAPI sub-application**:

```python
# backend/sg_app.py
sg_app = FastAPI(title="SolarGuard Space API", docs_url=None, redoc_url=None)
...
sg_app.mount("/", StaticFiles(directory=str(PUBLIC), html=True), name="sg-public")
```

The site host (`space-marines.aimaher.com`) owns the domain and the `app.py` that uvicorn
runs; SolarGuard is mounted into it at `/solarguard`. The sub-app does **not** run its own
server in production and defines no absolute paths in its routes — every route is relative to
wherever the host mounts it.

Contract the sub-app keeps, so the host can mount it safely:

- module-level `sg_app` is a FastAPI instance;
- every `/api/*` route is registered **before** the static mount;
- the static mount (`StaticFiles(..., html=True)`) is registered **last**, so it only catches
  leftovers and serves `public/index.html` for `/`;
- `/api/health` and `/api/version` are dependency-free and always answer;
- no route may raise (middleware crash barrier, `docs/ARCHITECTURE.md` §5).

Live URLs:

| URL | Serves |
|---|---|
| `https://space-marines.aimaher.com/solarguard/` | `public/index.html` |
| `https://space-marines.aimaher.com/solarguard/dashboard.html` | `public/dashboard.html` |
| `https://space-marines.aimaher.com/solarguard/api/*` | the sub-app's API |
| `https://space-marines.aimaher.com/solarguard/assets/*` | the sub-app's static assets |

Since 2026-10-07 the same content also answers at the **domain root**: `/` and `/solarguard/`
return byte-identical HTML (10,758 B) and `/api/report` answers 200 at the root, while
`/api/version` and `/api/health` at the root return the host's own `space-marines` identity
(`{"service":"space-marines","version":"3.0-ai",...}`). That is consistent with the host
declaring its own routes first and mounting the SolarGuard sub-app to catch the rest. The
repository was written for the `/solarguard` mount and works unchanged at the root because all
front-end calls are relative.

> Note on scope: the host module that performs the mount (`space-marines/backend/app.py`) lives
> outside this repository and outside the sandbox this document was written in, so its source
> was **not read** for this file. Everything above is either the sub-app's own contract
> (`backend/sg_app.py`) or live HTTP observation. Where this document says "the host does X",
> X is what the deployment returns, not a code citation.

## 2. The guarded-import pattern

The failure mode to avoid is a broken SolarGuard section taking the whole domain down. The
pattern is: import the sub-app behind a `try/except` and mount it only when the import
succeeds.

```python
# host app.py — pattern, not quoted from the host (see scope note)
try:
    from sg_app import sg_app as solarguard_app          # backend/ on sys.path
    app.mount("/solarguard", solarguard_app)
    _SOLARGUARD = True
except Exception as e:
    print(f"[host] solarguard unavailable: {type(e).__name__}: {e}")
    _SOLARGUARD = False
```

If the import fails (a syntax error, a missing dependency, a bad mount) the rest of the site
still serves; only `/solarguard` is missing. The sub-app cooperates by keeping its own import
graph small (fastapi/starlette/pydantic/httpx/numpy/pillow — `requirements.txt`) and by never
raising at request time.

The bare path is handled by Starlette's slash redirect: mounting at `/solarguard` makes a
request for `/solarguard` answer `308` to `/solarguard/` (FastAPI/Starlette default
`redirect_slashes=True`). Verified live — see §4.

## 3. Where things live and how they are run

- Repo: `/home/hermes2/solarguard-space`
- DeepSeek key: `/home/hermes2/solarguard-space/backend/.env` (runtime-only, gitignored)
- Host app: `/home/hermes2/space-marines/backend/app.py`, run by uvicorn with
  `--reload --reload-dir /home/hermes2/space-marines/backend`
- Process observed: `/usr/local/lib/hermes-agent/venv/bin/python -m uvicorn app:app --host
  127.0.0.1 --port 8100 --log-level warning --reload --reload-dir
  /home/hermes2/space-marines/backend`

To run SolarGuard standalone for development (no host):

```bash
cd /home/hermes2/solarguard-space/backend
python -m uvicorn sg_app:sg_app --host 127.0.0.1 --port 8099
# http://127.0.0.1:8099/  and  http://127.0.0.1:8099/api/health
```

## 4. Verifying a deploy

Run these in order. Each line is the command and the expected result.

```bash
BASE=https://space-marines.aimaher.com/solarguard
```

**1. Bare path redirects to the slash form**

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' "$BASE"
# 308 https://space-marines.aimaher.com/solarguard/
```

**2. The sub-app is alive and reports its identity**

```bash
curl -s "$BASE/api/version"
# {"service":"solarguard-space","version":"1.0.0","ai_model":"deepseek-flash","ai_configured":true,"soiling_model":"physics"}
```

`soiling_model` is `physics` or `ml+physics`. It reads `physics` because the ML artifacts do
not load (see README §ML models). `ai_configured: true` proves the key was read server-side.

**3. Health (dependency-free)**

```bash
curl -s "$BASE/api/health"
# {"status":"ok","service":"solarguard-space","version":"1.0.0","utc":"...","riyadh":"..."}
```

**4. The landing page serves**

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type} %{size_download}\n' "$BASE/"
# 200 text/html; charset=utf-8 10758
```

**5. The data layer is really pulling, not cached-forever**

```bash
curl -s "$BASE/api/sources" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["checked_utc"],d["open_live"],d["open_total"],d["gated"])'
# 2026-10-07T12:15:09+00:00 12 12 8
```

`open_live` must equal `open_total` for a healthy deploy. Use `?refresh=1` to force the probe.

**6. The main report endpoint returns real numbers**

```bash
curl -s "$BASE/api/report?site=dammam&capacity_kwp=100000&cleaning_interval_days=10&horizon_days=10" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);v=d["verdict"];print(d["site"]["name"],v["decision"],v["current_soiling_loss_pct"],v["next_7d_money_at_risk_sar"],v["cleaning_cost_sar"])'
# Dammam / Eastern Prov wait 0.73 16626.74 180000.0
```

**7. The agent is wired (one call)**

```bash
curl -s -X POST "$BASE/api/assistant" -H 'content-type: application/json' \
  -d '{"question":"Should we clean Dammam this week?","site":"dammam","capacity_kwp":100000}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["ok"],[t["tool"] for t in d.get("tool_trace",[])],len(d.get("answer") or ""))'
# True ['site_report', ...] <n chars>
```

**8. Comprehensive in-process walk (run on the box, no server needed)**

```bash
cd /home/hermes2/solarguard-space && python3 tests/test_asgi.py
# ... ends with:
# 5xx count: 0
# OK
```

`tests/test_asgi.py` walks every route plus the static pages and prints the 5xx count. Two
known non-5xx issues surface there: `/assets/hero/turntable/001.jpg` is 404 (assets not
shipped) and the DeepSeek leg prints a fallback summariser note if the model returns no prose.

## 5. Permission conventions

Observed on this box:

| Object | Mode |
|---|---|
| `solarguard-space/` (repo root) | `2775` (setgid, group rwx) |
| `backend/`, `models/` (dirs) | `2775` |
| source files (`backend/*.py`, `public/*`, `ml/*.py`) | `664` |
| `backend/.env` | `664` |

Files are group-writable `0664`; directories are `2775` so new files inherit the group. The
setgid bit (`2xxx`) is what keeps the group consistent when the renderer/encoder or another
account writes into `renders/` or `public/assets/`.

Hardening note: `backend/.env` at `664` is world-readable on the box. The host site's own
`.env` convention is `640`, readable only by the service account. Tightening it to `640`
(`chmod 640 backend/.env`) is recommended and changes nothing functionally, since the process
runs as the file owner. Not done here because this documentation pass does not modify the
deployment.

## 6. Rollback

Backups live in `/home/hermes2/backups`. Listing as of 2026-10-07:

| File | Size | Timestamp |
|---|---|---|
| `README.md.20261007-074219.bak` | 6,171 B | 2026-10-07 07:42:19 |
| `app.py.20261007-074219.bak` | 1,596 B | 2026-10-07 07:42:19 |
| `app.py.20261007-142403.bak` | 6,399 B | 2026-10-07 14:24:03 |
| `index.html.20261007-074219.bak` | 1,066 B | 2026-10-07 07:42:19 |

These are backups of the **host site's** files (the `space-marines` app.py/README/index.html),
not of `solarguard-space`. Be aware of that when rolling back: restoring one of these will not
revert a SolarGuard change.

Rollback procedure for the host:

1. Stop or pause the uvicorn process (or let `--reload` re-import on file change).
2. Copy the newest good backup over the live file, e.g.
   `cp -p /home/hermes2/backups/app.py.20261007-142403.bak /home/hermes2/space-marines/backend/app.py`
3. Watch the server log for a clean re-import; if the process has no `--reload`, restart it.
4. Re-run §4 checks 1-5. Expected: `/solarguard` 308 → `/solarguard/`, `/solarguard/api/version`
   returns `solarguard-space`, `/api/sources` returns `12 12 8`.

Because uvicorn runs with `--reload-dir /home/hermes2/space-marines/backend`, an edit to the
host `app.py` is picked up automatically; an edit to `solarguard-space/backend/*.py` is not in
that watched directory, so a change there is only picked up when the host re-imports the
sub-app (a restart or a host-file touch). That is a deployment gap worth closing: add the
SolarGuard backend to the watched dirs, or run the sub-app behind its own process.

There is **no backup of `solarguard-space`** in `/home/hermes2/backups`. Before making
destructive changes to the repo, copy it aside first. A git initialised repo with no commits
is also not a safety net (`.git` exists, `git log` is empty).

## 7. Deploy checklist

1. `python3 -m compileall -q backend ml` — catches syntax errors before they reach the host.
2. `python3 tests/test_asgi.py` — expect `5xx count: 0`.
3. Confirm `backend/.env` exists with `DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL`, mode `640`.
4. Confirm `public/` contains no secret material. The key is only ever in `backend/.env`;
   this exact check returns no matches (it does not false-positive on the `ask-row` CSS class):
   `grep -rInE 'DEEPSEEK_API_KEY|Bearer [A-Za-z0-9]|sk-[A-Za-z0-9]{20,}' public/`
5. Touch or restart the host so the sub-app re-imports, then run §4 checks 1-7.
6. If the ML path should be live, confirm `/api/version` reports `ml+physics` (it does not
   today — the `.npz` artifacts must be regenerated first).
