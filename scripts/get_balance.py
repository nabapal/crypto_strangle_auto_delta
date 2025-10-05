import hashlib
import hmac
import requests
import time
import json

# Configuration
base_url = 'https://api.india.delta.exchange'

DELTA_API_KEY = 'X89Fb3ZEwUq60srXMb2Mp09wUvKiKi'
DELTA_API_SECRET = 'uVLc6vRCsX10sPo4dUNDPAbHdhjBz88bmWkaPNIrSrsZyrvLzmWAbOATG7NF'
api_key = DELTA_API_KEY
api_secret = DELTA_API_SECRET

def generate_signature(secret, message):
    """Generate HMAC SHA256 signature for Delta Exchange API"""
    message = bytes(message, 'utf-8')
    secret = bytes(secret, 'utf-8')
    hash = hmac.new(secret, message, hashlib.sha256)
    return hash.hexdigest()

def get_account_balance():
    """Fetch account balance from Delta Exchange"""
    try:
        # API endpoint details
        method = 'GET'
        timestamp = str(int(time.time()))
        path = '/v2/wallet/balances'
        url = f'{base_url}{path}'
        query_string = ''
        payload = ''
        
        # Create signature
        signature_data = method + timestamp + path + query_string + payload
        signature = generate_signature(api_secret, signature_data)
        
        # Request headers
        headers = {
            'api-key': api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'python-rest-client',
            'Content-Type': 'application/json'
        }
        
        # Make API request
        response = requests.request(
            method, 
            url, 
            data=payload, 
            params={}, 
            timeout=(3, 27), 
            headers=headers
        )
        
        # Check if request was successful
        if response.status_code == 200:
            data = response.json()
            
            if data.get('success'):
                print("✅ Account Balance Retrieved Successfully")
                print("=" * 50)
                
                # Display meta information
                meta = data.get('meta', {})
                if meta:
                    print(f"Net Equity: {meta.get('net_equity', 'N/A')}")
                    print(f"Robo Trading Equity: {meta.get('robo_trading_equity', 'N/A')}")
                    print("-" * 50)
                
                # Display balance for each asset
                balances = data.get('result', [])
                
                if balances:
                    print(f"{'Asset':<10} {'Total Balance':<15} {'Available':<15} {'Blocked Margin':<15}")
                    print("-" * 60)
                    
                    for balance in balances:
                        asset_symbol = balance.get('asset_symbol', 'N/A')
                        total_balance = balance.get('balance', '0')
                        available_balance = balance.get('available_balance', '0')
                        blocked_margin = balance.get('blocked_margin', '0')
                        
                        # Only show assets with non-zero balance
                        if float(total_balance) > 0:
                            print(f"{asset_symbol:<10} {total_balance:<15} {available_balance:<15} {blocked_margin:<15}")
                    
                    print("-" * 60)
                    print(f"Total Assets: {len([b for b in balances if float(b.get('balance', '0')) > 0])}")
                else:
                    print("No balance data found")
                
                return data
            else:
                print("❌ API returned success=false")
                print(f"Response: {data}")
                return None
                
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error details: {error_data}")
            except:
                print(f"Response text: {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        print("❌ Request timeout - please try again")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ Connection error - please check your internet connection")
        return None
    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return None

def display_detailed_balance(balance_data):
    """Display detailed balance information for a specific asset"""
    if not balance_data or not balance_data.get('success'):
        print("No valid balance data to display")
        return
    
    balances = balance_data.get('result', [])
    
    print("\n" + "=" * 80)
    print("DETAILED BALANCE BREAKDOWN")
    print("=" * 80)
    
    for balance in balances:
        if float(balance.get('balance', '0')) > 0:
            asset_symbol = balance.get('asset_symbol', 'N/A')
            print(f"\n🪙 {asset_symbol} Balance Details:")
            print(f"   Total Balance: {balance.get('balance', '0')}")
            print(f"   Available for Trading: {balance.get('available_balance', '0')}")
            print(f"   Available for Robo: {balance.get('available_balance_for_robo', '0')}")
            print(f"   Blocked Margin: {balance.get('blocked_margin', '0')}")
            print(f"   Order Margin (Isolated): {balance.get('order_margin', '0')}")
            print(f"   Position Margin (Isolated): {balance.get('position_margin', '0')}")
            print(f"   Cross Order Margin: {balance.get('cross_order_margin', '0')}")
            print(f"   Cross Position Margin: {balance.get('cross_position_margin', '0')}")
            print(f"   Portfolio Margin: {balance.get('portfolio_margin', '0')}")
            print(f"   Trading Fee Credit: {balance.get('trading_fee_credit', '0')}")
            print(f"   Commission: {balance.get('commission', '0')}")

if __name__ == "__main__":
    print("Delta Exchange - Account Balance Fetcher")
    print("=" * 50)
    
    # Check if API credentials are set
    if api_key == 'your_api_key_here' or api_secret == 'your_api_secret_here':
        print("⚠️  Please update your API credentials in the script:")
        print("   - Replace 'your_api_key_here' with your actual API key")
        print("   - Replace 'your_api_secret_here' with your actual API secret")
        print("\n📝 You can get your API credentials from:")
        print("   https://www.delta.exchange/app/api-keys")
        exit(1)
    
    # Fetch and display balance
    balance_data = get_account_balance()
    
    if balance_data:
        # Ask user if they want detailed breakdown
        print("\n" + "=" * 50)
        show_details = input("Show detailed balance breakdown? (y/n): ").lower().strip()
        
        if show_details in ['y', 'yes']:
            display_detailed_balance(balance_data)
        
        print(f"\n💾 Full response saved to balance_data variable")
        print("You can access it programmatically for further processing")
    else:
        print("\n❌ Failed to retrieve balance data")
        print("\n🔧 Troubleshooting tips:")
        print("1. Verify your API key and secret are correct")
        print("2. Ensure your API key has wallet read permissions")
        print("3. Check if you're using the correct base URL (production vs testnet)")
        print("4. Verify your system time is synchronized")
