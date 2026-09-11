# 🚀 Setup Útmutató - Lépésről Lépésre

## 1. FÁJLOK FELTÖLTÉSE A GITHUB REPO-BA

### Option A: GitHub Web UI-ből (EGYSZERŰ)

1. Menj: https://github.com/botosmotors/inventory-sync
2. **Add file** → **Create new file**
3. Minden fájlt újra megadsz:
   - `inventory_sync.py`
   - `.github/workflows/sync.yml`
   - `requirements.txt`
   - `.gitignore`
   - `README.md`

### Option B: Git Command-line-ből (GYORSABB)

```bash
cd ~/inventory-sync
git clone https://github.com/botosmotors/inventory-sync.git
cd inventory-sync

# Fájlok másolása ide
# (Akkor Copy/Paste az inventory_sync.py stb. tartalmát)

git add .
git commit -m "Initial commit: O'Neal FTP sync setup"
git push origin main
```

---

## 2. GITHUB SECRETS BEÁLLÍTÁSA ⚙️

### A. Secrets hozzáadása

1. GitHub repo → **Settings** (jobb felső)
2. Bal oldalt: **Secrets and variables** → **Actions**
3. **New repository secret** gomb

### B. Secrets hozzáadása egyenként:

```
Név: ONEAL_FTP_HOST
Érték: oneal-b2b.com
```

```
Név: ONEAL_FTP_USER
Érték: user_12019
```

```
Név: ONEAL_FTP_PASSWORD
Érték: bff565af
```

```
Név: ONEAL_FTP_FILE
Érték: /download/inventories_12019_ONeal_Europe.csv
```

```
Név: SHOPIFY_STORE
Érték: botos-motors.myshopify.com
```

```
Név: SHOPIFY_CLIENT_ID
Érték: 94b9fa399bd25ea87f1dd9c209396097
```

```
Név: SHOPIFY_CLIENT_SECRET
Érték: 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
```

---

## 3. GITHUB ACTIONS AKTIVÁLÁSA ✅

1. GitHub repo → **Actions** tab
2. Bal oldalt: **Inventory Sync** workflow
3. **Enable workflow** (ha letiltva van)
4. Kész! Mostmár automatikusan fut!

---

## 4. TESZT FUTTATÁS 🧪

1. **Actions** tab
2. **Inventory Sync** workflow
3. **Run workflow** gomb
4. **Run workflow** ismét
5. Nézd az **Output** log-ot:

```
✅ Connected to FTP: oneal-b2b.com
✅ Downloaded inventory file: ...
✅ Shopify OAuth authentication successful
✅ Sync complete! Updated XXX variants
```

---

## 5. AUTOMATA FUTTATÁS 🤖

Mostmár a workflow AUTOMATIKUSAN fut:
- **Napi 4-szer** (00:00, 06:00, 12:00, 18:00 UTC)
- **Te:** 0 manuális munka!

---

## 🔍 DEBUGGING

### Hiba: "FTP connection failed"
- Ellenőrizd: ONEAL_FTP_HOST, USER, PASSWORD secrets-ben
- Nézd meg az Actions → Workflow run → Logs

### Hiba: "Shopify authentication failed"
- Ellenőrizd: SHOPIFY_CLIENT_ID, CLIENT_SECRET
- Client Secret ne legyen copy-paste hiba!

### Hiba: "No matching workflow"
- Biztos-e, hogy `.github/workflows/sync.yml` fájl létezik?
- Repo-ban lévő `.github/workflows/` mappá tartalmazza?

---

## 📝 NOTES

- **GitHub Actions** = GitHub-on futnak a scriptek (nem kell hozzá saját server)
- **Secrets** = Biztonságos tárolás (nem látszik a repo-ban)
- **6 óránkénti futás** = Egy nap 4x szinkronizálás
- **Email notification** = Hiba esetén GitHub e-mailt küld

---

## ✅ TELJES SETUP CHECKLIST

- [ ] Fájlok feltöltve a repo-ba
- [ ] Összes 7 Secret beállítva
- [ ] GitHub Actions enabled
- [ ] Teszt futtatás sikeres
- [ ] Logs zöld checkmark-kal
- [ ] Készen állsz! 🚀

---

**Ready?** Jelezz ha kérdés van vagy összekeveredtél valamivel! 💪
