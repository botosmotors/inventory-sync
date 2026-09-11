#!/usr/bin/env python3
"""
O'Neal FTP Inventory to Shopify Sync
Automatikusan letölti az O'Neal inventory CSV-t az FTP-ről,
és frissíti a Shopify termékinventoryt.
"""

import os
import sys
import json
import ftplib
import csv
import logging
from io import StringIO
from datetime import datetime
import requests
import base64

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
            logger.error("No access token available")
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
        """Update inventory policy (continue or deny)"""
        if not self.access_token:
            return False
        
        url = f"{self.base_url}/products/{product_id}/variants/{variant_id}.json"
        headers = self.get_auth_header()
        
        payload = {
            'variant': {
                'inventory_policy': policy  # 'continue' or 'deny'
            }
        }
        
        try:
            response = requests.put(url, headers=headers, json=payload)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to update inventory policy: {e}")
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
            
            # Find the file
            files = ftp.nlst(self.filename.rsplit('/', 1)[0])
            matching_file = None
            
            for f in files:
                if 'inventories_12019' in f and 'ONeal' in f:
                    matching_file = f
                    break
            
            if not matching_file:
                matching_file = self.filename
            
            # Download file
            csv_data = StringIO()
            ftp.retrlines(f'RETR {matching_file}', csv_data.write)
            ftp.quit()
            
            logger.info(f"✅ Downloaded inventory file: {matching_file}")
            return csv_data.getvalue()
        
        except ftplib.all_errors as e:
            logger.error(f"❌ FTP error: {e}")
            return None
    
    def parse_inventory(self, csv_content):
        """Parse CSV and extract stock data"""
        try:
            reader = csv.DictReader(StringIO(csv_content), delimiter=';')
            
            for row in reader:
                item_number = row.get('item_number', '').strip()
                stock = int(row.get('stock', 0))
                
                if item_number:
                    self.inventory_data[item_number] = {
                        'stock': stock,
                        'has_stock': stock > 0
                    }
            
            logger.info(f"✅ Parsed {len(self.inventory_data)} items from inventory")
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
    for product in shopify.products:
        for variant in product.get('variants', []):
            sku = variant.get('sku', '').strip()
            
            if not sku:
                continue
            
            # Check O'Neal stock
            has_stock = oneal.get_stock_status(sku)
            
            # Determine policy: 'continue' if has stock, 'deny' if no stock
            policy = 'continue' if has_stock else 'deny'
            
            # Update Shopify
            if shopify.update_inventory_policy(product['id'], variant['id'], policy):
                updated_count += 1
                status = "✅ In stock" if has_stock else "❌ Out of stock"
                logger.info(f"  {sku}: {status}")
    
    logger.info("=" * 60)
    logger.info(f"✅ Sync complete! Updated {updated_count} variants")
    logger.info("=" * 60)
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
