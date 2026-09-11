#!/usr/bin/env python3
"""
O'Neal FTP Inventory to Shopify Sync V9
AUTOMATA + TELJES ÖNELLENŐRZÉS (listázza az ÖSSZES módosítást + skipped termékeket + SKIP OKOK)
+ DRAFT TERMÉKEK SKIP-ELÉSE

HELYES LOGIKA:
- Ha stock > 0  → inventory_policy = "continue" (LEHET backorder - eladható készlet nélkül)
- Ha stock = 0  → inventory_policy = "deny"     (NE lehessen backorder - nem eladható!)
- DRAFT termékek → NEM módosítódnak
"""

import os
import sys
import ftplib
import logging
from datetime import datetime
import requests

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Config from environment (GitHub Secrets)
ONEAL_FTP_HOST = os.getenv('ONEAL_FTP_HOST')
ONEAL_FTP_USER = os.getenv('ONEAL_FTP_USER')
ONEAL_FTP_PASSWORD = os.getenv('ONEAL_FTP_PASSWORD')
ONEAL_FTP_FILE = os.getenv('ONEAL_FTP_FILE', '/download/inventories_12019_ONeal_Europe.csv')

SHOPIFY_STORE = os.getenv('SHOPIFY_STORE')
SHOPIFY_CLIENT_ID = os.getenv('SHOPIFY_CLIENT_ID')
SHOPIFY_CLIENT_SECRET = os.getenv('SHOPIFY_CLIENT_SECRET')


class ShopifyAPI:
    """Shopify Admin API wrapper - OAuth2 Client Credentials"""
    
    def __init__(self, store, client_id, client_secret):
        self.store = store
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = "2024-10"
        self.base_url = f"https://{self.store}/admin/api/{self.api_version}"
        self.access_token = None
        self.products = []
        self.authenticate()
    
    def authenticate(self):
        """Get OAuth2 access token using client credentials"""
        url = f"https://{self.store}/admin/oauth/access_token"
        
        payload = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }
        
        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
            data = response.json()
            self.access_token = data.get('access_token')
            
            if self.access_token:
                logger.info("✅ Shopify OAuth2 authentication successful")
                return True
            else:
                logger.error(f"❌ No access token in response: {data}")
                return False
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Shopify authentication failed: {e}")
            return False
    
    def get_auth_header(self):
        """Get Authorization header"""
        if not self.access_token:
            return None
        
        return {
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json'
        }
    
    def get_products(self):
        """Get all products from Shopify (max 250) - filter by O'Neal CSV"""
        if not self.access_token:
            logger.error("❌ No access token available")
            return False
        
        headers = self.get_auth_header()
        
        try:
            # Hozz be max 250 terméket
            url = f"{self.base_url}/products.json?limit=250"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            self.products = response.json().get('products', [])
            logger.info(f"✅ Fetched {len(self.products)} products from Shopify")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to fetch products: {e}")
            return False
    
    def update_inventory_policy(self, product_id, variant_id, policy):
        """
        Update inventory policy
        policy = "deny"     (NE lehessen backorder - nem eladható)
        policy = "continue" (LEHET backorder - eladható készlet nélkül)
        """
        if not self.access_token:
            return False
        
        url = f"{self.base_url}/products/{product_id}/variants/{variant_id}.json"
        headers = self.get_auth_header()
        
        payload = {
            'variant': {
                'inventory_policy': policy
            }
        }
        
        try:
            response = requests.put(url, headers=headers, json=payload)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to update variant {variant_id}: {e}")
            return False


