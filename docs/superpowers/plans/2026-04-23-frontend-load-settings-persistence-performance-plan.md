# Frontend Load, Settings Persistence, and Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver stable <=2.0s P95 first-screen loading for core pages and prevent settings loss on page switch while preserving explicit manual save semantics.

**Architecture:** Refactor to a layered frontend state model (View -> Store/PageModel -> API client) and a thinner backend router model (Router -> Service). Add config revision-based write safety, draft persistence with unsaved-leave guard, request dedupe/cancel, and stock-list service extraction to reduce coupling and improve performance predictability.

**Tech Stack:** Vue 3, Pinia, Vue Router, Axios, TypeScript, FastAPI, Python, unittest, SQLite/JSON cache.

---

## Scope Check

This work touches one coherent subsystem chain (settings persistence + page loading + API/architecture boundaries). It should stay in a single plan because frontend and backend changes are coupled through `/api/config`, query/state contracts, and performance hot paths.

## File Structure and Responsibilities

### Frontend files
- Create: `web/frontend/src/stores/settingsDraft.ts` - draft params, dirty state, revision tracking, save/reload actions.
- Create: `web/frontend/src/stores/queryState.ts` - shared query state for Home/StrategyResults.
- Create: `web/frontend/src/api/requestManager.ts` - request dedupe/cancel utilities.
- Modify: `web/frontend/src/api/index.ts` - typed config contract + request manager integration.
- Modify: `web/frontend/src/views/SettingsView.vue` - consume settingsDraft store, no direct mutable server state.
- Modify: `web/frontend/src/router/index.ts` - unsaved-leave guard for settings route.
- Modify: `web/frontend/src/views/HomeView.vue` - shared query store + controlled loading orchestration.
- Modify: `web/frontend/src/views/StrategyResultsView.vue` - shared query store + controlled loading orchestration.
- Modify: `web/frontend/src/components/KlineChart.vue` - stale-request cancel and render throttling hooks.
- Modify: `web/frontend/package.json` and `web/frontend/vite.config.ts` - add/enable unit-test runner for TDD coverage.

### Backend files
- Create: `web/backend/services/config_service.py` - config load/save/revision logic.
- Create: `web/backend/services/stock_list_service.py` - stock list aggregation/sort/pagination orchestration.
- Modify: `web/backend/models/schemas.py` - config request/response schema with revision fields.
- Modify: `web/backend/routers/config_api.py` - read/write config via service, return 409 on revision conflict.
- Modify: `web/backend/services/strategy_service.py` - consume config_service and refresh strategy registry/runtime params.
- Modify: `strategy/strategy_registry.py` - add parameter reload/refresh API for runtime consistency.
- Modify: `web/backend/routers/stock.py` - delegate heavy logic to stock_list_service.

### Test files
- Create: `web/backend/tests/test_config_api_revision.py`
- Create: `web/backend/tests/test_stock_list_service.py`
- Create: `web/frontend/src/stores/__tests__/settingsDraft.spec.ts`
- Create: `web/frontend/src/stores/__tests__/queryState.spec.ts`
- Create: `web/frontend/src/api/__tests__/requestManager.spec.ts`
- Create: `web/frontend/src/api/__tests__/klineApi.spec.ts`

### Docs
- Modify: `README.md` (settings behavior and save conflict handling)
- Modify: `docs/technical_documentation.md` (new layering and API contract)

---

### Task 1: Frontend Test Harness (TDD foundation)

**Files:**
- Modify: `web/frontend/package.json`
- Modify: `web/frontend/vite.config.ts`
- Create: `web/frontend/src/test/setup.ts`
- Test: `web/frontend/src/stores/__tests__/settingsDraft.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// web/frontend/src/stores/__tests__/settingsDraft.spec.ts
import { describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsDraftStore } from '@/stores/settingsDraft'

describe('settingsDraft', () => {
  it('marks draft as dirty when param changes', () => {
    setActivePinia(createPinia())
    const store = useSettingsDraftStore()
    store.loadFromServer({
      revision: 'r1',
      updated_at: '2026-04-23T00:00:00Z',
      configs: [{ strategy_name: 'B1CaseStrategy', params: { lookback_days: 60 }, param_meta: {} }],
    })
    store.updateParam('B1CaseStrategy', 'lookback_days', 80)
    expect(store.isDirty).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web\frontend && npm run test -- --run src/stores/__tests__/settingsDraft.spec.ts`
Expected: FAIL with "Missing script: test" or module resolution failure.

- [ ] **Step 3: Write minimal implementation**

```json
// web/frontend/package.json (scripts/devDependencies additions)
{
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "devDependencies": {
    "vitest": "^3.2.0",
    "jsdom": "^26.1.0",
    "@vue/test-utils": "^2.4.6"
  }
}
```

