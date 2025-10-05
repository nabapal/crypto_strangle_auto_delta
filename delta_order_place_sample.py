import time
import logging
import hashlib
import hmac
import requests
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass

@dataclass
class OrderConfig:
    product_id: int
    symbol: str
    side: str  # "buy" or "sell"
    size: int
    max_retries: int = 4
    retry_delay: float = 1.0  # seconds between retries
    partial_fill_threshold: float = 0.1  # 10% minimum fill to consider success
    order_timeout: float = 30.0  # seconds to wait before canceling

class DeltaOrderManager:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://api.india.delta.exchange"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.logger = logging.getLogger(__name__)
        
    def generate_signature(self, secret: str, message: str) -> str:
        """Generate HMAC signature for authentication"""
        message = bytes(message, 'utf-8')
        secret = bytes(secret, 'utf-8')
        hash = hmac.new(secret, message, hashlib.sha256)
        return hash.hexdigest()
    
    def make_request(self, method: str, path: str, payload: str = "", query_params: Dict = None) -> Dict:
        """Make authenticated API request"""
        timestamp = str(int(time.time()))
        query_string = ""
        if query_params:
            query_string = "?" + "&".join([f"{k}={v}" for k, v in query_params.items()])
        
        signature_data = method + timestamp + path + query_string + payload
        signature = self.generate_signature(self.api_secret, signature_data)
        
        headers = {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'User-Agent': 'delta-order-manager',
            'Content-Type': 'application/json'
        }
        
        url = f"{self.base_url}/v2{path}"
        if query_string:
            url += query_string
            
        response = requests.request(
            method, url, data=payload, timeout=(3, 27), headers=headers
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            self.logger.error(f"API request failed: {response.status_code} - {response.text}")
            response.raise_for_status()
    
    def get_best_bid_ask(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """Get best bid and ask prices from ticker"""
        try:
            response = self.make_request("GET", f"/tickers/{symbol}")
            if response.get("success"):
                quotes = response["result"].get("quotes", {})
                best_bid = quotes.get("best_bid")
                best_ask = quotes.get("best_ask")
                
                return (
                    float(best_bid) if best_bid else None,
                    float(best_ask) if best_ask else None
                )
        except Exception as e:
            self.logger.error(f"Failed to get best bid/ask for {symbol}: {e}")
        
        return None, None
    
    def get_product_info(self, product_id: int) -> Optional[Dict]:
        """Get product information including tick size"""
        try:
            response = self.make_request("GET", f"/products/{product_id}")
            if response.get("success"):
                return response["result"]
        except Exception as e:
            self.logger.error(f"Failed to get product info for {product_id}: {e}")
        
        return None
    
    def round_to_tick_size(self, price: float, tick_size: float) -> float:
        """Round price to the nearest tick size"""
        tick_decimal = Decimal(str(tick_size))
        price_decimal = Decimal(str(price))
        return float(price_decimal.quantize(tick_decimal, rounding=ROUND_HALF_UP))
    
    def place_limit_order(self, config: OrderConfig, limit_price: float) -> Optional[Dict]:
        """Place a limit order"""
        payload = {
            "product_id": config.product_id,
            "size": config.size,
            "side": config.side,
            "order_type": "limit_order",
            "limit_price": str(limit_price),
            "time_in_force": "gtc",
            "reduce_only": "false",
            "post_only": "false",
            "client_order_id": f"limit-{int(time.time())}-{config.side}"
        }
        
        try:
            response = self.make_request("POST", "/orders", payload=str(payload).replace("'", '"'))
            if response.get("success"):
                self.logger.info(f"Limit order placed: {response['result']['id']} at price {limit_price}")
                return response["result"]
        except Exception as e:
            self.logger.error(f"Failed to place limit order: {e}")
        
        return None
    
    def place_market_order(self, config: OrderConfig) -> Optional[Dict]:
        """Place a market order as fallback"""
        payload = {
            "product_id": config.product_id,
            "size": config.size,
            "side": config.side,
            "order_type": "market_order",
            "reduce_only": "false",
            "client_order_id": f"market-{int(time.time())}-{config.side}"
        }
        
        try:
            response = self.make_request("POST", "/orders", payload=str(payload).replace("'", '"'))
            if response.get("success"):
                self.logger.info(f"Market order placed: {response['result']['id']}")
                return response["result"]
        except Exception as e:
            self.logger.error(f"Failed to place market order: {e}")
        
        return None
    
    def get_order_status(self, order_id: int) -> Optional[Dict]:
        """Get current order status"""
        try:
            response = self.make_request("GET", f"/orders/{order_id}")
            if response.get("success"):
                return response["result"]
        except Exception as e:
            self.logger.error(f"Failed to get order status for {order_id}: {e}")
        
        return None
    
    def cancel_order(self, order_id: int, product_id: int) -> bool:
        """Cancel an order"""
        payload = {
            "id": order_id,
            "product_id": product_id
        }
        
        try:
            response = self.make_request("DELETE", "/orders", payload=str(payload).replace("'", '"'))
            if response.get("success"):
                self.logger.info(f"Order {order_id} cancelled successfully")
                return True
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")
        
        return False
    
    def wait_for_fill_or_timeout(self, order_id: int, config: OrderConfig) -> Tuple[bool, float]:
        """
        Wait for order to fill or timeout
        Returns: (is_filled_enough, fill_percentage)
        """
        start_time = time.time()
        
        while time.time() - start_time < config.order_timeout:
            order_status = self.get_order_status(order_id)
            if not order_status:
                break
                
            state = order_status.get("state")
            size = order_status.get("size", 0)
            unfilled_size = order_status.get("unfilled_size", size)
            filled_size = size - unfilled_size
            fill_percentage = filled_size / size if size > 0 else 0
            
            # Check if order is completely filled
            if state == "closed":
                self.logger.info(f"Order {order_id} completely filled")
                return True, 1.0
            
            # Check if order is cancelled
            if state == "cancelled":
                self.logger.info(f"Order {order_id} was cancelled")
                return False, fill_percentage
            
            # Check if we have sufficient partial fill
            if fill_percentage >= config.partial_fill_threshold:
                self.logger.info(f"Order {order_id} partially filled: {fill_percentage:.2%}")
                return True, fill_percentage
            
            time.sleep(1)  # Check every second
        
        # Timeout reached
        order_status = self.get_order_status(order_id)
        if order_status:
            size = order_status.get("size", 0)
            unfilled_size = order_status.get("unfilled_size", size)
            filled_size = size - unfilled_size
            fill_percentage = filled_size / size if size > 0 else 0
            
            self.logger.warning(f"Order {order_id} timed out with {fill_percentage:.2%} fill")
            return fill_percentage >= config.partial_fill_threshold, fill_percentage
        
        return False, 0.0

    def execute_order_strategy(self, config: OrderConfig) -> Dict[str, Any]:
        """
        Execute the complete order strategy:
        1. Try limit orders at best bid/ask up to max_retries
        2. Cancel any open orders before retry
        3. Fallback to market order if all retries fail
        4. Handle partial fills
        """
        self.logger.info(f"Starting order strategy for {config.symbol} - {config.side} {config.size}")
        
        # Get product information
        product_info = self.get_product_info(config.product_id)
        if not product_info:
            return {"success": False, "error": "Failed to get product information"}
        
        tick_size = float(product_info.get("tick_size", 0.1))
        
        # Track all order attempts
        order_attempts = []
        total_filled = 0
        
        # Retry limit orders
        for attempt in range(config.max_retries):
            self.logger.info(f"Limit order attempt {attempt + 1}/{config.max_retries}")
            
            # Get current best bid/ask
            best_bid, best_ask = self.get_best_bid_ask(config.symbol)
            if best_bid is None or best_ask is None:
                self.logger.error("Failed to get best bid/ask prices")
                time.sleep(config.retry_delay)
                continue
            
            # Determine limit price based on side
            if config.side == "buy":
                limit_price = best_bid  # Buy at best bid (maker)
            else:
                limit_price = best_ask  # Sell at best ask (maker)
            
            # Round to tick size
            limit_price = self.round_to_tick_size(limit_price, tick_size)
            
            # Place limit order
            order = self.place_limit_order(config, limit_price)
            if not order:
                self.logger.error(f"Failed to place limit order on attempt {attempt + 1}")
                time.sleep(config.retry_delay)
                continue
            
            order_id = order["id"]
            order_attempts.append({
                "attempt": attempt + 1,
                "order_id": order_id,
                "order_type": "limit",
                "price": limit_price,
                "timestamp": time.time()
            })
            
            # Wait for fill or timeout
            is_filled, fill_percentage = self.wait_for_fill_or_timeout(order_id, config)
            
            if is_filled:
                # Update remaining size for next attempt
                filled_amount = int(config.size * fill_percentage)
                total_filled += filled_amount
                config.size -= filled_amount
                
                order_attempts[-1]["filled"] = filled_amount
                order_attempts[-1]["fill_percentage"] = fill_percentage
                
                if config.size <= 0:
                    self.logger.info("Order strategy completed successfully with limit orders")
                    return {
                        "success": True,
                        "strategy": "limit_orders",
                        "total_filled": total_filled,
                        "attempts": order_attempts
                    }
            else:
                # Cancel the unfilled order before retry
                self.logger.info(f"Cancelling unfilled order {order_id}")
                self.cancel_order(order_id, config.product_id)
                order_attempts[-1]["cancelled"] = True
            
            # Wait before next retry
            if attempt < config.max_retries - 1:
                time.sleep(config.retry_delay)
        
        # All limit order attempts failed, fallback to market order
        if config.size > 0:
            self.logger.info("Falling back to market order")
            market_order = self.place_market_order(config)
            
            if market_order:
                order_attempts.append({
                    "attempt": "market_fallback",
                    "order_id": market_order["id"],
                    "order_type": "market",
                    "timestamp": time.time()
                })
                
                # Market orders typically fill immediately, but let's check
                time.sleep(2)  # Brief wait for settlement
                final_status = self.get_order_status(market_order["id"])
                
                if final_status and final_status.get("state") == "closed":
                    filled_amount = final_status.get("size", 0) - final_status.get("unfilled_size", 0)
                    total_filled += filled_amount
                    
                    order_attempts[-1]["filled"] = filled_amount
                    order_attempts[-1]["fill_percentage"] = 1.0
                    
                    self.logger.info("Order strategy completed with market order fallback")
                    return {
                        "success": True,
                        "strategy": "market_fallback",
                        "total_filled": total_filled,
                        "attempts": order_attempts
                    }
        
        # Complete failure
        self.logger.error("Order strategy failed completely")
        return {
            "success": False,
            "strategy": "failed",
            "total_filled": total_filled,
            "attempts": order_attempts,
            "error": "All attempts failed"
        }

# Usage Example
def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Initialize order manager
    order_manager = DeltaOrderManager(
        api_key="your_api_key",
        api_secret="your_api_secret"
    )
    
    # Configure order
    config = OrderConfig(
        product_id=98170,  # C-BTC-126000-061025
        symbol="C-BTC-126000-061025",
        side="sell",
        size=1,
        max_retries=4,
        retry_delay=2.0,
        partial_fill_threshold=0.1,  # Accept 10% partial fill
        order_timeout=30.0
    )
    
    # Execute strategy
    result = order_manager.execute_order_strategy(config)
    
    # Print results
    print(f"Strategy Result: {result}")
    
    if result["success"]:
        print(f"✅ Successfully filled {result['total_filled']} contracts using {result['strategy']}")
    else:
        print(f"❌ Strategy failed: {result.get('error', 'Unknown error')}")
    
    # Print attempt details
    for attempt in result["attempts"]:
        print(f"Attempt {attempt['attempt']}: {attempt}")

if __name__ == "__main__":
    main()
