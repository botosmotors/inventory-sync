# O'Neal FTP to Shopify Inventory Sync

Automatikus készlet szinkronizáció az O'Neal FTP-ről a Shopify boltra.

## 🎯 Mit csinál?

1. **FTP letöltés**: Minden 6 órában letölti az O'Neal inventory CSV-t
2. **Stock ellenőrzés**: Megnézi, hogy melyik termékeknek van készlet
3. **Shopify frissítés**: 
   - Ha `stock > 0` → "Eladható készlet nélkül" = ❌ (inventory_policy: "deny")
   - Ha `stock = 0` → "Eladható készlet nélkül" = ✅ (inventory_policy: "continue")

## 🚀 Setup

### 1. GitHub Secrets beállítása

A repo Settings → Secrets and variables → Actions menüben add meg ezeket:

```
ONEAL_FTP_HOST          = oneal-b2b.com
ONEAL_FTP_USER          = user_12019
ONEAL_FTP_PASSWORD      = bff565af
ONEAL_FTP_FILE          = /download/inventories_12019_ONeal_Europe.csv
SHOPIFY_STORE           = botos-motors.myshopify.com
SHOPIFY_CLIENT_ID       = 94b9fa399bd25ea87f1dd9c209396097
SHOPIFY_CLIENT_SECRET   = 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
```

### 2. GitHub Actions aktiválása

1. **Actions** tab megnyitása
2. **I understand my workflows...** gomb kattintása (ha szükséges)
3. Az `Inventory Sync` workflow automatikusan futni fog 6 óránként

### 3. Teszt futtatás

```bash
# Manuális futtatás a GitHub UI-ből:
Actions → Inventory Sync → Run workflow
```

## 📋 Fájlok

- **inventory_sync.py** - Fő Python script
- **.github/workflows/sync.yml** - GitHub Actions workflow (automata futtatás)
- **requirements.txt** - Python dependencies
- **README.md** - Ez a fájl

## 🔧 Új márka hozzáadása

Később könnyű lesz további márkákat hozzáadni. Pl. Dunlop:

1. Új `dunlop.py` osztály az O'Neal helyett
2. FTP vagy API logika Dunlop-nak
3. GitHub Secrets frissítése
4. Kész!

## 📊 Futás ütemezése

```
00:00 UTC → Automata szinkron
06:00 UTC → Automata szinkron
12:00 UTC → Automata szinkron
18:00 UTC → Automata szinkron
```

(Ha módosítani akarod, szerkeszd a `.github/workflows/sync.yml` fájlban a `cron` sort)

## 🐛 Debugging

1. **Actions tab** → Az utolsó workflow run
2. **Logs** megtekintése
3. Ha hiba van, a log megmutatja, hogy mi történt

## 💡 Támogatás

Ha valami nem működik:
1. Ellenőrizd a GitHub Secrets-et
2. Nézd meg az Actions logs-ot
3. Próbálj manuálisan futtatni a "Run workflow" gombbal

---

**Készült:** 2026. szeptember 11.  
**Verzió:** 1.0
