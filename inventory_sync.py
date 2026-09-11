#!/usr/bin/env python3
"""
O'Neal FTP Inventory to Shopify Sync
Automatikusan letölti az O'Neal inventory CSV-t az FTP-ről,
és frissíti a Shopify termékinventoryt.

Logic:
- Ha stock > 0  → inventory_policy = "deny"   (NE lehessen backorder)
- Ha stock = 0  → inventory_policy = "continue" (LEHET backorder)
"""

import os
import sys
import ftplib
import csv
import logging
from io import StringIO
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
        """Get all products from Shopify"""
        if not self.access_token:
            logger.error("❌ No access token available")
            return False
        
        url = f"{self.base_url}/products.json"
        headers = self.get_auth_header()
        
        try:
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
        policy = "deny"     (NE eladható készlet nélkül - stock > 0)
        policy = "continue" (ELADHATÓ készlet nélkül - stock = 0)
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
        """Download inventory CSV from FTP"""
        try:
            ftp = ftplib.FTP(self.host)
            ftp.login(self.user, self.password)
            logger.info(f"✅ Connected to FTP: {self.host}")
            
            csv_data = StringIO()
            ftp.retrlines(f'RETR {self.filename}', csv_data.write)
            ftp.quit()
            
            logger.info(f"✅ Downloaded inventory file: {self.filename}")
            return csv_data.getvalue()
        
        except ftplib.all_errors as e:
            logger.error(f"❌ FTP error: {e}")
            return None
    
    def detect_delimiter(self, csv_content):
        """Detect CSV delimiter (;, tab, comma, space)"""
        first_line = csv_content.split('\n')[0] if csv_content else ""
        
        delimiters = [';', '\t', ',', ' ']
        delimiter = ';'  # default
        
        for delim in delimiters:
            if delim in first_line:
                delimiter = delim
                logger.info(f"✅ Detected CSV delimiter: '{repr(delimiter)}'")
                break
        
        return delimiter
    
    def parse_inventory(self, csv_content):
        """Parse CSV and extract stock data"""
        try:
            # Auto-detect delimiter
            delimiter = self.detect_delimiter(csv_content)
            
            reader = csv.DictReader(StringIO(csv_content), delimiter=delimiter)
            
            if reader.fieldnames is None:
                logger.error("❌ CSV is empty or invalid")
                return False
            
            logger.info(f"CSV fields: {reader.fieldnames}")
            
            row_count = 0
            for row in reader:
                item_number = row.get('item_number', '').strip()
                stock_str = row.get('stock', '0').strip()
                
                try:
                    stock = int(stock_str)
                except ValueError:
                    stock = 0
                
                if item_number:
                    self.inventory_data[item_number] = {
                        'stock': stock,
                        'has_stock': stock > 0
                    }
                    row_count += 1
            
            logger.info(f"✅ Parsed {row_count} items from inventory")
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to parse CSV: {e}")
            return False
    
    def get_stock_status(self, sku):
        """Get stock status for SKU - returns has_stock boolean"""
        return self.inventory_data.get(sku, {}).get('has_stock', False)


def main():
    """Main sync function"""
    logger.info("=" * 60)
    logger.info("🚀 O'Neal FTP to Shopify Inventory Sync Started")
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
    
    for product in shopify.products:
        for variant in product.get('variants', []):
            sku = variant.get('sku')
            
            # Handle None or empty SKU
            if not sku:
                skipped_count += 1
                continue
            
            sku = str(sku).strip()
            
            if not sku:
                skipped_count += 1
                continue
            
            # Check O'Neal stock
            has_stock = oneal.get_stock_status(sku)
            
            # Determine policy:
            # - has_stock (stock > 0)  → "deny"     (NE eladható készlet nélkül)
            # - NO stock (stock = 0)   → "continue" (ELADHATÓ készlet nélkül)
            policy = "deny" if has_stock else "continue"
            
            # Update Shopify
            if shopify.update_inventory_policy(product['id'], variant['id'], policy):
                updated_count += 1
                status = "📦 In stock (deny)" if has_stock else "📭 No stock (continue)"
                logger.info(f"  {sku}: {status}")
            else:
                failed_count += 1
    
    logger.info("=" * 60)
    logger.info(f"✅ Sync complete!")
    logger.info(f"   Updated: {updated_count} variants")
    logger.info(f"   Failed: {failed_count} variants")
    logger.info(f"   Skipped: {skipped_count} variants (no SKU)")
    logger.info("=" * 60)
    
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
