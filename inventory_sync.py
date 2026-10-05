#!/usr/bin/env python3
"""
O'Neal FTP -> Shopify készlet szinkron  V10

Mit csinál:
- Letölti az O'Neal készletfájlt FTP-ről (item_number;stock;EAN;next_delivery;active)
- Végigmegy a Shopify ÖSSZES aktív O'Neal termékén (lapozással, GraphQL API)
- Változatonként párosít: először SKU alapján, ha az nem talál, akkor EAN (vonalkód) alapján
- Beállítja az "Értékesítés készlethiány esetén" opciót:
    O'Neal készlet > 0           -> CONTINUE (rendelhető)
    O'Neal készlet = 0           -> DENY     (nem rendelhető, ha nincs saját készlet)
    nincs az O'Neal listában     -> DENY     (kifutott méret; kikapcsolható: DENY_MISSING=false)
- CSAK akkor ír a Shopify-ba, ha az érték tényleg változik (gyors, nem fut bele a limitekbe)
- Vázlat (draft) és archivált termékekhez nem nyúl
- A saját raktárkészletet nem módosítja (csak az inventory policy-t)

V9-hez képest javítva:
- ">10" készletérték eddig 0-nak számított -> minden ilyen változat "nem rendelhető" lett. JAVÍTVA.
- Eddig csak az első 250 terméket nézte (nem volt lapozás). JAVÍTVA: minden termék.
- Eddig minden futáskor minden változatot újraírt. JAVÍTVA: csak a változást írja.
- EAN alapú tartalék párosítás.
- Csak O'Neal szállítójú termékeket kezel (más márka SKU-ja nem keveredhet bele).
- REST helyett GraphQL Admin API (a REST termék API kivezetés alatt áll).
- DRY_RUN=true módban csak kiírja, mit csinálna, nem módosít semmit.
- Összesítő a GitHub Actions "Summary" oldalán.
"""

import csv
import ftplib
import io
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# ---- Beállítások (GitHub Secrets / env) ----
ONEAL_FTP_HOST = os.getenv('ONEAL_FTP_HOST')
ONEAL_FTP_USER = os.getenv('ONEAL_FTP_USER')
ONEAL_FTP_PASSWORD = os.getenv('ONEAL_FTP_PASSWORD')
ONEAL_FTP_FILE = os.getenv('ONEAL_FTP_FILE') or '/download/inventories_12019_ONeal_Europe.csv'

SHOPIFY_STORE = os.getenv('SHOPIFY_STORE')
SHOPIFY_CLIENT_ID = os.getenv('SHOPIFY_CLIENT_ID')
SHOPIFY_CLIENT_SECRET = os.getenv('SHOPIFY_CLIENT_SECRET')

API_VERSION = os.getenv('SHOPIFY_API_VERSION') or '2026-01'
VENDOR = os.getenv('VENDOR') or 'Oneal'                    # Shopify "Szállító" mező értéke
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'  # true = csak kiírja, nem módosít
DENY_MISSING = os.getenv('DENY_MISSING', 'true').lower() == 'true'


# ---------------------------------------------------------------- O'Neal FTP
def parse_stock(value):
    """'>10' -> 11, '6' -> 6, '' / hibás -> 0"""
    v = (value or '').strip()
    if not v:
        return 0
    m = re.search(r'\d+', v)
    if not m:
        return 0
    n = int(m.group())
    return n + 1 if v.startswith('>') else n


def download_oneal():
    ftp = ftplib.FTP(ONEAL_FTP_HOST, timeout=60)
    ftp.login(ONEAL_FTP_USER, ONEAL_FTP_PASSWORD)
    buf = io.BytesIO()
    ftp.retrbinary(f'RETR {ONEAL_FTP_FILE}', buf.write)
    ftp.quit()
    raw = buf.getvalue()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    log.info(f"✅ O'Neal fájl letöltve ({len(raw)//1024} KB)")
    return text


def parse_oneal(text):
    """Visszaad: by_sku {sku: {...}}, by_ean {ean: {...}}"""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if 'item_number' in l.lower()), None)
    if start is None:
        raise RuntimeError("Nem található 'item_number' fejléc az O'Neal fájlban")
    reader = csv.DictReader(lines[start:], delimiter=';')
    reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
    by_sku, by_ean = {}, {}
    for row in reader:
        sku = (row.get('item_number') or '').strip()
        if not sku:
            continue
        rec = {
            'sku': sku,
            'stock': parse_stock(row.get('stock')),
            'raw_stock': (row.get('stock') or '').strip(),
            'ean': (row.get('ean') or '').strip(),
            'next_delivery': (row.get('next_delivery') or '').strip(),
        }
        by_sku[sku] = rec
        if rec['ean']:
            by_ean[rec['ean']] = rec
    log.info(f"✅ O'Neal tételek: {len(by_sku)} (EAN-nal: {len(by_ean)})")
    return by_sku, by_ean


