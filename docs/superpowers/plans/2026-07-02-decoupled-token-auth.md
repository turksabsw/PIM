# Decoupled Frontend + Token Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ayrı deploy edilen Vue SPA (pim.atonota.net) ile Frappe backend (pimcronbi.cronbi.com) arasında token tabanlı login/register akışı kurmak.

**Architecture:** Frontend cross-origin olduğu için cookie yerine Frappe'nin `api_key:api_secret` token'ını kullanır. Backend guest'e açık `login`/`register`/`me` endpoint'leri sağlar; frontend token'ı localStorage'da tutup her istekte `Authorization: token ...` header'ı gönderir.

**Tech Stack:** Backend: Frappe v15 / Python. Frontend: Vue 3 + TypeScript + Pinia + Vue Router + Tailwind + axios + Vite.

## Global Constraints

- Backend repo: `/home/metin/Desktop/pim/PIM` (branch: `feat/decoupled-token-auth`).
- Frontend repo: `/home/metin/Desktop/pim/Pim-Frontend`.
- Prod API base URL: `https://pimcronbi.cronbi.com` (verbatim).
- Auth header formatı: `token <api_key>:<api_secret>` (verbatim).
- localStorage token anahtarı: `pim-auth-token` (verbatim).
- Backend auth endpoint namespace: `frappe_pim.pim.api.auth`.
- Backend testleri bir Frappe bench üzerinde çalışır: `bench --site <site> run-tests --module <module>`. Yerel bench yoksa, deploy sonrası curl ile manuel doğrulama (her backend task'ın sonunda verilir).
- Frontend'de test runner **yok**; frontend doğrulaması `npm run type-check` + `npm run build` + tarayıcıda manuel kontrol ile yapılır.
- Mevcut Tailwind stil dili ve Pinia setup-store deseni korunur.

---

## Testing Approach Note

Bu proje iki farklı test gerçekliğine sahip:
- **Backend:** Frappe test framework mevcut (`frappe_pim/pim/tests/`). TDD uygulanır: önce test, sonra kod. Testler bir bench'te koşar.
- **Frontend:** Test runner kurulu değil ve kurmak bu iş için kapsam dışı (YAGNI). Doğrulama derleme + tip kontrolü + manuel tarayıcı testi ile yapılır. Her frontend task'ında doğrulama adımı bunu yansıtır.

---

## Task 1: Backend — `auth.login` + token credential helper

**Files:**
- Create: `frappe_pim/pim/api/auth.py`
- Test: `frappe_pim/pim/tests/test_auth_api.py`

**Interfaces:**
- Produces:
  - `login(usr: str, pwd: str) -> dict` → `{"api_key", "api_secret", "user", "full_name"}`; geçersiz/disabled kullanıcıda `frappe.AuthenticationError`.
  - `_resolve_user(usr: str) -> str | None`
  - `_get_or_create_api_credentials(user: str) -> tuple[str, str]`

- [ ] **Step 1: Testi yaz**

`frappe_pim/pim/tests/test_auth_api.py`:

```python
import frappe
import unittest
from frappe.utils.password import update_password
from frappe_pim.pim.api import auth


class TestAuthAPI(unittest.TestCase):
    test_email = "pim_auth_test@example.com"
    test_pwd = "Secret@12345"

    @classmethod
    def setUpClass(cls):
        if not frappe.db.exists("User", cls.test_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": cls.test_email,
                "first_name": "Auth",
                "last_name": "Test",
                "send_welcome_email": 0,
                "enabled": 1,
            })
            user.insert(ignore_permissions=True)
        update_password(cls.test_email, cls.test_pwd)
        frappe.db.commit()

    def test_login_success_returns_token(self):
        result = auth.login(self.test_email, self.test_pwd)
        self.assertTrue(result["api_key"])
        self.assertTrue(result["api_secret"])
        self.assertEqual(result["user"], self.test_email)

    def test_login_token_is_stable_across_calls(self):
        first = auth.login(self.test_email, self.test_pwd)
        second = auth.login(self.test_email, self.test_pwd)
        self.assertEqual(first["api_key"], second["api_key"])
        self.assertEqual(first["api_secret"], second["api_secret"])

    def test_login_wrong_password_raises(self):
        with self.assertRaises(frappe.AuthenticationError):
            auth.login(self.test_email, "wrong-password")

    def test_login_unknown_user_raises(self):
        with self.assertRaises(frappe.AuthenticationError):
            auth.login("nobody@nowhere.invalid", "whatever")
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'frappe_pim.pim.api.auth' has no attribute 'login'`.

- [ ] **Step 3: Minimal implementasyonu yaz**

`frappe_pim/pim/api/auth.py`:

```python
"""PIM Token-based Authentication API.

Guest-accessible endpoints for a decoupled SPA frontend hosted on a different
origin. Uses Frappe's api_key:api_secret token auth so the frontend never
depends on cross-site cookies.
"""

import frappe
from frappe import _
from frappe.utils.password import check_password, get_decrypted_password


def _resolve_user(usr):
    """Resolve a login identifier (email or username) to a User name."""
    if not usr:
        return None
    if frappe.db.exists("User", usr):
        return usr
    return frappe.db.get_value("User", {"username": usr}, "name")


def _get_or_create_api_credentials(user):
    """Return a stable (api_key, api_secret) pair for the user, creating if absent."""
    user_doc = frappe.get_doc("User", user)
    changed = False

    if not user_doc.api_key:
        user_doc.api_key = frappe.generate_hash(length=15)
        changed = True

    api_secret = None
    if user_doc.api_secret:
        api_secret = get_decrypted_password("User", user, "api_secret")

    if not api_secret:
        api_secret = frappe.generate_hash(length=15)
        user_doc.api_secret = api_secret
        changed = True

    if changed:
        user_doc.save(ignore_permissions=True)
        frappe.db.commit()

    return user_doc.api_key, api_secret


@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    """Authenticate and return an API token (api_key:api_secret)."""
    user = _resolve_user(usr)
    if not user:
        frappe.throw(_("Invalid login credentials"), frappe.AuthenticationError)

    # Raises frappe.AuthenticationError on mismatch.
    check_password(user, pwd)

    if not frappe.db.get_value("User", user, "enabled"):
        frappe.throw(_("User account is disabled"), frappe.AuthenticationError)

    api_key, api_secret = _get_or_create_api_credentials(user)

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
    }
```

- [ ] **Step 4: Testi çalıştır, geçtiğini gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: 4 test PASS.

(Yerel bench yoksa bu adımı deploy sonrası curl ile doğrula:
`curl -X POST https://pimcronbi.cronbi.com/api/method/frappe_pim.pim.api.auth.login -d 'usr=<email>&pwd=<pwd>'` → JSON içinde `message.api_key` dönmeli.)

- [ ] **Step 5: Commit**

```bash
cd /home/metin/Desktop/pim/PIM
git add frappe_pim/pim/api/auth.py frappe_pim/pim/tests/test_auth_api.py
git commit -m "feat(auth): token-based login endpoint"
```

---

## Task 2: Backend — `auth.register` (public self-signup)

**Files:**
- Modify: `frappe_pim/pim/api/auth.py`
- Test: `frappe_pim/pim/tests/test_auth_api.py`

**Interfaces:**
- Consumes: Frappe `frappe.core.doctype.user.user.sign_up`.
- Produces: `register(email: str, full_name: str) -> dict` → `{"status": int, "message": str}`.

- [ ] **Step 1: Testi yaz (mevcut test dosyasına ekle)**

`test_auth_api.py` içine, `TestAuthAPI` sınıfına ekle:

```python
    def test_register_creates_user_when_signup_enabled(self):
        ws = frappe.get_single("Website Settings")
        ws.disable_signup = 0
        ws.save(ignore_permissions=True)
        frappe.db.commit()

        new_email = "pim_signup_test@example.com"
        if frappe.db.exists("User", new_email):
            frappe.delete_doc("User", new_email, ignore_permissions=True, force=True)
            frappe.db.commit()

        result = auth.register(new_email, "Signup Test")
        self.assertIn("status", result)
        self.assertTrue(frappe.db.exists("User", new_email))
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: FAIL — `AttributeError: module ... has no attribute 'register'`.

- [ ] **Step 3: Implementasyonu yaz (auth.py sonuna ekle)**

```python
@frappe.whitelist(allow_guest=True)
def register(email, full_name):
    """Public self-signup: create a Website User and send a verification email.

    Requires Website Settings signup to be enabled (disable_signup = 0).
    Frappe's sign_up throws if signup is disabled; that error propagates to the
    frontend which surfaces the server message.
    """
    from frappe.core.doctype.user.user import sign_up

    status, message = sign_up(email, full_name, redirect_to="")
    return {"status": status, "message": message}
```

- [ ] **Step 4: Testi çalıştır, geçtiğini gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: tüm testler PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/metin/Desktop/pim/PIM
git add frappe_pim/pim/api/auth.py frappe_pim/pim/tests/test_auth_api.py
git commit -m "feat(auth): public self-signup register endpoint"
```

---

## Task 3: Backend — `auth.me` (token doğrulama)

**Files:**
- Modify: `frappe_pim/pim/api/auth.py`
- Test: `frappe_pim/pim/tests/test_auth_api.py`

**Interfaces:**
- Produces: `me() -> dict` → guest için `{"authenticated": False}`, aksi halde `{"authenticated": True, "user": str, "full_name": str}`.

- [ ] **Step 1: Testi yaz (sınıfa ekle)**

```python
    def test_me_returns_current_user(self):
        original = frappe.session.user
        try:
            frappe.set_user(self.test_email)
            result = auth.me()
            self.assertTrue(result["authenticated"])
            self.assertEqual(result["user"], self.test_email)
        finally:
            frappe.set_user(original)

    def test_me_guest_is_not_authenticated(self):
        original = frappe.session.user
        try:
            frappe.set_user("Guest")
            result = auth.me()
            self.assertFalse(result["authenticated"])
        finally:
            frappe.set_user(original)
```

- [ ] **Step 2: Testi çalıştır, başarısız olduğunu gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: FAIL — `AttributeError: module ... has no attribute 'me'`.

- [ ] **Step 3: Implementasyonu yaz (auth.py sonuna ekle)**

```python
@frappe.whitelist(allow_guest=True)
def me():
    """Return the current user resolved from the Authorization token header."""
    user = frappe.session.user
    if not user or user == "Guest":
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": user,
        "full_name": frappe.db.get_value("User", user, "full_name"),
    }
```

- [ ] **Step 4: Testi çalıştır, geçtiğini gör**

Run: `bench --site <site> run-tests --module frappe_pim.pim.tests.test_auth_api`
Expected: tüm testler PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/metin/Desktop/pim/PIM
git add frappe_pim/pim/api/auth.py frappe_pim/pim/tests/test_auth_api.py
git commit -m "feat(auth): me endpoint for token validation"
```

---

## Task 4: Backend — "Allow Sign Up" patch

**Files:**
- Create: `frappe_pim/patches/v1_0/enable_website_signup.py`
- Modify: `frappe_pim/patches.txt`

**Interfaces:**
- Produces: `execute()` — migrate sırasında `Website Settings.disable_signup = 0` yapar.

- [ ] **Step 1: Patch'i yaz**

`frappe_pim/patches/v1_0/enable_website_signup.py`:

```python
import frappe


def execute():
    """Enable public website signup so the SPA register tab works."""
    ws = frappe.get_single("Website Settings")
    if ws.disable_signup:
        ws.disable_signup = 0
        ws.save(ignore_permissions=True)
        frappe.db.commit()
```

- [ ] **Step 2: patches.txt'e kaydet**

`frappe_pim/patches.txt` sonuna ekle:

```
# Enable public website signup for decoupled SPA register tab
frappe_pim.patches.v1_0.enable_website_signup
```

- [ ] **Step 3: Doğrula (bench varsa)**

Run: `bench --site <site> migrate`
Expected: patch hatasız çalışır; `bench --site <site> execute "frappe.client.get_single_value" --args "['Website Settings','disable_signup']"` → `0`.

(Bench yoksa manuel alternatif: Frappe Desk → Website Settings → "Disable Signup" kutusunu kapat.)

- [ ] **Step 4: Commit**

```bash
cd /home/metin/Desktop/pim/PIM
git add frappe_pim/patches/v1_0/enable_website_signup.py frappe_pim/patches.txt
git commit -m "feat(auth): patch to enable website signup"
```

---

## Task 5: Frontend — API config + token storage helpers

**Files:**
- Create: `src/config/api.ts`
- Create: `src/config/authToken.ts`
- Modify: `env.d.ts`

**Interfaces:**
- Produces:
  - `API_BASE_URL: string`
  - `interface AuthToken { api_key: string; api_secret: string }`
  - `getStoredToken(): AuthToken | null`
  - `setStoredToken(t: AuthToken): void`
  - `clearStoredToken(): void`
  - `authHeader(): string | null`

- [ ] **Step 1: `src/config/api.ts` oluştur**

```ts
/**
 * Backend API base URL.
 * - Production: baked from VITE_API_BASE_URL (.env.production) → absolute cloud URL.
 * - Dev: undefined → '' → Vite dev proxy handles /api (same-origin, no CORS).
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''
```

- [ ] **Step 2: `src/config/authToken.ts` oluştur**

```ts
/**
 * Token storage for cross-origin Frappe API auth.
 * Stores the api_key:api_secret pair in localStorage and builds the
 * Authorization header. Shared by useFrappeAPI (request interceptor) and the
 * auth store to avoid circular imports.
 */

const TOKEN_KEY = 'pim-auth-token'

export interface AuthToken {
  api_key: string
  api_secret: string
}

export function getStoredToken(): AuthToken | null {
  const raw = localStorage.getItem(TOKEN_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthToken
  } catch {
    return null
  }
}

export function setStoredToken(token: AuthToken): void {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(token))
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** Frappe token auth header, or null if not logged in. */
export function authHeader(): string | null {
  const token = getStoredToken()
  return token ? `token ${token.api_key}:${token.api_secret}` : null
}
```

- [ ] **Step 3: `env.d.ts`'e tip ekle**

`env.d.ts` dosyasına (mevcut `declare module '*.vue'` bloğundan önce) ekle:

```ts
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
```

- [ ] **Step 4: Tip kontrolü**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check`
Expected: yeni dosyalar için hata yok (projede önceden var olan hatalar hariç).

- [ ] **Step 5: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/config/api.ts src/config/authToken.ts env.d.ts
git commit -m "feat(auth): api base url config and token storage helpers"
```

---

## Task 6: Frontend — `useFrappeAPI` token interceptor'a geçiş

**Files:**
- Modify: `src/composables/useFrappeAPI.ts`

**Interfaces:**
- Consumes: `API_BASE_URL`, `authHeader`, `clearStoredToken` (Task 5).
- Produces: axios instance artık `Authorization: token ...` gönderir; CSRF/cookie mantığı kaldırılmıştır. `useFrappeAPI()` genel imzası değişmez.

- [ ] **Step 1: Import'ları güncelle (dosyanın en üstü, mevcut `import type ... '@/types'` bloğundan sonra)**

```ts
import { API_BASE_URL } from '@/config/api'
import { authHeader, clearStoredToken } from '@/config/authToken'
```

- [ ] **Step 2: CSRF blok(lar)ını kaldır**

`getCSRFToken` fonksiyonunu (yakl. satır 34-68) ve `clearCSRFToken` export'unu (yakl. satır 71-73) **sil**. `_csrfToken` değişkenini de sil (yakl. satır 30).

- [ ] **Step 3: `createFrappeAxios` gövdesini değiştir**

Mevcut `axios.create({...})` çağrısı ve iki interceptor'u aşağıdakiyle değiştir:

```ts
function createFrappeAxios(): AxiosInstance {
  const instance = axios.create({
    baseURL: API_BASE_URL || '/',
    timeout: 30000,
    withCredentials: false,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
  })

  // Request interceptor: attach the token auth header when logged in.
  instance.interceptors.request.use((config) => {
    const header = authHeader()
    if (header) {
      config.headers['Authorization'] = header
    }
    return config
  })

  // Response interceptor: on auth failure, drop the token and go to login.
  instance.interceptors.response.use(
    (response) => response,
    (error: AxiosError) => {
      const status = error.response?.status
      if (status === 401 || status === 403) {
        clearStoredToken()
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
      }
      return Promise.reject(error)
    },
  )

  return instance
}
```

- [ ] **Step 4: Tip kontrolü + build**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check && npx vite build`
Expected: `clearCSRFToken`/`getCSRFToken` referans hatası yok, build başarılı.

- [ ] **Step 5: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/composables/useFrappeAPI.ts
git commit -m "feat(auth): switch useFrappeAPI to token auth"
```

---

## Task 7: Frontend — auth store (Pinia)

**Files:**
- Create: `src/stores/auth.ts`

**Interfaces:**
- Consumes: `useFrappeAPI` (`callMethod`), `authToken` helpers (Task 5).
- Produces: `useAuthStore()` →
  - state: `user: { name: string; full_name: string } | null`
  - getter: `isAuthenticated: boolean`
  - `login(usr: string, pwd: string): Promise<void>`
  - `register(email: string, full_name: string): Promise<{ status: number; message: string }>`
  - `logout(): void`
  - `fetchCurrentUser(): Promise<void>`

- [ ] **Step 1: `src/stores/auth.ts` oluştur**

```ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useFrappeAPI } from '@/composables/useFrappeAPI'
import {
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  type AuthToken,
} from '@/config/authToken'