```ts
// web/frontend/vite.config.ts (test section)
test: {
  environment: 'jsdom',
  setupFiles: ['./src/test/setup.ts'],
  include: ['src/**/*.spec.ts'],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web\frontend && npm run test -- --run src/stores/__tests__/settingsDraft.spec.ts`
Expected: PASS with `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/package.json web/frontend/vite.config.ts web/frontend/src/test/setup.ts web/frontend/src/stores/__tests__/settingsDraft.spec.ts
git commit -m "test(frontend): add vitest harness for state-store tdd"
```

---

### Task 2: Config Revision Contract and Backend Consistency

**Files:**
- Create: `web/backend/services/config_service.py`
- Modify: `web/backend/models/schemas.py`
- Modify: `web/backend/routers/config_api.py`
- Modify: `web/backend/services/strategy_service.py`
- Modify: `strategy/strategy_registry.py`
- Test: `web/backend/tests/test_config_api_revision.py`

- [ ] **Step 1: Write the failing test**

```python
# web/backend/tests/test_config_api_revision.py
import unittest
from fastapi.testclient import TestClient
from web.backend.main import app


class ConfigRevisionApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_config_returns_revision(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("revision", body["data"])
        self.assertIn("configs", body["data"])

    def test_post_config_rejects_stale_revision(self):
        first = self.client.get("/api/config").json()["data"]
        bad_revision = "stale-revision"
        payload = {
            "strategy_name": first["configs"][0]["strategy_name"],
            "params": first["configs"][0]["params"],
            "expected_revision": bad_revision,
        }
        res = self.client.post("/api/config", json=payload)
        self.assertEqual(res.status_code, 409)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest web.backend.tests.test_config_api_revision -v`
Expected: FAIL because `/api/config` response does not include `revision` and stale revision is not rejected.

- [ ] **Step 3: Write minimal implementation**

```python
# web/backend/models/schemas.py (add field)
class ConfigUpdateRequest(BaseModel):
    strategy_name: str
    params: Dict[str, Any]
    expected_revision: Optional[str] = None
```

```python
# web/backend/services/config_service.py (new)
import hashlib
import json
import yaml
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
CONFIG_FILE = project_root / "config" / "strategy_params.yaml"


def _load_raw_config() -> dict:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _revision_of(config: dict) -> str:
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_config_with_revision() -> tuple[dict, str]:
    config = _load_raw_config()
    return config, _revision_of(config)


def update_config_with_revision(strategy_name: str, new_params: dict, expected_revision: str | None):
    config = _load_raw_config()
    current_revision = _revision_of(config)
    if expected_revision and expected_revision != current_revision:
        return False, current_revision
    config.setdefault(strategy_name, {}).update(new_params)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    return True, _revision_of(config)
```

```python
# web/backend/routers/config_api.py (contract change)
@router.get("/config")
async def get_config():
    from web.backend.services.strategy_service import get_strategies_config
    data = get_strategies_config()
    return {"success": True, "data": data}


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
    from web.backend.services.strategy_service import update_strategy_config
    ok, revision = update_strategy_config(req.strategy_name, req.params, req.expected_revision)
    if not ok:
        raise HTTPException(status_code=409, detail="配置版本冲突，请刷新后重试")
    return {"success": True, "data": {"revision": revision}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest web.backend.tests.test_config_api_revision -v`
Expected: PASS with `OK`.

- [ ] **Step 5: Commit**

```bash
git add web/backend/models/schemas.py web/backend/routers/config_api.py web/backend/services/config_service.py web/backend/services/strategy_service.py strategy/strategy_registry.py web/backend/tests/test_config_api_revision.py
git commit -m "feat(config): add revision-safe strategy config api and runtime refresh"
```

---

### Task 3: Settings Draft Store + Unsaved Leave Guard

**Files:**
- Create: `web/frontend/src/stores/settingsDraft.ts`
- Modify: `web/frontend/src/views/SettingsView.vue`
- Modify: `web/frontend/src/router/index.ts`
- Test: `web/frontend/src/stores/__tests__/settingsDraft.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
it('keeps draft after route-like reset and clears after save success', async () => {
  setActivePinia(createPinia())
  const store = useSettingsDraftStore()
  store.loadFromServer({
    revision: 'r1',
    updated_at: '2026-04-23T00:00:00Z',
    configs: [{ strategy_name: 'B2Strategy', params: { b2_breakout_pct: 4 }, param_meta: {} }],
  })
  store.updateParam('B2Strategy', 'b2_breakout_pct', 5)
  expect(store.isDirty).toBe(true)
  store.markSaved('r2')
  expect(store.isDirty).toBe(false)
  expect(store.revision).toBe('r2')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web\frontend && npm run test -- --run src/stores/__tests__/settingsDraft.spec.ts`
