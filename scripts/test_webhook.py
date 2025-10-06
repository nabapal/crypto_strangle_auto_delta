import requests
import json
import time
from datetime import datetime

# Base URL for Delta Exchange API
base_url = 'https://api.india.delta.exchange'

# Option contract symbol
symbol = 'C-BTC-124000-071025'

def fetch_l2_orderbook(symbol, depth=10):
    """
    Fetch L2 orderbook data for a given symbol
    """
    try:
        url = f'{base_url}/v2/l2orderbook/{symbol}'
        params = {'depth': depth}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('success'):
            return data['result']
        else:
            print(f"API Error: {data}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request error for L2 orderbook: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON decode error for L2 orderbook: {e}")
        return None

def fetch_ticker(symbol):
    """
    Fetch ticker data for a given symbol
    """
    try:
        url = f'{base_url}/v2/tickers/{symbol}'
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('success'):
            return data['result']
        else:
            print(f"API Error: {data}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Request error for ticker: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON decode error for ticker: {e}")
        return None

def display_l2_orderbook(orderbook_data):
    """
    Display L2 orderbook data in a readable format
    """
    if not orderbook_data:
        print("No orderbook data available")
        return
    
    print(f"\n=== L2 ORDERBOOK for {orderbook_data.get('symbol', 'Unknown')} ===")
    print(f"Last Updated: {datetime.fromtimestamp(orderbook_data.get('last_updated_at', 0) / 1000000)}")
    
    # Display sell orders (asks) - sorted from lowest to highest price
    print("\n--- SELL ORDERS (ASKS) ---")
    print("Price\t\tSize\t\tDepth")
    print("-" * 40)
    
    sell_orders = orderbook_data.get('sell', [])
    for order in reversed(sell_orders[-5:]):  # Show top 5 asks
        print(f"{order['price']}\t\t{order['size']}\t\t{order['depth']}")
    
    # Display buy orders (bids) - sorted from highest to lowest price
    print("\n--- BUY ORDERS (BIDS) ---")
    print("Price\t\tSize\t\tDepth")
    print("-" * 40)
    
    buy_orders = orderbook_data.get('buy', [])
    for order in buy_orders[:5]:  # Show top 5 bids
        print(f"{order['price']}\t\t{order['size']}\t\t{order['depth']}")

def display_ticker(ticker_data):
    """
    Display ticker data in a readable format
    """
    if not ticker_data:
        print("No ticker data available")
        return
    
    print(f"\n=== TICKER DATA for {ticker_data.get('symbol', 'Unknown')} ===")
    print(f"Product ID: {ticker_data.get('product_id')}")
    print(f"Contract Type: {ticker_data.get('contract_type')}")
    print(f"Strike Price: {ticker_data.get('strike_price')}")
    print(f"Spot Price: {ticker_data.get('spot_price')}")
    print(f"Mark Price: {ticker_data.get('mark_price')}")
    
    # Price data
    print(f"\n--- PRICE DATA ---")
    print(f"Open: {ticker_data.get('open')}")
    print(f"High: {ticker_data.get('high')}")
    print(f"Low: {ticker_data.get('low')}")
    print(f"Close: {ticker_data.get('close')}")
    
    # Volume and Open Interest
    print(f"\n--- VOLUME & OPEN INTEREST ---")
    print(f"Volume: {ticker_data.get('volume')}")
    print(f"Turnover: {ticker_data.get('turnover')} {ticker_data.get('turnover_symbol')}")
    print(f"Open Interest: {ticker_data.get('oi')}")
    print(f"OI Value: {ticker_data.get('oi_value')} {ticker_data.get('oi_value_symbol')}")
    
    # Quotes (Best Bid/Ask)
    quotes = ticker_data.get('quotes', {})
    if quotes:
        print(f"\n--- BEST BID/ASK ---")
        print(f"Best Bid: {quotes.get('best_bid')} (Size: {quotes.get('bid_size')})")
        print(f"Best Ask: {quotes.get('best_ask')} (Size: {quotes.get('ask_size')})")
        print(f"Bid IV: {quotes.get('bid_iv')}")
        print(f"Ask IV: {quotes.get('ask_iv')}")
    
    # Greeks (for options)
    greeks = ticker_data.get('greeks', {})
    if greeks:
        print(f"\n--- OPTION GREEKS ---")
        print(f"Delta: {greeks.get('delta')}")
        print(f"Gamma: {greeks.get('gamma')}")
        print(f"Theta: {greeks.get('theta')}")
        print(f"Vega: {greeks.get('vega')}")
        print(f"Rho: {greeks.get('rho')}")
    
    # Price Band
    price_band = ticker_data.get('price_band', {})
    if price_band:
        print(f"\n--- PRICE BAND ---")
        print(f"Lower Limit: {price_band.get('lower_limit')}")
        print(f"Upper Limit: {price_band.get('upper_limit')}")
    
    print(f"\nTimestamp: {datetime.fromtimestamp(ticker_data.get('timestamp', 0) / 1000000)}")

def main():
    """
    Main function to fetch and display webhook data
    """
    print(f"Fetching market data for option contract: {symbol}")
    print("=" * 60)
    
    # Fetch L2 orderbook data
    print("Fetching L2 orderbook data...")
    orderbook_data = fetch_l2_orderbook(symbol, depth=10)
    display_l2_orderbook(orderbook_data)
    
    print("\n" + "=" * 60)
    
    # Fetch ticker data
    print("Fetching ticker data...")
    ticker_data = fetch_ticker(symbol)
    display_ticker(ticker_data)
    
    # Optional: Save data to files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if orderbook_data:
        with open(f'orderbook_{symbol}_{timestamp}.json', 'w') as f:
            json.dump(orderbook_data, f, indent=2)
        print(f"\nOrderbook data saved to: orderbook_{symbol}_{timestamp}.json")
    
    if ticker_data:
        with open(f'ticker_{symbol}_{timestamp}.json', 'w') as f:
            json.dump(ticker_data, f, indent=2)
        print(f"Ticker data saved to: ticker_{symbol}_{timestamp}.json")

if __name__ == "__main__":
    main()
