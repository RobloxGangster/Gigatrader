from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
import os, json
tc=TradingClient(os.getenv('ALPACA_API_KEY_ID'), os.getenv('ALPACA_API_SECRET_KEY'), paper='paper' in os.getenv('APCA_API_BASE_URL',''), url=os.getenv('APCA_API_BASE_URL'))
req=GetOrdersRequest(status=QueryOrderStatus.OPEN, nested=True, limit=10)
orders=tc.get_orders(filter=req)
print(json.dumps([{'id':o.id,'symbol':o.symbol,'qty':str(o.qty),'cid':o.client_order_id,'status':o.status} for o in orders], indent=2))