interface AuthUser {
  name: string
  full_name: string
}

interface LoginResponse extends AuthToken {
  user: string
  full_name: string
}

interface RegisterResponse {
  status: number
  message: string
}

interface MeResponse {
  authenticated: boolean
  user?: string
  full_name?: string
}

export const useAuthStore = defineStore('auth', () => {
  const { callMethod } = useFrappeAPI()

  const user = ref<AuthUser | null>(null)

  const isAuthenticated = computed(() => getStoredToken() !== null)

  async function login(usr: string, pwd: string): Promise<void> {
    const res = await callMethod<LoginResponse>(
      'frappe_pim.pim.api.auth.login',
      { usr, pwd },
    )
    setStoredToken({ api_key: res.api_key, api_secret: res.api_secret })
    user.value = { name: res.user, full_name: res.full_name }
  }

  async function register(
    email: string,
    full_name: string,
  ): Promise<RegisterResponse> {
    return callMethod<RegisterResponse>(
      'frappe_pim.pim.api.auth.register',
      { email, full_name },
    )
  }

  function logout(): void {
    clearStoredToken()
    user.value = null
    window.location.href = '/login'
  }

  async function fetchCurrentUser(): Promise<void> {
    if (!getStoredToken()) {
      user.value = null
      return
    }
    try {
      const res = await callMethod<MeResponse>('frappe_pim.pim.api.auth.me')
      if (res.authenticated && res.user) {
        user.value = { name: res.user, full_name: res.full_name ?? res.user }
      } else {
        clearStoredToken()
        user.value = null
      }
    } catch {
      clearStoredToken()
      user.value = null
    }
  }

  return { user, isAuthenticated, login, register, logout, fetchCurrentUser }
})
```

- [ ] **Step 2: Tip kontrolü**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check`
Expected: yeni store için hata yok.

