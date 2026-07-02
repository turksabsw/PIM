# Decoupled Frontend + Token Auth — Tasarım Dokümanı

**Tarih:** 2026-07-02
**Durum:** Onaylandı (brainstorming)

## Amaç

Ayrı deploy edilen Vue SPA frontend'i (`https://pim.atonota.net`, GitHub Pages) ile
Frappe Cloud backend'i (`https://pimcronbi.cronbi.com`) arasında çalışan bir API
iletişimi ve login/register akışı kurmak. Frontend ve backend farklı ana
domain'lerde olduğu için (cross-origin), auth cookie yerine **token tabanlı**
yapılacak.

## Onaylanan Kararlar

| Konu | Karar |
|------|-------|
| Frontend deploy | `pim.atonota.net` (GitHub Pages) — mevcut akış aynen kalır |
| Backend API base URL | `https://pimcronbi.cronbi.com` |
| Auth yöntemi | Token tabanlı: `Authorization: token api_key:api_secret` |
| Register | Herkese açık self-signup (Frappe `sign_up` + e-posta doğrulama) |
| "Allow Sign Up" | Backend patch/fixture ile açılır (+ manuel panel adımı dokümante edilir) |
| CORS | Kullanıcı Frappe Cloud site config'inden açar (`allow_cors`) |

## Mimari Genel Bakış

```
[ Vue SPA @ pim.atonota.net ]  --HTTPS + Authorization: token-->  [ Frappe @ pimcronbi.cronbi.com ]
         localStorage: token (api_key:api_secret)                  /api/method/frappe_pim.pim.api.auth.*
                                                                    /api/resource/* , /api/method/*
```

- Cookie yok → cross-site cookie engellemesi (Safari/Chrome) sorunu ortadan kalkar.
- Frappe, `Authorization: token api_key:api_secret` header'ını native olarak destekler;
  tüm `/api/resource` ve `/api/method` çağrıları bu header ile kimliklenir.

## Bileşen 1 — Backend: `frappe_pim/pim/api/auth.py` (yeni)

Guest'e açık whitelisted metotlar (`@frappe.whitelist(allow_guest=True)`):

### `login(usr, pwd)`
1. `usr` çözümlenir (email veya username → User id).
2. `frappe.utils.password.check_password(user, pwd)` ile doğrulanır
   (başarısızsa `frappe.AuthenticationError`).
3. Kullanıcı `disabled` ise reddedilir.
4. `User.api_key` yoksa üretilir (`frappe.generate_hash`).
5. `api_secret`:
   - Varsa `frappe.utils.password.get_decrypted_password("User", user, "api_secret")`
     ile çözülüp döndürülür (token stabil kalır, önceki cihazlar geçersiz olmaz).
   - Yoksa üretilip kaydedilir.
6. Döner: `{ "api_key", "api_secret", "user", "full_name" }`.

**Güvenlik:** Brute-force'a karşı Frappe'nin `frappe.auth` rate-limit'i devrede;
gerekirse `frappe.rate_limiter` ile ek sınır. Başarısız denemede jenerik hata mesajı.

### `register(email, full_name)`
- Frappe'nin `frappe.core.doctype.user.user.sign_up(email, full_name, redirect_to="")`
  fonksiyonunu çağırır → Website User oluşturur, doğrulama e-postası gönderir.
- "Allow Sign Up" kapalıysa Frappe hata döndürür; bu durumu yakalayıp anlamlı mesaj veririz.
- Döner: `{ "status": "ok", "message": "..." }` (frontend "e-postanı doğrula" gösterir).

### `me()`
- `Authorization: token` header'ından çözülen `frappe.session.user` bilgisini döndürür.
- Guest ise `{ "authenticated": false }`; değilse kullanıcı bilgisi.
- Frontend token geçerliliğini uygulama açılışında bununla doğrular.