class ONealFTPSync:
    """O'Neal FTP inventory synchronizer"""
    
    def __init__(self, host, user, password, filename):
        self.host = host
        self.user = user
        self.password = password
        self.filename = filename
        self.inventory_data = {}
    
    def download_inventory(self):
        """Download inventory CSV from FTP - BINARY MODE"""
        try:
            ftp = ftplib.FTP(self.host)
            ftp.login(self.user, self.password)
            logger.info(f"✅ Connected to FTP: {self.host}")
            
            # BINÁRIS mód - teljes fájl letöltés egyszerre
            import io
            data_buffer = io.BytesIO()
            ftp.retrbinary(f'RETR {self.filename}', data_buffer.write)
            ftp.quit()
            
            # UTF-8 dekódolás
            csv_content = data_buffer.getvalue().decode('utf-8')
            logger.info(f"✅ Downloaded inventory file: {self.filename}")
            return csv_content
        
        except ftplib.all_errors as e:
            logger.error(f"❌ FTP error: {e}")
            return None
    
    def parse_inventory(self, csv_content):
        """Parse CSV and extract stock data - robust parsing"""
        try:
            lines = csv_content.split('\n')
            
            if not lines:
                logger.error("❌ CSV is empty")
                return False
            
            # Find header line (contains 'item_number')
            header_line = None
            header_idx = -1
            
            for i, line in enumerate(lines):
                if 'item_number' in line.lower():
                    header_line = line
                    header_idx = i
                    break
            
            if header_idx == -1:
                logger.error("❌ Could not find header with 'item_number'")
                return False
            
            logger.info(f"✅ Found header at line {header_idx}")
            
            # Parse data lines
            row_count = 0
            
            for i in range(header_idx + 1, len(lines)):
                line = lines[i].strip()
                
                if not line:
                    continue
                
                # Simple split by semicolon
                parts = line.split(';')
                
                if len(parts) >= 2:
                    item_number = parts[0].strip()
                    stock_str = parts[1].strip()
                    
                    if item_number:
                        try:
                            stock = int(stock_str)
                        except ValueError:
                            stock = 0
                        
                        self.inventory_data[item_number] = {
                            'stock': stock,
                            'has_stock': stock > 0
                        }
                        row_count += 1
            
            logger.info(f"✅ Parsed {row_count} items from inventory")
            
            # EXPORT az parsed inventory-t CSV-be debugginghoz
            try:
                import csv
                with open('/tmp/parsed_inventory.csv', 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(['item_number', 'stock', 'has_stock'])
                    for sku, data in sorted(self.inventory_data.items()):
                        writer.writerow([sku, data['stock'], data['has_stock']])
                logger.info(f"✅ Exported parsed inventory to: /tmp/parsed_inventory.csv")
            except Exception as e:
                logger.warning(f"⚠️ Could not export inventory CSV: {e}")
            
            # DEBUG: Kiírja az első 20 parsolt SKU-t
            logger.info(f"🔍 DEBUG - Első 20 parsolt SKU:")
            for i, (sku, data) in enumerate(list(self.inventory_data.items())[:20]):
                logger.info(f"   {i+1}. {sku} → stock={data.get('stock')}")
            
            # DEBUG: Keresés az 0625-516-ra
            if '0625-516' in self.inventory_data:
                logger.info(f"✅ 0625-516 MEGTALÁLVA: {self.inventory_data['0625-516']}")
            else:
                logger.warning(f"❌ 0625-516 NINCS az inventory_data-ban!")
                # Próbáljunk whitespace-el keresni
                for sku in list(self.inventory_data.keys()):
                    if '0625' in sku and '516' in sku:
                        logger.info(f"   💡 De MEGTALÁLTAM: '{sku}' → {self.inventory_data[sku]}")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to parse CSV: {e}")
            return False
    
    def get_stock_status(self, sku):
        """Get stock status for SKU"""
        return self.inventory_data.get(sku, {}).get('has_stock', False)


def main():
    """Main sync function"""
    logger.info("=" * 60)
    logger.info("🚀 O'Neal FTP to Shopify Inventory Sync V9 Started")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Validate config
    if not all([ONEAL_FTP_HOST, ONEAL_FTP_USER, ONEAL_FTP_PASSWORD, SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET]):
        logger.error("❌ Missing required environment variables")
        return False
    
    # Initialize
    oneal = ONealFTPSync(ONEAL_FTP_HOST, ONEAL_FTP_USER, ONEAL_FTP_PASSWORD, ONEAL_FTP_FILE)
    shopify = ShopifyAPI(SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET)
    
    # Check authentication
    if not shopify.access_token:
        logger.error("❌ Failed to authenticate with Shopify")
        return False
    
    # Download O'Neal inventory
    csv_content = oneal.download_inventory()
    if not csv_content:
        logger.error("❌ Failed to download O'Neal inventory")
        return False
    
    # Parse inventory
    if not oneal.parse_inventory(csv_content):
        logger.error("❌ Failed to parse inventory CSV")
        return False
    
    # Get Shopify products
    if not shopify.get_products():
        logger.error("❌ Failed to fetch Shopify products")
        return False
    
    # Sync inventory
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    
    # Listázáshoz
    available_skus = []      # stock > 0 → continue (eladható készlet nélkül)
    unavailable_skus = []    # stock = 0 → deny (nem eladható)
    skipped_items = []       # SKU nélküli variánsok + oka
    draft_items = []         # DRAFT termékek
    
    for product in shopify.products:
        product_title = product.get('title', 'Unknown')
        product_status = product.get('status', 'unknown')
        
        # SKIP OK: DRAFT TERMÉK
        if product_status == 'draft':
            for variant in product.get('variants', []):
                variant_title = variant.get('title', 'Unknown')
                draft_items.append({
                    'product': product_title,
                    'variant': variant_title,
                    'status': product_status
                })
                skipped_count += 1
            continue  # Skip az egész terméket
        
        # ACTIVE termékek feldolgozása
        for variant in product.get('variants', []):
            sku = variant.get('sku')
            variant_title = variant.get('title', 'Unknown')
            
            # SKIP OK: Nincs SKU
            if not sku or (isinstance(sku, str) and not sku.strip()):
                skipped_count += 1
                skip_reason = "Nincs SKU feltöltve a Shopify-ban"
                skipped_items.append({
                    'product': product_title,
                    'variant': variant_title,
                    'reason': skip_reason,
                    'variant_id': variant.get('id')
                })
                continue
            
            sku = str(sku).strip()
            
            if not sku:
                skipped_count += 1
                skip_reason = "SKU üres vagy nem olvasható"
                skipped_items.append({
                    'product': product_title,
                    'variant': variant_title,
                    'reason': skip_reason,
                    'variant_id': variant.get('id')
                })
                continue
            
            # Check O'Neal stock
            # ⚠️ FONTOS: Csak az O'Neal-ben megtalálható SKU-kat módosítunk!
            if sku not in oneal.inventory_data:
                skipped_count += 1
                skip_reason = f"SKU nincs az O'Neal készletben: {sku}"
                skipped_items.append({
                    'product': product_title,
                    'variant': variant_title,
                    'reason': skip_reason,
                    'variant_id': variant.get('id')
                })
                continue
            
            has_stock = oneal.get_stock_status(sku)
            actual_stock = oneal.inventory_data[sku]['stock']
            
            # DEBUG: Ha 0625-516, kiírja a detailokat
            if '0625-516' in sku:
                logger.info(f"🔍 DEBUG {sku}: actual_stock={actual_stock}, has_stock={has_stock}")
            
            # HELYES LOGIKA:
            # stock > 0 → "continue" (LEHET backorder - eladható készlet nélkül)
            # stock = 0 → "deny"     (NE lehessen backorder - nem eladható)
            policy = "continue" if has_stock else "deny"
            
            # DEBUG: Ha 0625-516, kiírja a policy-t
            if '0625-516' in sku:
                logger.info(f"🔍 DEBUG {sku}: policy={policy}")
            
            # Update Shopify
            if shopify.update_inventory_policy(product['id'], variant['id'], policy):
                updated_count += 1
                if has_stock:
                    available_skus.append(sku)
                    logger.info(f"  ✅ {sku}: Eladható készlet nélkül (continue)")
                else:
                    unavailable_skus.append(sku)
                    logger.info(f"  ❌ {sku}: NEM eladható (deny)")
            else:
                failed_count += 1
    
    # ========== TELJES ÖNELLENŐRZÉS ==========
    logger.info("=" * 60)
    logger.info("📋 TELJES ÖNELLENŐRZÉS - MÓDOSÍTOTT + SKIPPED:")
    logger.info("=" * 60)
    
    if available_skus:
        logger.info(f"\n✅ RENDELHETŐ - Készlet van ({len(available_skus)} db):")
        for sku in sorted(available_skus)[:50]:
            logger.info(f"   - {sku}")
        if len(available_skus) > 50:
            logger.info(f"   ... és további {len(available_skus) - 50} termék")
    
    if unavailable_skus:
        logger.info(f"\n❌ NEM RENDELHETŐ - Nincs készlet ({len(unavailable_skus)} db):")
        for sku in sorted(unavailable_skus)[:50]:
            logger.info(f"   - {sku}")
        if len(unavailable_skus) > 50:
            logger.info(f"   ... és további {len(unavailable_skus) - 50} termék")
    
    if draft_items:
        logger.info(f"\n🔴 DRAFT - NEM MÓDOSÍTOTT (INAKTÍV TERMÉKEK) ({len(draft_items)} db):")
        logger.info("   (Draft termékek kizárva az automatikus szinkronizációból)")
        for item in draft_items[:20]:
            product = item.get('product', 'Unknown')
            variant = item.get('variant', 'Unknown')
            logger.info(f"   - {product} / {variant}")
        if len(draft_items) > 20:
            logger.info(f"   ... és további {len(draft_items) - 20} termék")
    
    if skipped_items:
        logger.info(f"\n⚠️  SKIPPED - MIÉRT NEM MÓDOSÍTOTT ({len(skipped_items)} db):")
        logger.info("   " + "=" * 55)
        
        # Csoportosítás oka szerint
        reasons_dict = {}
        for item in skipped_items:
            reason = item.get('reason', 'Ismeretlen ok')
            if reason not in reasons_dict:
                reasons_dict[reason] = []
            reasons_dict[reason].append(item)
        
        for reason, items in reasons_dict.items():
            logger.info(f"\n   ⚠️  OK: {reason}")
            logger.info(f"      Érintett termékek ({len(items)} db):")
            for item in items[:15]:
                product = item.get('product', 'Unknown')
                variant = item.get('variant', 'Unknown')
                logger.info(f"      - {product} / {variant}")
            if len(items) > 15:
                logger.info(f"      ... és további {len(items) - 15} termék")
    
    logger.info("\n" + "=" * 60)
    logger.info(f"✅ Sync complete!")
    logger.info(f"   Updated: {updated_count} variants (ACTIVE)")
    logger.info(f"   Failed: {failed_count} variants")
    logger.info(f"   Skipped (no SKU): {len(skipped_items)} variants")
    logger.info(f"   Draft (inaktív): {len(draft_items)} variants")
    logger.info("=" * 60)
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