- [ ] **Step 3: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/stores/auth.ts
git commit -m "feat(auth): pinia auth store"
```

---

## Task 8: Frontend — LoginPage iki sekmeli (Login/Register) yeniden yazım

**Files:**
- Modify: `src/views/auth/LoginPage.vue` (tamamen değiştirilir)

**Interfaces:**
- Consumes: `useAuthStore` (Task 7), `useRouter`.

- [ ] **Step 1: `LoginPage.vue`'yu değiştir**

Dosyanın tamamını şununla değiştir:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

type Tab = 'login' | 'register'

const router = useRouter()
const authStore = useAuthStore()

const tab = ref<Tab>('login')
const error = ref('')
const info = ref('')
const loading = ref(false)

// Login fields
const usr = ref('')
const pwd = ref('')

// Register fields
const email = ref('')
const fullName = ref('')

function switchTab(next: Tab): void {
  tab.value = next
  error.value = ''
  info.value = ''
}

async function handleLogin(): Promise<void> {
  error.value = ''
  info.value = ''
  loading.value = true
  try {
    await authStore.login(usr.value, pwd.value)
    router.push('/')
  } catch (e) {
    error.value = extractMessage(e, 'Giriş başarısız')
  } finally {
    loading.value = false
  }
}

async function handleRegister(): Promise<void> {
  error.value = ''
  info.value = ''
  loading.value = true
  try {
    await authStore.register(email.value, fullName.value)
    info.value = 'Hesabın oluşturuldu. E-postana gönderilen bağlantıyla doğrula, sonra giriş yap.'
    switchTab('login')
    info.value = 'Hesabın oluşturuldu. E-postana gönderilen bağlantıyla doğrula, sonra giriş yap.'
  } catch (e) {
    error.value = extractMessage(e, 'Kayıt başarısız')
  } finally {
    loading.value = false
  }
}

function extractMessage(e: unknown, fallback: string): string {
  const err = e as { response?: { data?: { message?: string; _server_messages?: string } } }
  const data = err?.response?.data
  if (data?.message) return data.message
  if (data?._server_messages) {
    try {
      const arr = JSON.parse(data._server_messages)
      const first = JSON.parse(arr[0])
      return first.message || fallback
    } catch {
      return fallback
    }
  }
  return fallback
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
    <div class="w-full max-w-sm">
      <div class="rounded-lg border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-800">
        <h1 class="mb-6 text-center text-2xl font-bold text-gray-900 dark:text-white">PIM</h1>

        <!-- Tabs -->
        <div class="mb-6 grid grid-cols-2 rounded-lg bg-gray-100 p-1 dark:bg-gray-700">
          <button
            type="button"
            @click="switchTab('login')"
            :class="[
              'rounded-md py-2 text-sm font-medium transition',
              tab === 'login' ? 'bg-white text-gray-900 shadow dark:bg-gray-800 dark:text-white' : 'text-gray-500 dark:text-gray-300',
            ]"
          >
            Giriş
          </button>
          <button
            type="button"
            @click="switchTab('register')"
            :class="[
              'rounded-md py-2 text-sm font-medium transition',
              tab === 'register' ? 'bg-white text-gray-900 shadow dark:bg-gray-800 dark:text-white' : 'text-gray-500 dark:text-gray-300',
            ]"
          >
            Kayıt Ol
          </button>
        </div>

        <div v-if="error" class="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600 dark:bg-red-900/30 dark:text-red-400">
          {{ error }}
        </div>
        <div v-if="info" class="mb-4 rounded-lg bg-green-50 p-3 text-sm text-green-700 dark:bg-green-900/30 dark:text-green-400">
          {{ info }}
        </div>

        <!-- Login form -->
        <form v-if="tab === 'login'" @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <label for="usr" class="mb-2 block text-sm font-medium text-gray-900 dark:text-white">E-posta veya kullanıcı adı</label>
            <input id="usr" v-model="usr" type="text" required autofocus
              class="block w-full rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 focus:border-primary-600 focus:ring-primary-600 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
              placeholder="ornek@firma.com" />
          </div>
          <div>
            <label for="pwd" class="mb-2 block text-sm font-medium text-gray-900 dark:text-white">Parola</label>
            <input id="pwd" v-model="pwd" type="password" required
              class="block w-full rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 focus:border-primary-600 focus:ring-primary-600 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
              placeholder="Parola" />
          </div>
          <button type="submit" :disabled="loading"
            class="w-full rounded-lg bg-primary-600 px-5 py-2.5 text-center text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-4 focus:ring-primary-300 disabled:opacity-50">
            {{ loading ? 'Giriş yapılıyor...' : 'Giriş Yap' }}
          </button>
        </form>

        <!-- Register form -->
        <form v-else @submit.prevent="handleRegister" class="space-y-4">
          <div>
            <label for="fullName" class="mb-2 block text-sm font-medium text-gray-900 dark:text-white">Ad Soyad</label>
            <input id="fullName" v-model="fullName" type="text" required autofocus
              class="block w-full rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 focus:border-primary-600 focus:ring-primary-600 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
              placeholder="Ad Soyad" />
          </div>
          <div>
            <label for="email" class="mb-2 block text-sm font-medium text-gray-900 dark:text-white">E-posta</label>
            <input id="email" v-model="email" type="email" required
              class="block w-full rounded-lg border border-gray-300 bg-gray-50 p-2.5 text-sm text-gray-900 focus:border-primary-600 focus:ring-primary-600 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
              placeholder="ornek@firma.com" />
          </div>
          <button type="submit" :disabled="loading"
            class="w-full rounded-lg bg-primary-600 px-5 py-2.5 text-center text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-4 focus:ring-primary-300 disabled:opacity-50">
            {{ loading ? 'Kaydediliyor...' : 'Kayıt Ol' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Tip kontrolü + build**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check && npx vite build`