# ---------------------------------------------------------------- Shopify
class Shopify:
    def __init__(self):
        self.url = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"
        r = requests.post(f"https://{SHOPIFY_STORE}/admin/oauth/access_token", data={
            'client_id': SHOPIFY_CLIENT_ID,
            'client_secret': SHOPIFY_CLIENT_SECRET,
            'grant_type': 'client_credentials',
        }, timeout=30)
        r.raise_for_status()
        self.token = r.json()['access_token']
        log.info("✅ Shopify bejelentkezés rendben")

    def gql(self, query, variables=None, retries=6):
        for attempt in range(retries):
            r = requests.post(self.url, json={'query': query, 'variables': variables or {}},
                              headers={'X-Shopify-Access-Token': self.token,
                                       'Content-Type': 'application/json'}, timeout=60)
            if r.status_code in (429, 502, 503):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            errs = data.get('errors')
            if errs and any(e.get('extensions', {}).get('code') == 'THROTTLED' for e in errs):
                time.sleep(2 ** attempt)
                continue
            if errs:
                raise RuntimeError(f"GraphQL hiba: {errs}")
            # kíméljük a limitet
            cost = data.get('extensions', {}).get('cost', {}).get('throttleStatus', {})
            if cost and cost.get('currentlyAvailable', 1000) < 200:
                time.sleep(2)
            return data['data']
        raise RuntimeError("Shopify API: túl sok újrapróbálkozás")

    def oneal_products(self):
        q = """
        query($cursor: String, $q: String!) {
          products(first: 50, after: $cursor, query: $q) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id title status vendor
              variants(first: 100) {
                nodes { id title sku barcode inventoryPolicy }
              }
            }
          }
        }"""
        cursor, out = None, []
        while True:
            d = self.gql(q, {'cursor': cursor, 'q': f"vendor:'{VENDOR}' status:active"})
            page = d['products']
            out.extend(p for p in page['nodes'] if p['vendor'] == VENDOR and p['status'] == 'ACTIVE')
            if not page['pageInfo']['hasNextPage']:
                break
            cursor = page['pageInfo']['endCursor']
        log.info(f"✅ Aktív {VENDOR} termékek a Shopify-ban: {len(out)}")
        return out

    def set_policies(self, product_id, changes):
        m = """
        mutation($pid: ID!, $v: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $pid, variants: $v) {
            userErrors { field message }
          }
        }"""
        d = self.gql(m, {'pid': product_id,
                         'v': [{'id': vid, 'inventoryPolicy': pol} for vid, pol in changes]})
        errs = d['productVariantsBulkUpdate']['userErrors']
        if errs:
            raise RuntimeError(str(errs))


