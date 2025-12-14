"""
API管理器 - 统一管理交易所API请求
"""
import ccxt
import time
import threading
from queue import PriorityQueue
from enum import IntEnum
from dataclasses import dataclass
from typing import Callable, Any, Optional, List, Dict
from app.config import settings
from app.utils.logger import logger


class RequestPriority(IntEnum):
    """请求优先级"""
    STOP_LOSS = 1  # 止损（最高优先级）
    TRADE = 2  # 交易
    QUERY = 3  # 查询（最低优先级）


@dataclass
class APIRequest:
    """API请求"""
    priority: RequestPriority
    func: Callable
    args: tuple
    kwargs: dict
    callback: Optional[Callable] = None
    timestamp: float = 0


class APIManager:
    """API管理器"""
    
    def __init__(self):
        """初始化API管理器"""
        # 初始化交易所
        exchange_class = getattr(ccxt, settings.EXCHANGE_NAME)
        exchange_config = {
            'apiKey': settings.EXCHANGE_API_KEY,
            'secret': settings.EXCHANGE_SECRET,
            'password': settings.EXCHANGE_PASSPHRASE,
            'sandbox': settings.EXCHANGE_SANDBOX,
            'enableRateLimit': False,  # 我们自己控制限流
            'options': {
                'defaultType': 'swap',  # 默认使用永续合约
                # OKX永续合约配置
                'defaultContractSize': 1,  # 合约乘数，CCXT会自动处理
            }
        }
        self.exchange = exchange_class(exchange_config)
        
        # 请求队列
        self.request_queue = PriorityQueue()
        self.last_request_time = 0
        self.request_lock = threading.Lock()
        
        # 限流配置
        self.rate_limit = settings.API_RATE_LIMIT  # 每2秒10次
        self.rate_window = settings.API_RATE_WINDOW  # 时间窗口（秒）
        self.request_count = 0
        self.window_start = time.time()
        
        # 工作线程
        self.worker_thread = None
        self.running = False
    
    def start(self):
        """启动API管理器"""
        if self.running:
            return
        
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_thread, daemon=True)
        self.worker_thread.start()
        logger.info("API管理器已启动")
    
    def stop(self):
        """停止API管理器"""
        if not self.running:
            return
        
        self.running = False
        
        # 等待队列处理完成
        self.request_queue.join()
        
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        
        logger.info("API管理器已停止")
    
    def _check_rate_limit(self):
        """检查限流"""
        current_time = time.time()
        
        # 如果超过时间窗口，重置计数
        if current_time - self.window_start >= self.rate_window:
            self.request_count = 0
            self.window_start = current_time
        
        # 如果达到限制，等待
        if self.request_count >= self.rate_limit:
            wait_time = self.rate_window - (current_time - self.window_start)
            if wait_time > 0:
                logger.debug(f"达到限流，等待 {wait_time:.2f} 秒")
                time.sleep(wait_time)
                # 重置窗口
                self.request_count = 0
                self.window_start = time.time()
        
        # 更新计数
        self.request_count += 1
        self.last_request_time = time.time()
    
    def _enforce_min_interval(self):
        """强制执行最小请求间隔"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # 最小间隔：200ms（每2秒10次 = 200ms/次）
        min_interval = self.rate_window / self.rate_limit  # 0.2秒
        
        if time_since_last < min_interval:
            sleep_time = min_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def submit_request(
        self,
        priority: RequestPriority,
        func: Callable,
        *args,
        callback: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """提交API请求（同步）"""
        # 创建请求对象
        request = APIRequest(
            priority=priority,
            func=func,
            args=args,
            kwargs=kwargs,
            callback=callback,
            timestamp=time.time()
        )
        
        # 放入优先级队列（优先级越小越先执行）
        self.request_queue.put((priority.value, request.timestamp, request))
        
        # 等待结果（使用Event）
        result_event = threading.Event()
        result_container = {'result': None, 'error': None}
        
        def callback_wrapper(result, error=None):
            result_container['result'] = result
            result_container['error'] = error
            result_event.set()
        
        request.callback = callback_wrapper
        
        # 等待结果
        result_event.wait(timeout=settings.API_REQUEST_TIMEOUT)
        
        if result_container['error']:
            raise result_container['error']
        
        return result_container['result']
    
    def _worker_thread(self):
        """工作线程（处理请求队列）"""
        logger.info("API管理器工作线程启动")
        
        while self.running:
            try:
                # 从队列获取请求（阻塞）
                _, _, request = self.request_queue.get(timeout=1)
                
                # 限流检查
                self._check_rate_limit()
                self._enforce_min_interval()
                
                # 执行请求
                try:
                    result = request.func(*request.args, **request.kwargs)
                    
                    # 调用回调
                    if request.callback:
                        request.callback(result, None)
                        
                except Exception as e:
                    error_str = str(e)
                    # 对于认证错误，只记录警告，不记录完整堆栈
                    if ('401' in error_str or 'Unauthorized' in error_str or
                        'apiKey' in error_str or 'credential' in error_str.lower() or
                        'authentication' in error_str.lower()):
                        logger.warning(f"API请求认证失败（API密钥未配置或无效）: {error_str}")
                    else:
                        logger.error(f"API请求执行失败: {error_str}", exc_info=True)
                    
                    # 调用回调（传递错误）
                    if request.callback:
                        request.callback(None, e)
                
                # 标记任务完成
                self.request_queue.task_done()
                
            except:
                # 超时或其他异常，继续循环
                continue
        
        logger.info("API管理器工作线程停止")
    
    # 常用API封装
    def get_balance(self) -> Optional[float]:
        """获取账户余额"""
        def _get_balance():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    logger.warning("EXCHANGE_API_KEY未配置，无法获取账户余额")
                    return None
                
                balance = self.exchange.fetch_balance({'type': 'swap'})
                if balance and 'USDT' in balance and balance['USDT']:
                    return balance['USDT']['free']
                return None
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证相关错误
                if ('apiKey' in error_str or 'credential' in error_str.lower() or 
                    '401' in error_str or 'Unauthorized' in error_str or
                    'authentication' in error_str.lower()):
                    logger.warning(f"交易所API密钥未配置或无效，无法获取账户余额: {error_str}")
                else:
                    logger.error(f"获取账户余额失败: {error_str}", exc_info=True)
                return None
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_balance
        )
    
    def get_current_price(self, symbol: str = None) -> float:
        """获取当前价格（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        # 确保symbol是CCXT格式（如 ETH/USDT:USDT）
        # 如果传入的是 ETH 这样的格式，转换为 CCXT 格式
        if symbol and '/' not in symbol:
            symbol = settings.symbol_to_ccxt_format(symbol)
        
        def _get_price():
            try:
                # 确保markets已加载（CCXT需要markets才能识别symbol）
                if not hasattr(self.exchange, 'markets') or not self.exchange.markets:
                    self.exchange.load_markets()
                
                # 使用真实API获取价格
                ticker = self.exchange.fetch_ticker(symbol)
                return float(ticker['last'])
            except Exception as e:
                error_str = str(e)
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取价格失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"获取价格失败: {error_str}", exc_info=True)
                return None
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_price
        )
    
    def get_ticker(self, symbol: str = None) -> dict:
        """获取完整ticker信息（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        def _get_ticker():
            try:
                return self.exchange.fetch_ticker(symbol)
            except Exception as e:
                error_str = str(e)
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取ticker失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"获取ticker失败: {error_str}", exc_info=True)
                return None
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_ticker
        )
    
    def get_orderbook(self, symbol: str = None, limit: int = 20) -> dict:
        """获取订单簿（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        def _get_orderbook():
            try:
                return self.exchange.fetch_order_book(symbol, limit)
            except Exception as e:
                error_str = str(e)
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取订单簿失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"获取订单簿失败: {error_str}", exc_info=True)
                return None
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_orderbook
        )
    
    def get_klines(self, symbol: str = None, timeframe: str = '15m', limit: int = 100, since: int = None) -> list:
        """获取K线数据（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        def _get_klines():
            try:
                if since:
                    return self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                else:
                    return self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except Exception as e:
                error_str = str(e)
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取K线数据失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"获取K线数据失败: {error_str}", exc_info=True)
                return []
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_klines
        )
    
    def get_funding_rate(self, symbol: str = None) -> dict:
        """获取当前资金费率（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        def _get_funding_rate():
            # OKX API: GET /api/v5/public/funding-rate
            # CCXT方法：fetch_funding_rate
            try:
                return self.exchange.fetch_funding_rate(symbol)
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取资金费率失败（API密钥未配置或无效）: {error_str}")
                    return None
                # 如果CCXT不支持，使用原始API
                logger.warning(f"CCXT fetch_funding_rate失败，尝试原始API: {error_str}")
                try:
                    # 转换为OKX格式：BTC/USDT:USDT -> BTC-USDT-SWAP
                    inst_id = symbol.replace('/', '-').replace(':USDT', '-SWAP')
                    result = self.exchange.public_get_public_funding_rate({'instId': inst_id})
                    if result and 'data' in result and len(result['data']) > 0:
                        data = result['data'][0]
                        return {
                            'fundingRate': float(data.get('fundingRate', 0)),
                            'nextFundingTime': int(data.get('nextFundingTime', 0)),
                            'instId': data.get('instId', '')
                        }
                except Exception as e2:
                    logger.error(f"使用原始API获取资金费率也失败: {e2}", exc_info=True)
                return None
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_funding_rate
        )
    
    def get_funding_rate_history(self, symbol: str = None, limit: int = 100) -> list:
        """获取资金费率历史（真实API）"""
        symbol = symbol or settings.SYMBOL
        
        def _get_funding_rate_history():
            try:
                # OKX API: GET /api/v5/public/funding-rate-history
                # 转换为OKX格式：BTC/USDT:USDT -> BTC-USDT-SWAP
                inst_id = symbol.replace('/', '-').replace(':USDT', '-SWAP')
                result = self.exchange.public_get_public_funding_rate_history({
                    'instId': inst_id,
                    'limit': limit
                })
                if result and 'data' in result:
                    return result['data']
                return []
            except Exception as e:
                error_str = str(e)
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower() or '50101' in error_str):
                    logger.warning(f"获取资金费率历史失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"获取资金费率历史失败: {error_str}", exc_info=True)
                return []
        
        return self.submit_request(
            RequestPriority.QUERY,
            _get_funding_rate_history
        )

    def create_order(
        self,
        symbol: str,
        type: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        params: Optional[dict] = None
    ) -> dict:
        """
        创建订单（下单）
        
        Args:
            symbol: 交易对，如 'BTC/USDT:USDT'
            type: 订单类型，如 'market'（市价单）、'limit'（限价单）、'stop_market'（止损市价单）
            side: 买卖方向，'buy'（买入）或 'sell'（卖出）
            amount: 数量
            price: 价格（限价单必需）
            params: 额外参数，如杠杆、保证金模式等
            
        Returns:
            dict: 订单信息，包含订单ID、状态等
        """
        def _create_order():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
                
                # 构建订单参数
                order_params = params or {}
                
                # 如果是限价单，必须提供价格
                if type == 'limit' and price is None:
                    raise ValueError("限价单必须提供价格")
                
                # 调用CCXT创建订单
                # 重要：OKX永续合约的数量单位处理
                # OKX的ETH-USDT-SWAP合约乘数是0.1（1张合约=0.1 ETH）
                # 根据CCXT文档，amount参数应该是币的数量，CCXT会自动转换为合约张数
                # 但实际测试发现，CCXT可能没有正确处理，需要手动转换为合约张数
                
                # 获取交易对的合约信息
                try:
                    market = self.exchange.market(symbol)
                    contract_size = market.get('contractSize', 0.1)  # 默认0.1（ETH）
                except:
                    # 如果获取失败，根据symbol判断
                    if 'ETH' in symbol.upper():
                        contract_size = 0.1
                    else:
                        contract_size = 1.0
                    logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
                
                # 重要：OKX的create_order需要合约张数，不是币的数量
                # 将币的数量转换为合约张数
                if contract_size != 1.0 and contract_size > 0:
                    contracts = amount / contract_size
                    # 四舍五入到最小精度（合约张数通常是整数或0.1的倍数）
                    contracts = round(contracts, 1)
                    order_amount = contracts
                    logger.info(
                        f"[OKX下单] 数量转换: 币数量={amount:.6f}, "
                        f"合约乘数={contract_size}, 合约张数={contracts:.1f}"
                    )
                else:
                    order_amount = amount
                    logger.info(f"[OKX下单] 数量: {amount:.6f} (合约乘数=1，无需转换)")
                
                # 检查是否设置了止盈止损参数
                has_tp_sl = 'slTriggerPx' in order_params or 'tpTriggerPx' in order_params
                
                # 如果设置了止盈止损，需要确保ordType参数正确
                if has_tp_sl:
                    # 确保ordType参数存在（OKX要求）
                    if 'ordType' not in order_params:
                        order_params['ordType'] = 'limit' if type == 'limit' else 'market'
                    logger.debug(f"[OKX下单] 设置止盈止损，ordType={order_params.get('ordType')}")
                
                # 转换为OKX格式的交易对：BTC/USDT:USDT -> BTC-USDT-SWAP
                inst_id = symbol.replace('/', '-').replace(':USDT', '-SWAP')
                
                # 如果设置了止盈止损，可能需要使用原始API
                # 先尝试使用CCXT的create_order
                try:
                    order = self.exchange.create_order(
                        symbol=symbol,
                        type=type,
                        side=side,
                        amount=order_amount,  # 使用合约张数
                        price=price,
                        params=order_params
                    )
                except Exception as ccxt_error:
                    error_str = str(ccxt_error)
                    # 如果CCXT报错ordType相关错误，尝试使用原始API
                    if 'ordType' in error_str.lower() or '51000' in error_str:
                        logger.warning(f"CCXT下单失败（ordType错误），尝试使用OKX原始API: {ccxt_error}")
                        
                        # 使用OKX原始API创建订单
                        # 构建OKX API请求参数
                        okx_params = {
                            'instId': inst_id,
                            'tdMode': order_params.get('tdMode', 'cross'),
                            'side': side,
                            'ordType': order_params.get('ordType', 'limit'),
                            'sz': str(order_amount),
                            'posSide': order_params.get('posSide', 'net')
                        }
                        
                        # 限价单需要价格
                        if type == 'limit' and price:
                            okx_params['px'] = str(price)
                        
                        # 添加杠杆（如果提供）
                        if 'leverage' in order_params:
                            okx_params['lever'] = str(order_params['leverage'])
                        
                        # 添加止盈止损参数
                        if 'slTriggerPx' in order_params:
                            okx_params['slTriggerPx'] = order_params['slTriggerPx']
                        if 'slOrdPx' in order_params:
                            okx_params['slOrdPx'] = order_params['slOrdPx']
                        if 'tpTriggerPx' in order_params:
                            okx_params['tpTriggerPx'] = order_params['tpTriggerPx']
                        if 'tpOrdPx' in order_params:
                            okx_params['tpOrdPx'] = order_params['tpOrdPx']
                        
                        logger.debug(f"[OKX原始API] 请求参数: {okx_params}")
                        
                        # 调用OKX原始API
                        result = self.exchange.private_post_trade_order(okx_params)
                        
                        if result and result.get('code') == '0' and result.get('data'):
                            # 转换OKX响应格式为CCXT格式
                            order_data = result['data'][0]
                            order = {
                                'id': order_data.get('ordId', ''),
                                'clientOrderId': order_data.get('clOrdId', ''),
                                'symbol': symbol,
                                'type': type,
                                'side': side,
                                'amount': order_amount,
                                'price': price,
                                'status': 'open',
                                'filled': 0,
                                'remaining': order_amount,
                                'info': order_data
                            }
                            logger.info(f"[OKX原始API] 订单创建成功: {order['id']}")
                        else:
                            error_msg = result.get('msg', '未知错误') if result else '返回结果为空'
                            raise Exception(f"OKX原始API下单失败: {error_msg}")
                    else:
                        # 其他错误，直接抛出
                        raise
                
                # 记录订单信息用于调试数量问题
                logger.info(
                    f"[OKX下单] 订单创建成功\n"
                    f"  - 订单ID: {order.get('id')}\n"
                    f"  - 交易对: {symbol}\n"
                    f"  - 类型: {type}\n"
                    f"  - 方向: {side}\n"
                    f"  - 输入数量（币）: {amount:.6f}\n"
                    f"  - 下单数量（转换后）: {order_amount:.6f}\n"
                    f"  - 合约乘数: {contract_size}\n"
                    f"  - 价格: ${price:,.2f}\n"
                    f"  - 订单返回filled: {order.get('filled')}\n"
                    f"  - 订单返回amount: {order.get('amount')}\n"
                    f"  - 订单状态: {order.get('status', 'unknown')}"
                )
                
                return order
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"下单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"下单失败: {error_str}", exc_info=True)
                raise
        
        return self.submit_request(
            RequestPriority.TRADE,
            _create_order
        )
    
    def create_order_native(
        self,
        symbol: str,
        side: str,
        amount: float,
        attach_algo_ords: Optional[list] = None
    ) -> dict:
        """
        使用OKX原生API直接下单（市价单）
        
        Args:
            symbol: 交易对，如 'ETH/USDT:USDT'
            side: 买卖方向，'buy'（买入）或 'sell'（卖出）
            amount: 数量（币的数量）
            attach_algo_ords: 止盈止损参数列表，格式：
                [{
                    'tpTriggerPx': '止盈触发价',
                    'tpTriggerPxType': 'last',  # 'last'/'index'/'mark'
                    'tpOrdPx': '-1',  # '-1'表示市价单
                    'slTriggerPx': '止损触发价',
                    'slTriggerPxType': 'last',
                    'slOrdPx': '-1'  # '-1'表示市价单
                }]
            
        Returns:
            dict: 订单信息，包含订单ID、状态等
        """
        def _create_order_native():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
                
                # 转换为OKX格式的交易对：ETH/USDT:USDT -> ETH-USDT-SWAP
                inst_id = symbol.replace('/', '-').replace(':USDT', '-SWAP')
                
                # 获取交易对的合约信息
                try:
                    market = self.exchange.market(symbol)
                    contract_size = market.get('contractSize', 0.1)  # 默认0.1（ETH）
                except:
                    # 如果获取失败，根据symbol判断
                    if 'ETH' in symbol.upper():
                        contract_size = 0.1
                    else:
                        contract_size = 1.0
                    logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
                
                # 将币的数量转换为合约张数
                if contract_size != 1.0 and contract_size > 0:
                    contracts = amount / contract_size
                    # 四舍五入到最小精度（合约张数通常是整数或0.1的倍数）
                    contracts = round(contracts, 1)
                    order_amount = contracts
                    logger.info(
                        f"[OKX原生API] 数量转换: 币数量={amount:.6f}, "
                        f"合约乘数={contract_size}, 合约张数={contracts:.1f}"
                    )
                else:
                    order_amount = amount
                    logger.info(f"[OKX原生API] 数量: {amount:.6f} (合约乘数=1，无需转换)")
                
                # 构建OKX API请求参数
                okx_params = {
                    'instId': inst_id,
                    'tdMode': 'cross',  # 全仓模式
                    'side': side,
                    'ordType': 'market',  # 市价单
                    'sz': str(order_amount),  # 合约张数
                    'posSide': 'long' if side == 'buy' else 'short'  # 持仓方向
                }
                
                # 添加杠杆
                okx_params['lever'] = str(settings.MAX_LEVERAGE)
                
                # 添加止盈止损参数（attachAlgoOrds）
                if attach_algo_ords:
                    okx_params['attachAlgoOrds'] = attach_algo_ords
                    logger.info(
                        f"[OKX原生API] 添加止盈止损参数: {len(attach_algo_ords)}个策略"
                    )
                
                logger.debug(f"[OKX原生API] 请求参数: {okx_params}")
                
                # 调用OKX原始API
                result = self.exchange.private_post_trade_order(okx_params)
                
                if result and result.get('code') == '0' and result.get('data'):
                    # 转换OKX响应格式为CCXT格式
                    order_data = result['data'][0]
                    order = {
                        'id': order_data.get('ordId', ''),
                        'clientOrderId': order_data.get('clOrdId', ''),
                        'symbol': symbol,
                        'type': 'market',
                        'side': side,
                        'amount': amount,  # 返回币的数量
                        'price': None,  # 市价单没有价格
                        'status': 'open',
                        'filled': 0,
                        'remaining': amount,
                        'info': order_data
                    }
                    
                    # 如果有attachAlgoOrds，记录策略订单ID
                    if attach_algo_ords and 'attachAlgoOrds' in order_data:
                        algo_orders = order_data.get('attachAlgoOrds', [])
                        if algo_orders:
                            logger.info(
                                f"[OKX原生API] 止盈止损策略订单已创建: "
                                f"{[algo.get('algoId', 'N/A') for algo in algo_orders]}"
                            )
                    
                    logger.info(
                        f"[OKX原生API] 订单创建成功: order_id={order['id']}, "
                        f"市价单, {side} {amount:.6f} {symbol.split('/')[0]}"
                    )
                    return order
                else:
                    error_msg = result.get('msg', '未知错误') if result else '返回结果为空'
                    error_code = result.get('code', 'N/A') if result else 'N/A'
                    raise Exception(f"OKX原生API下单失败: [{error_code}] {error_msg}")
                    
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"下单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"下单失败: {error_str}", exc_info=True)
                raise
        
        return self.submit_request(
            RequestPriority.TRADE,
            _create_order_native
        )
    
    def cancel_order(
        self,
        order_id: str,
        symbol: str
    ) -> dict:
        """
        取消订单（撤单）
        
        Args:
            order_id: 订单ID
            symbol: 交易对，如 'BTC/USDT:USDT'
            
        Returns:
            dict: 取消结果
        """
        def _cancel_order():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法撤单")
                
                # 调用CCXT取消订单
                result = self.exchange.cancel_order(order_id, symbol)
                
                logger.info(f"订单取消成功: order_id={order_id}, symbol={symbol}")
                
                return result
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"撤单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"撤单失败: {error_str}", exc_info=True)
                raise
        
        return self.submit_request(
            RequestPriority.TRADE,
            _cancel_order
        )
    
    def fetch_order(
        self,
        order_id: str,
        symbol: str
    ) -> dict:
        """
        查询订单状态
        
        Args:
            order_id: 订单ID
            symbol: 交易对，如 'BTC/USDT:USDT'
            
        Returns:
            dict: 订单信息，包含状态、成交价、成交数量等
        """
        def _fetch_order():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法查询订单")
                
                # 调用CCXT查询订单
                order = self.exchange.fetch_order(order_id, symbol)
                
                logger.debug(
                    f"订单查询成功: order_id={order_id}, "
                    f"status={order.get('status')}, "
                    f"filled={order.get('filled')}, "
                    f"average={order.get('average')}"
                )
                
                return order
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"查询订单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"查询订单失败: {error_str}", exc_info=True)
                raise
        
        return self.submit_request(
            RequestPriority.QUERY,
            _fetch_order
        )
    
    def fetch_open_orders(
        self,
        symbol: Optional[str] = None
    ) -> list:
        """
        查询所有未成交订单
        
        Args:
            symbol: 交易对（可选），如 'BTC/USDT:USDT'，不提供则查询所有交易对
            
        Returns:
            list: 未成交订单列表
        """
        def _fetch_open_orders():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法查询未成交订单")
                
                # 调用CCXT查询未成交订单
                query_symbol = symbol or settings.SYMBOL
                orders = self.exchange.fetch_open_orders(query_symbol)
                
                logger.debug(f"查询未成交订单成功: symbol={query_symbol}, count={len(orders)}")
                
                return orders
                
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"查询未成交订单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"查询未成交订单失败: {error_str}", exc_info=True)
                return []
        
        return self.submit_request(
            RequestPriority.QUERY,
            _fetch_open_orders
        )
    
    def amend_order(
        self,
        order_id: str,
        symbol: str,
        stop_loss_trigger_price: Optional[float] = None,
        stop_loss_order_price: Optional[str] = None,
        take_profit_trigger_price: Optional[float] = None,
        take_profit_order_price: Optional[str] = None
    ) -> dict:
        """
        修改订单的止盈止损设置
        使用 OKX 的修改订单 API: POST /api/v5/trade/amend-order
        
        Args:
            order_id: 订单ID（ordId 或 clOrdId）
            symbol: 交易对，如 'BTC/USDT:USDT'
            stop_loss_trigger_price: 止损触发价格
            stop_loss_order_price: 止损执行价格（'-1' 表示市价单）
            take_profit_trigger_price: 止盈触发价格
            take_profit_order_price: 止盈执行价格（'-1' 表示市价单）
            
        Returns:
            dict: 修改结果
        """
        def _amend_order():
            try:
                # 检查API密钥是否配置
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法修改订单")
                
                # 构建修改参数
                # 注意：OKX 要求如果设置了 slTriggerPx，必须同时设置 slOrdPx
                # 如果设置了 tpTriggerPx，必须同时设置 tpOrdPx
                amend_params = {}
                
                # 止损设置（必须同时设置触发价和执行价）
                if stop_loss_trigger_price is not None:
                    amend_params['slTriggerPx'] = str(stop_loss_trigger_price)
                    # 如果没有提供执行价，默认使用市价单（-1）
                    if stop_loss_order_price is None:
                        amend_params['slOrdPx'] = '-1'
                    else:
                        amend_params['slOrdPx'] = stop_loss_order_price
                
                # 止盈设置（必须同时设置触发价和执行价）
                if take_profit_trigger_price is not None:
                    amend_params['tpTriggerPx'] = str(take_profit_trigger_price)
                    # 如果没有提供执行价，默认使用市价单（-1）
                    if take_profit_order_price is None:
                        amend_params['tpOrdPx'] = '-1'
                    else:
                        amend_params['tpOrdPx'] = take_profit_order_price
                
                # 如果没有要修改的参数，直接返回
                if not amend_params:
                    logger.warning("没有要修改的止盈止损参数")
                    return {'success': False, 'message': '没有要修改的参数'}
                
                # 转换为OKX格式：BTC/USDT:USDT -> BTC-USDT-SWAP
                inst_id = symbol.replace('/', '-').replace(':USDT', '-SWAP')
                
                # 构建请求参数
                # 注意：OKX 修改订单 API 需要 instId, ordId 或 clOrdId，以及要修改的参数
                request_params = {
                    'instId': inst_id,
                    'ordId': order_id,  # 使用 ordId
                    'tdMode': 'cross',  # 全仓模式（与下单时保持一致）
                    **amend_params
                }
                
                logger.debug(f"修改订单参数: {request_params}")
                
                # 调用 OKX 的修改订单 API
                # CCXT 可能没有直接的 amend_order 方法，使用原始 API
                result = self.exchange.private_post_trade_amend_order(request_params)
                
                if result and 'code' in result:
                    if result['code'] == '0':
                        logger.info(
                            f"订单止盈止损修改成功: order_id={order_id}, "
                            f"止损触发价={stop_loss_trigger_price}, "
                            f"止盈触发价={take_profit_trigger_price}"
                        )
                        return {
                            'success': True,
                            'data': result.get('data', [])
                        }
                    else:
                        error_msg = result.get('msg', '未知错误')
                        logger.error(f"订单止盈止损修改失败: {error_msg}, result={result}")
                        raise Exception(f"修改订单失败: {error_msg}")
                else:
                    logger.error(f"订单止盈止损修改返回异常: {result}")
                    raise Exception("修改订单返回结果异常")
                    
            except Exception as e:
                error_str = str(e)
                # 检查是否是认证错误
                if ('401' in error_str or 'Unauthorized' in error_str or
                    'apiKey' in error_str or 'credential' in error_str.lower() or
                    'authentication' in error_str.lower()):
                    logger.error(f"修改订单失败（API密钥未配置或无效）: {error_str}")
                else:
                    logger.error(f"修改订单失败: {error_str}", exc_info=True)
                raise
        
        return self.submit_request(
            RequestPriority.TRADE,
            _amend_order
        )