Expected: hata yok.

- [ ] **Step 3: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/views/auth/LoginPage.vue
git commit -m "feat(auth): two-tab login/register page"
```

---

## Task 9: Frontend — router auth guard

**Files:**
- Modify: `src/router/index.ts`

**Interfaces:**
- Consumes: `useAuthStore` (Task 7).

- [ ] **Step 1: Import ekle (`src/router/index.ts` en üstteki import'lara)**

```ts
import { useAuthStore } from '@/stores/auth'
```

- [ ] **Step 2: Auth guard'ı ekle (mevcut `router.beforeEach(onboardingGuard)` satırından ÖNCE)**

```ts
// Auth gate — non-public routes require a stored token.
// Runs before the onboarding guard so unauthenticated users never hit it.
router.beforeEach((to) => {
  if (to.meta.public) return
  const authStore = useAuthStore()
  if (!authStore.isAuthenticated) {
    return { path: '/login' }
  }
})
```

- [ ] **Step 3: Tip kontrolü + build**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check && npx vite build`
Expected: hata yok.

- [ ] **Step 4: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/router/index.ts
git commit -m "feat(auth): router auth guard"
```

---

## Task 10: Frontend — AppLayout kullanıcı adını token ile al

**Files:**
- Modify: `src/components/AppLayout.vue`

**Interfaces:**
- Consumes: `useAuthStore` (Task 7).

- [ ] **Step 1: Import ekle (script bloğundaki import'lara)**

```ts
import { useAuthStore } from '@/stores/auth'
```

- [ ] **Step 2: `onMounted` içindeki raw fetch'i değiştir**

Mevcut:

```ts
const userName = ref('')

