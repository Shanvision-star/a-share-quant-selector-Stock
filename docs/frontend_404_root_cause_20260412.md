# Frontend 404 Root Cause Analysis and Fix

## Symptom

- Accessing `http://localhost:5173/` returned `HTTP ERROR 404`.
- Running `npm run dev` in the repository root failed because there is no root `package.json`.
- Running `npm run dev` in `web` started a Vite server, but the page was still 404.

## Root Cause

The actual Vue + Vite frontend project is located in `web/frontend`, not in `web`.

The following structure shows the mismatch:

- `web/frontend/index.html`
- `web/frontend/src/main.ts`
- `web/frontend/package.json`

However, a temporary `web/package.json` was later created manually and configured to run `vite` directly inside `web`.

That `web` directory does not contain the required Vite entry files:

- missing `web/index.html`
- missing `web/src/main.ts`

As a result, starting Vite inside `web` produced a running dev server with no application entry page, so requesting `/` returned 404.

## Why the Browser Showed 404 Instead of Connection Refused

This distinction is important:

- `connection refused` means the dev server did not start.
- `404` means the dev server started, but the requested route or entry document was not found.

In this case, Vite in `web` was running, but there was no `index.html` to serve from that directory.

## Fix Applied

Updated `web/package.json` to delegate all web commands to the real frontend project under `web/frontend`.

An important implementation detail was also corrected:

- `npm --prefix frontend run dev` is not enough for Vite, because it does not switch the process working directory to `web/frontend`
- Vite uses the current working directory to determine its project root
- therefore the wrapper must explicitly `cd frontend` before starting Vite

The final usable command path is to enter `frontend` and run that project's own Vite command.

Current wrapper behavior:

- `npm run dev` now runs `cd frontend && npm run dev -- --host 0.0.0.0`
- `npm run build` now runs `cd frontend && npm run build`
- `npm run serve` now runs `cd frontend && npm run preview -- --host 0.0.0.0`

## Why Explicit `--root` Was Necessary

Although switching directories or using `--prefix` may appear sufficient, the observed runtime behavior still showed:

- `http://localhost:5173/@vite/client` returned 200
- `http://localhost:5173/index.html` returned 404
- `http://localhost:5173/src/main.ts` returned 404

That means Vite itself was running, but its project root was still not resolving to the actual frontend source tree.

This ensures the frontend package runs with its own local `package.json`, dependencies, and Vite runtime context.

## Final Root Cause

There were actually two overlapping problems:

1. The wrong directory (`web`) was initially treated as if it were the Vite app root.
2. A stale old Vite process remained bound to `127.0.0.1:5173`.

The second problem made diagnosis confusing because:

- the correct frontend Vite instance was already listening on `0.0.0.0:5173`
- but browser requests to `localhost:5173` were being handled by the stale `127.0.0.1:5173` process first
- that stale process returned 404 for `/` and `/src/main.ts`

After terminating the stale localhost-only process, the correct frontend server immediately returned:

- `GET /` -> 200
- `GET /src/main.ts` -> 200

This confirmed the frontend project itself was healthy and the remaining issue was port ownership by an obsolete dev server process.

This preserves `web` as the command entry directory while ensuring the actual frontend app is launched.

## Correct Usage After Fix

From the `web` directory:

```powershell
npm run dev
```

Or directly from the real frontend directory:

```powershell
cd web/frontend
npm run dev
```

## Expected Result

After the fix, Vite should serve the application from the real frontend project and `http://localhost:5173/` should return the Vue app instead of 404.

## Follow-up Recommendation

To avoid future confusion:

- treat `web/frontend` as the actual frontend source tree
- use `web` only as a convenience command wrapper for frontend and backend-related web tasks
- avoid installing separate Vite app dependencies directly into `web` unless `web` itself is intentionally converted into the frontend root