# ---------------------------------------------------------------- main
def main():
    log.info("=" * 60)
    log.info(f"🚀 O'Neal készlet szinkron V10  {datetime.now():%Y-%m-%d %H:%M}"
             f"{'   [DRY RUN – nem módosít]' if DRY_RUN else ''}")
    log.info("=" * 60)

    missing = [k for k, v in {
        'ONEAL_FTP_HOST': ONEAL_FTP_HOST, 'ONEAL_FTP_USER': ONEAL_FTP_USER,
        'ONEAL_FTP_PASSWORD': ONEAL_FTP_PASSWORD, 'SHOPIFY_STORE': SHOPIFY_STORE,
        'SHOPIFY_CLIENT_ID': SHOPIFY_CLIENT_ID, 'SHOPIFY_CLIENT_SECRET': SHOPIFY_CLIENT_SECRET}.items() if not v]
    if missing:
        log.error(f"❌ Hiányzó beállítás: {', '.join(missing)}")
        return False

    by_sku, by_ean = parse_oneal(download_oneal())
    if len(by_sku) < 500:
        # biztonsági fék: hibás/üres fájl esetén ne állítson át mindent "nem rendelhető"-re
        log.error(f"❌ Gyanúsan kevés O'Neal tétel ({len(by_sku)}), a szinkron leáll.")
        return False

    shop = Shopify()
    products = shop.oneal_products()

    stats = {'match_sku': 0, 'match_ean': 0, 'not_found': 0, 'no_id': 0,
             'to_continue': 0, 'to_deny': 0, 'unchanged': 0, 'failed': 0}
    changed_log, not_found_log, no_id_log = [], [], []

    for p in products:
        changes = []
        for v in p['variants']['nodes']:
            sku = (v['sku'] or '').strip()
            bars = [b.strip() for b in re.split(r'[;,\s]+', v['barcode'] or '') if b.strip()]
            rec = by_sku.get(sku) if sku else None
            if rec:
                stats['match_sku'] += 1
            else:
                rec = next((by_ean[b] for b in bars if b in by_ean), None)
                if rec:
                    stats['match_ean'] += 1
            name = f"{p['title']} / {v['title']}"

            if not rec:
                if not sku and not bars:
                    stats['no_id'] += 1
                    no_id_log.append(name)
                    continue
                stats['not_found'] += 1
                not_found_log.append(f"{name} ({sku or bars[0]})")
                if not DENY_MISSING:
                    continue
                target = 'DENY'
            else:
                target = 'CONTINUE' if rec['stock'] > 0 else 'DENY'

            if v['inventoryPolicy'] == target:
                stats['unchanged'] += 1
                continue
            changes.append((v['id'], target))
            stats['to_continue' if target == 'CONTINUE' else 'to_deny'] += 1
            extra = f" (O'Neal: {rec['raw_stock']}, érkezik: {rec['next_delivery']})" if rec else " (nincs az O'Neal listában)"
            changed_log.append(f"{'✅ rendelhető' if target == 'CONTINUE' else '⛔ nem rendelhető'}: {name}{extra}")

        if changes and not DRY_RUN:
            try:
                shop.set_policies(p['id'], changes)
            except Exception as e:
                stats['failed'] += len(changes)
                log.error(f"❌ Nem sikerült: {p['title']}: {e}")

    # ---- Riport ----
    log.info("=" * 60)
    log.info("📋 VÁLTOZÁSOK:")
    for line in changed_log:
        log.info("  " + line)
    if not changed_log:
        log.info("  Nincs változás az előző futáshoz képest.")
    if not_found_log:
        log.info(f"\n⚠️  Nincs az O'Neal listában ({len(not_found_log)} db)"
                 f"{' → nem rendelhetőre állítva' if DENY_MISSING else ' → kihagyva'}:")
        for line in not_found_log[:100]:
            log.info("  - " + line)
    if no_id_log:
        log.info(f"\n⚠️  Nincs SKU és vonalkód sem ({len(no_id_log)} db) → kihagyva:")
        for line in no_id_log[:100]:
            log.info("  - " + line)

    summary = (f"Párosítva SKU-val: {stats['match_sku']}, EAN-nal: {stats['match_ean']} | "
               f"Nem található: {stats['not_found']} | Azonosító nélkül: {stats['no_id']} | "
               f"Módosítva → rendelhető: {stats['to_continue']}, → nem rendelhető: {stats['to_deny']} | "
               f"Változatlan: {stats['unchanged']} | Hiba: {stats['failed']}")
    log.info("\n" + "=" * 60)
    log.info(("[DRY RUN] " if DRY_RUN else "✅ ") + summary)
    log.info("=" * 60)

    gh_summary = os.getenv('GITHUB_STEP_SUMMARY')
    if gh_summary:
        with open(gh_summary, 'a', encoding='utf-8') as f:
            f.write(f"## O'Neal készlet szinkron {'(DRY RUN)' if DRY_RUN else ''}\n\n")
            f.write("| | db |\n|---|---|\n")
            for k, label in [('match_sku', 'Párosítva SKU-val'), ('match_ean', 'Párosítva EAN-nal'),
                             ('to_continue', 'Módosítva → rendelhető'), ('to_deny', 'Módosítva → nem rendelhető'),
                             ('unchanged', 'Változatlan'), ('not_found', "Nincs az O'Neal listában"),
                             ('no_id', 'Nincs SKU és vonalkód'), ('failed', 'Hiba')]:
                f.write(f"| {label} | {stats[k]} |\n")
            if changed_log:
                f.write("\n### Változások\n" + "\n".join(f"- {l}" for l in changed_log[:300]) + "\n")

    return stats['failed'] == 0


if __name__ == '__main__':
    try:
        ok = main()
    except Exception as e:
        log.exception(f"❌ Váratlan hiba: {e}")
        ok = False
    sys.exit(0 if ok else 1)