onMounted(async () => {
  try {
    const res = await fetch('/api/method/frappe.auth.get_logged_user', {
      credentials: 'include',
    })
    const data = await res.json()
    if (data.message) {
      userName.value = data.message
    }
  } catch {
    // ignore — user info is cosmetic
  }
})
```

Şununla değiştir:

```ts
const authStore = useAuthStore()
const userName = ref('')

onMounted(async () => {
  await authStore.fetchCurrentUser()
  userName.value = authStore.user?.full_name ?? authStore.user?.name ?? ''
})
```

- [ ] **Step 3: Tip kontrolü + build**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run type-check && npx vite build`
Expected: hata yok.

- [ ] **Step 4: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add src/components/AppLayout.vue
git commit -m "feat(auth): resolve user name via token in AppLayout"
```

---

## Task 11: Frontend — dev proxy + prod env

**Files:**
- Modify: `src/../vite.config.ts` (repo kökündeki `vite.config.ts`)
- Create: `.env.production`

**Interfaces:** yok (yapılandırma).

- [ ] **Step 1: `vite.config.ts` proxy hedeflerini güncelle**

`server.proxy` içindeki dört bloğun (`/api`, `/logout`, `/files`, `/private`) `target` değerini `http://localhost:8090` → `https://pimcronbi.cronbi.com` yap ve her birine `secure: true` ekle. Örnek `/api` bloğu:

