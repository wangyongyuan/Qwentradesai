"""
盘口挂单分布同步管理器
"""
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.order_book import OrderBookRepository
from app.config import settings
from app.utils.logger import logger


class OrderBookSyncManager(threading.Thread):
    """盘口挂单分布同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager, symbol: str):
        super().__init__(name=f"OrderBookSyncThread-{symbol}", daemon=False)
        self.api_manager = api_manager
        self.symbol = symbol
        self.ccxt_symbol = settings.symbol_to_ccxt_format(symbol)
        self.stop_event = threading.Event()
        self.db = db
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """每1小时同步一次"""
        if self.last_sync_time is None:
            return True
        time_diff = (now - self.last_sync_time).total_seconds()
        return time_diff >= 3600  # 1小时
    
    def _fetch_and_save_order_book(self) -> bool:
        """获取并保存盘口挂单分布数据"""
        try:
            # 使用OKX API /api/v5/market/books-full 获取完整订单簿
            exchange = self.api_manager.exchange
            
            # 调用OKX原始API: GET /api/v5/market/books-full
            # 将CCXT格式转换为OKX格式：BTC/USDT:USDT -> BTC-USDT-SWAP
            inst_id = self.ccxt_symbol.replace('/', '-').replace(':USDT', '-SWAP')
            
            # 参数: sz=1000 (返回1000档深度)
            params = {
                'instId': inst_id,
                'sz': '1000'  # 返回1000档深度
            }
            
            logger.debug(f"调用OKX API: /api/v5/market/books-full, 参数: {params}")
            response = exchange.public_get_market_books_full(params)
            
            if not response or response.get('code') != '0' or not response.get('data'):
                logger.warning(f"获取{self.symbol}盘口挂单数据失败: {response}")
                return False
            
            # OKX返回格式: {"code":"0","data":[{"asks":[...],"bids":[...],...}],...}
            data = response['data'][0] if response['data'] else {}
            
            if 'asks' not in data or 'bids' not in data:
                logger.warning(f"获取{self.symbol}盘口挂单数据为空")
                return False
            
            now = datetime.now(timezone.utc)
            
            # OKX books-full接口返回的格式：["价格", "数量", "订单数"] (3个字段)
            asks = data.get('asks', [])
            bids = data.get('bids', [])
            
            # 输出数据格式信息用于验证
            logger.info(f"========== {self.symbol} 盘口挂单数据抓取结果 ==========")
            logger.info(f"时间: {now}")
            logger.info(f"asks数量: {len(asks)}, bids数量: {len(bids)}")
            
            # 检查并输出前几个asks和bids的数据格式
            if asks:
                first_ask = asks[0]
                logger.info(f"asks[0] 数据格式: {first_ask}")
                logger.info(f"asks[0] 字段数量: {len(first_ask)}")
                if len(first_ask) >= 3:
                    logger.info(f"  - 深度价格: {first_ask[0]}")
                    logger.info(f"  - 数量(合约张数/交易币数量): {first_ask[1]}")
                    logger.info(f"  - 订单数量: {first_ask[2]}")
                else:
                    logger.warning(f"  ⚠️ asks[0] 字段数量不足3个，当前格式: {first_ask}")
            
            if bids:
                first_bid = bids[0]
                logger.info(f"bids[0] 数据格式: {first_bid}")
                logger.info(f"bids[0] 字段数量: {len(first_bid)}")
                if len(first_bid) >= 3:
                    logger.info(f"  - 深度价格: {first_bid[0]}")
                    logger.info(f"  - 数量(合约张数/交易币数量): {first_bid[1]}")
                    logger.info(f"  - 订单数量: {first_bid[2]}")
                else:
                    logger.warning(f"  ⚠️ bids[0] 字段数量不足3个，当前格式: {first_bid}")
            
            # 验证数据格式是否符合文档要求
            # 文档要求：["411.8", "10", "4"] - 价格、数量、订单数 (3个字段)
            format_valid = True
            if asks:
                for i, ask in enumerate(asks[:5]):  # 检查前5个
                    if len(ask) < 3:
                        logger.warning(f"  ⚠️ asks[{i}] 格式不符合要求，应为3个字段，实际: {len(ask)}个，数据: {ask}")
                        format_valid = False
            
            if bids:
                for i, bid in enumerate(bids[:5]):  # 检查前5个
                    if len(bid) < 3:
                        logger.warning(f"  ⚠️ bids[{i}] 格式不符合要求，应为3个字段，实际: {len(bid)}个，数据: {bid}")
                        format_valid = False
            
            if format_valid:
                logger.info(f"✓ 数据格式验证通过，符合文档要求 (3个字段: 价格、数量、订单数)")
            else:
                logger.warning(f"⚠️ 数据格式验证未完全通过，请检查")
            
            # 计算大单金额（档位数量超过平均值的2倍的档位，用于分析大单压力/支撑）
            large_ask_amount = None
            large_bid_amount = None
            
            if asks and len(asks) > 0:
                # 计算所有asks的平均档位数量
                total_ask_qty = sum(float(ask[1]) for ask in asks if len(ask) >= 2)
                avg_ask_qty_per_level = total_ask_qty / len(asks) if len(asks) > 0 else 0
                # 大单阈值：档位数量超过平均档位数量的2倍
                threshold = avg_ask_qty_per_level * 2.0
                if threshold > 0:
                    large_ask_amount = sum(
                        float(ask[1]) for ask in asks 
                        if len(ask) >= 2 and float(ask[1]) >= threshold
                    )
                    if large_ask_amount == 0:
                        large_ask_amount = None
            
            if bids and len(bids) > 0:
                # 计算所有bids的平均档位数量
                total_bid_qty = sum(float(bid[1]) for bid in bids if len(bid) >= 2)
                avg_bid_qty_per_level = total_bid_qty / len(bids) if len(bids) > 0 else 0
                # 大单阈值：档位数量超过平均档位数量的2倍
                threshold = avg_bid_qty_per_level * 2.0
                if threshold > 0:
                    large_bid_amount = sum(
                        float(bid[1]) for bid in bids 
                        if len(bid) >= 2 and float(bid[1]) >= threshold
                    )
                    if large_bid_amount == 0:
                        large_bid_amount = None
            
            logger.info(f"==========================================")
            
            with self.db.get_session() as session:
                if OrderBookRepository.insert_order_book(
                    session,
                    symbol=self.symbol,
                    time=now,
                    asks=asks,
                    bids=bids,
                    large_ask_amount=large_ask_amount,
                    large_bid_amount=large_bid_amount
                ):
                    self.last_sync_time = now
                    logger.info(f"{self.symbol} 盘口挂单数据保存成功")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}盘口挂单数据失败: {e}", exc_info=True)
            return False
    
    def run(self):
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_order_book()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"{self.symbol} 盘口挂单同步线程错误: {e}")
                time.sleep(60)