Expected: FAIL because `useSettingsDraftStore` does not exist.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/frontend/src/stores/settingsDraft.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useSettingsDraftStore = defineStore('settingsDraft', () => {
  const revision = ref('')
  const serverConfigs = ref<any[]>([])
  const draftConfigs = ref<any[]>([])
  const isDirty = computed(() => JSON.stringify(serverConfigs.value) !== JSON.stringify(draftConfigs.value))

  function loadFromServer(payload: { revision: string; configs: any[] }) {
    revision.value = payload.revision
    serverConfigs.value = structuredClone(payload.configs)
    draftConfigs.value = structuredClone(payload.configs)
  }

  function updateParam(strategyName: string, key: string, value: number) {
    const cfg = draftConfigs.value.find((c: any) => c.strategy_name === strategyName)
    if (!cfg) return
    cfg.params[key] = value
  }

  function markSaved(newRevision: string) {
    revision.value = newRevision
    serverConfigs.value = structuredClone(draftConfigs.value)
  }

  return { revision, serverConfigs, draftConfigs, isDirty, loadFromServer, updateParam, markSaved }
})
```

```ts
// web/frontend/src/router/index.ts (guard)
import { useSettingsDraftStore } from '@/stores/settingsDraft'

router.beforeEach((to, from, next) => {
  if (from.name === 'Settings') {
    const draft = useSettingsDraftStore()
    if (draft.isDirty && !window.confirm('参数尚未保存，确认离开吗？')) {
      next(false)
      return
    }
  }
  next()
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web\frontend && npm run test -- --run src/stores/__tests__/settingsDraft.spec.ts`
Expected: PASS with `2 passed` (including Task 1 case).

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/stores/settingsDraft.ts web/frontend/src/views/SettingsView.vue web/frontend/src/router/index.ts web/frontend/src/stores/__tests__/settingsDraft.spec.ts
git commit -m "feat(settings): add draft state and unsaved-leave guard"
```

---

### Task 4: Request Manager and Shared Query State for Home/Results

**Files:**
- Create: `web/frontend/src/api/requestManager.ts`
- Create: `web/frontend/src/stores/queryState.ts`
- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/views/HomeView.vue`
- Modify: `web/frontend/src/views/StrategyResultsView.vue`
- Test: `web/frontend/src/api/__tests__/requestManager.spec.ts`
- Test: `web/frontend/src/stores/__tests__/queryState.spec.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// requestManager.spec.ts
import { describe, it, expect } from 'vitest'
import { createRequestManager } from '@/api/requestManager'

describe('requestManager', () => {
  it('cancels older request with same key', () => {
    const manager = createRequestManager()
    const first = manager.start('results:list')
    const second = manager.start('results:list')
    expect(first.signal.aborted).toBe(true)
    expect(second.signal.aborted).toBe(false)
  })
})
```

```ts
// queryState.spec.ts
import { describe, it, expect } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useQueryStateStore } from '@/stores/queryState'

describe('queryState', () => {
  it('persists results filters in store', () => {
    setActivePinia(createPinia())
    const s = useQueryStateStore()
    s.setResultsKeyword('军工')
    expect(s.results.keyword).toBe('军工')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web\frontend && npm run test -- --run src/api/__tests__/requestManager.spec.ts src/stores/__tests__/queryState.spec.ts`
Expected: FAIL because modules do not exist.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/frontend/src/api/requestManager.ts
export function createRequestManager() {
  const controllers = new Map<string, AbortController>()
  function start(key: string) {
    controllers.get(key)?.abort()
    const controller = new AbortController()
    controllers.set(key, controller)
    return controller
  }
  function clear(key: string) {
    controllers.delete(key)
  }
  return { start, clear }
}
```

```ts
// web/frontend/src/stores/queryState.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useQueryStateStore = defineStore('queryState', () => {
  const results = ref({ page: 1, perPage: 50, keyword: '', strategy: 'all' })
  function setResultsKeyword(keyword: string) {
    results.value.keyword = keyword
    results.value.page = 1
  }
  return { results, setResultsKeyword }
})
```

- [ ] **Step 4: Run tests and type build**

Run: `cd web\frontend && npm run test -- --run src/api/__tests__/requestManager.spec.ts src/stores/__tests__/queryState.spec.ts`
Expected: PASS.

Run: `cd web\frontend && npm run build`
Expected: build succeeds without TS errors.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/api/requestManager.ts web/frontend/src/stores/queryState.ts web/frontend/src/api/index.ts web/frontend/src/views/HomeView.vue web/frontend/src/views/StrategyResultsView.vue web/frontend/src/api/__tests__/requestManager.spec.ts web/frontend/src/stores/__tests__/queryState.spec.ts
git commit -m "refactor(frontend): centralize request control and page query state"
```

---

### Task 5: Stock List Service Extraction and Backend Performance Guardrails

**Files:**
- Create: `web/backend/services/stock_list_service.py`
- Modify: `web/backend/routers/stock.py`
- Test: `web/backend/tests/test_stock_list_service.py`

- [ ] **Step 1: Write the failing test**

```python
# web/backend/tests/test_stock_list_service.py
import unittest
from web.backend.services.stock_list_service import paginate_codes


class StockListServiceTest(unittest.TestCase):
    def test_paginate_codes_respects_page_and_size(self):
        codes = [f"{i:06d}" for i in range(1, 21)]
        page_codes, total = paginate_codes(codes, page=2, per_page=5)
        self.assertEqual(total, 20)
        self.assertEqual(page_codes, ["000006", "000007", "000008", "000009", "000010"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest web.backend.tests.test_stock_list_service -v`
Expected: FAIL because `stock_list_service` module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# web/backend/services/stock_list_service.py
def paginate_codes(codes: list[str], page: int, per_page: int):
    start = (page - 1) * per_page
    return codes[start:start + per_page], len(codes)
```

```python
# web/backend/routers/stock.py (delegation pattern)
from web.backend.services.stock_list_service import paginate_codes

# inside get_stock_list(...)
page_codes, total = paginate_codes(ordered_codes, page=page, per_page=per_page)
```

- [ ] **Step 4: Run test and API smoke check**

Run: `python -m unittest web.backend.tests.test_stock_list_service -v`
Expected: PASS with `OK`.

Run: `python -c "from web.backend.main import app; print('app_ready')"`
Expected: outputs `app_ready`.

- [ ] **Step 5: Commit**

```bash
git add web/backend/services/stock_list_service.py web/backend/routers/stock.py web/backend/tests/test_stock_list_service.py
git commit -m "refactor(backend): extract stock list orchestration into service layer"
```

---

### Task 6: Kline Request Cancellation + Final Docs and Regression Pass

**Files:**
- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/components/KlineChart.vue`
- Modify: `README.md`
- Modify: `docs/technical_documentation.md`

- [ ] **Step 1: Write the failing test**

```ts
// web/frontend/src/api/__tests__/klineApi.spec.ts
import { describe, it, expect, vi } from 'vitest'
import api, { getKline } from '@/api'

describe('getKline', () => {
  it('forwards AbortSignal to axios request config', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({ data: { data: {} } } as any)
    const controller = new AbortController()
    await getKline('600000', { period: 'daily', limit: 2600, adjust: 'qfq' }, controller.signal)
    expect(spy).toHaveBeenCalledWith('/kline/600000', {
      params: { period: 'daily', limit: 2600, adjust: 'qfq' },
      signal: controller.signal,
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web\frontend && npm run test -- --run src/api/__tests__/klineApi.spec.ts`
Expected: FAIL because `getKline` does not accept `signal` yet.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/frontend/src/api/index.ts
export const getKline = (
  code: string,
  params?: { period?: string; limit?: number; adjust?: 'qfq' | 'hfq' | 'nfq' },
  signal?: AbortSignal,
) => api.get(`/kline/${code}`, { params, signal })
```

```ts
// web/frontend/src/components/KlineChart.vue (inside renderChart)
const reqKey = `kline:${props.code}:${props.period}:${props.adjust}`
const controller = requestManager.start(reqKey)
const res = await getKline(
  props.code,
  { period: props.period, limit: props.limit, adjust: props.adjust as 'qfq' | 'hfq' | 'nfq' },
  controller.signal,
)
```

- [ ] **Step 4: Run final regression commands**

Run: `cd web\frontend && npm run test -- --run`
Expected: all frontend unit tests pass.

Run: `cd web\frontend && npm run build`
Expected: build succeeds.

Run: `python -m unittest web.backend.tests.test_config_api_revision web.backend.tests.test_stock_list_service -v`
Expected: all backend tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/api/index.ts web/frontend/src/components/KlineChart.vue README.md docs/technical_documentation.md
git commit -m "perf(web): cancel stale kline requests and document new contracts"
```

---

## Self-Review (Plan vs Spec)

1. **Spec coverage**
   - 模块耦合度：Task 4/5 处理前端与后端解耦。
   - 接口设计：Task 2 处理 `/api/config` revision 契约与冲突语义。
   - 性能瓶颈：Task 4/5/6 处理请求治理、stock list 分层、Kline stale request。
   - 参数丢失：Task 3 处理草稿保留和离开提醒。
   - 文件清单与风险：已在 spec 明确；本计划映射为可执行任务。
2. **Placeholder scan**
   - 无 TBD/TODO/“后续补充”等占位符。
3. **Type consistency**
   - `expected_revision`, `revision`, `useSettingsDraftStore`, `useQueryStateStore`, `createRequestManager` 在任务内保持一致。