```ts
      '/api': {
        target: 'https://pimcronbi.cronbi.com',
        changeOrigin: true,
        secure: true,
      },
```

(`cookieDomainRewrite` satırları kaldırılabilir — token auth cookie kullanmıyor.)

- [ ] **Step 2: `.env.production` oluştur**

Repo kökünde (`/home/metin/Desktop/pim/Pim-Frontend/.env.production`):

```
VITE_API_BASE_URL=https://pimcronbi.cronbi.com
```

- [ ] **Step 3: Prod build'i doğrula**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npx vite build && grep -r "pimcronbi.cronbi.com" dist/assets | head -1`
Expected: build başarılı; base URL derlenmiş çıktıda bulunuyor (env gömüldü).

- [ ] **Step 4: Commit**

```bash
cd /home/metin/Desktop/pim/Pim-Frontend
git add vite.config.ts .env.production
git commit -m "feat(auth): point dev proxy and prod build to backend URL"
```

---

## Task 12: Manuel doğrulama + CORS (kod dışı)

**Files:** yok.

- [ ] **Step 1: Frappe Cloud CORS'u aç (kullanıcı)**

Frappe Cloud → Sites → pimcronbi.cronbi.com → Site Config → ekle:

```json
"allow_cors": "https://pim.atonota.net"
```