### logout
- Backend endpoint gerekmez; client localStorage'daki token'ı siler.
- (Opsiyonel, kapsam dışı: `api_secret` rotate endpoint'i ileride eklenebilir.)

## Bileşen 2 — Backend: "Allow Sign Up" ayarı

- Yeni patch (`frappe_pim/patches/v1_0/enable_website_signup.py`) veya fixture ile
  `Website Settings.disable_signup = 0` (yani signup açık) set edilir.
- Manuel alternatif (dokümante edilir): Frappe Desk → Website Settings →
  "Disable Signup" kapalı olacak.

## Bileşen 3 — Backend: CORS (kullanıcı tarafı)

Kod ile yapılamaz; kullanıcıya verilecek talimat:
- Frappe Cloud → Site Config'e ekle:
  ```json
  "allow_cors": "https://pim.atonota.net"
  ```
  (dev için gerekmiyor; dev proxy üzerinden gider.)
- Token auth cookie kullanmadığı için `Access-Control-Allow-Credentials` gerekmez;
  yalnızca origin + `Authorization` header'ının preflight'ta kabulü yeterli
  (`allow_cors` bunu sağlar).

## Bileşen 4 — Frontend: `src/config/api.ts` (yeni)

```ts
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
```
- Prod build: `VITE_API_BASE_URL=https://pimcronbi.cronbi.com`
- Dev: tanımsız/boş → `''` → Vite proxy devreye girer (CORS'suz).

## Bileşen 5 — Frontend: `useFrappeAPI.ts` değişiklikleri

- `baseURL` → `API_BASE_URL`.
- CSRF token okuma/gönderme mantığı kaldırılır (token auth'ta gereksiz).
- `withCredentials: false`.
- Request interceptor: auth store'dan token okur, varsa
  `Authorization: token ${api_key}:${api_secret}` ekler.
- Response interceptor: 401/403'te token temizlenir ve `/login`'e yönlendirilir.

## Bileşen 6 — Frontend: `src/stores/auth.ts` (yeni, Pinia)

- **state:** `token: { api_key, api_secret } | null` (localStorage'da persist),
  `user: { name, full_name } | null`.
- **getters:** `isAuthenticated` (token var mı).
- **actions:**
  - `login(usr, pwd)` → `auth.login` çağırır, token'ı saklar, `user`'ı doldurur.
  - `register(email, full_name)` → `auth.register` çağırır, sonucu döndürür.
  - `logout()` → token/user temizler, `/login`'e yönlendirir.
  - `fetchCurrentUser()` → `auth.me` ile token'ı doğrular; geçersizse logout.

## Bileşen 7 — Frontend: `LoginPage.vue` (yeniden yazım)

- İki sekme: **Login** ve **Register** (mevcut tek-form yerine).
- Login sekmesi: email/username + password → `authStore.login`.
- Register sekmesi: email + full name → `authStore.register` → başarıda
  "E-postana gönderilen bağlantıyla hesabını doğrula" mesajı.
- Hata ve loading state'leri; mevcut Tailwind stil dili korunur.

## Bileşen 8 — Frontend: Router auth guard

- `src/router/index.ts`'e global `beforeEach` guard:
  - `to.meta.public` değilse ve `authStore.isAuthenticated` false ise → `/login`.
  - Onboarding guard'dan **önce** çalışır.
- `/login` route'u zaten `meta.public: true`.

## Bileşen 9 — Frontend: dev proxy

- `vite.config.ts` proxy hedefleri `http://localhost:8090` → `https://pimcronbi.cronbi.com`
  (`changeOrigin: true`). Böylece dev'de tarayıcı için same-origin, CORS gerekmez.

## Deploy Akışı (değişmez)

- Frontend: mevcut GitHub Pages workflow'u aynen. Tek fark: prod build'de
  `VITE_API_BASE_URL` environment değişkeni GitHub Actions'ta set edilir.
- Backend: PIM repo'suna push → Frappe Cloud otomatik deploy (yeni `auth.py` + patch).

## Kapsam Dışı (YAGNI)

- Şifre sıfırlama akışı
- Sosyal login / OAuth
- Refresh-token rotasyonu
- Backend-hosted SPA
- Cross-repo derlenmiş asset commit'i

## Test Stratejisi

- Backend: `auth.py` için Frappe test (login başarılı/başarısız, disabled user,
  register açık/kapalı, me() guest/authenticated).
- Frontend: auth store login/logout birim testi; guard yönlendirme testi.
- Manuel E2E: dev proxy ile login → dashboard, register → doğrulama mesajı,
  geçersiz token → login'e yönlendirme.