(Dev'de proxy kullanıldığı için localhost CORS gerekmez.)

- [ ] **Step 2: Backend'i deploy et**

PIM repo `feat/decoupled-token-auth` → main'e merge → Frappe Cloud otomatik deploy → migrate patch'i çalışır (signup açılır).

- [ ] **Step 3: Dev'de E2E**

Run: `cd /home/metin/Desktop/pim/Pim-Frontend && npm run dev`
Sonra tarayıcıda:
- `/login` → Kayıt Ol sekmesi → e-posta+ad ile kayıt → yeşil doğrulama mesajı görülür.
- Giriş sekmesi → geçerli kullanıcı ile giriş → dashboard'a yönlenir.
- Sayfayı yenile → token localStorage'da olduğu için oturum korunur.
- localStorage'dan token'ı sil, yenile → `/login`'e yönlenir.

- [ ] **Step 4: Prod'u doğrula**

Frontend `main`'e push → GitHub Pages deploy → `https://pim.atonota.net/login` üzerinde aynı E2E akışı (CORS açık olmalı).

---

## Self-Review Notları

- **Spec coverage:** login (Task 1), register (Task 2), me (Task 3), Allow Sign Up (Task 4), api config (Task 5), useFrappeAPI token (Task 6), auth store (Task 7), LoginPage tabs (Task 8), router guard (Task 9), AppLayout token (Task 10, spec'te belirtilen ek dokunuş), dev proxy + prod env (Task 11), CORS + manuel (Task 12). Tüm spec bileşenleri kapsandı.
- **Type consistency:** `AuthToken`, `login/register/logout/fetchCurrentUser/isAuthenticated` imzaları Task 5–10 arasında tutarlı; endpoint yolları `frappe_pim.pim.api.auth.*` her yerde aynı.
