"""
CoinGlass API客户端
用于获取市场情绪数据、未平仓合约、ETF资金流、恐惧贪婪指数等
"""
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from app.config import Settings  # Settings类，用于类型提示
from app.utils.logger import logger


class CoinGlassClient:
    """CoinGlass API客户端"""
    
    def __init__(self, settings: Settings):
        """
        初始化CoinGlass客户端
        
        Args:
            settings: 应用配置
        """
        self.base_url = settings.COINGLASS_BASE_URL
        self.api_key = settings.COINGLASS_API_KEY
        self.headers = {
            'accept': 'application/json'
        }
        if self.api_key:
            self.headers['CG-API-KEY'] = self.api_key
    
    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        发送API请求
        
        Args:
            endpoint: API端点
            params: 请求参数
            
        Returns:
            API响应数据，失败返回None
        """
        try:
            url = f"{self.base_url}{endpoint}"
            logger.debug(f"CoinGlass API请求: {url}, 参数: {params}")
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # 记录API响应的详细信息
            logger.debug(f"CoinGlass API响应 - endpoint: {endpoint}, code: {data.get('code')}, "
                        f"msg: {data.get('msg')}, data_type: {type(data.get('data'))}, "
                        f"data_length: {len(data.get('data')) if isinstance(data.get('data'), list) else 'N/A'}")
            
            if data.get('code') == '0':
                result_data = data.get('data')
                
                # 对于恐惧贪婪指数接口，记录更详细的信息
                if '/fear-greed' in endpoint:
                    logger.info(f"恐惧贪婪指数API响应 - result_data类型: {type(result_data)}")
                    if isinstance(result_data, dict):
                        logger.info(f"恐惧贪婪指数API响应 - result_data字段: {list(result_data.keys())}")
                    elif isinstance(result_data, list):
                        logger.info(f"恐惧贪婪指数API响应 - result_data是列表，长度: {len(result_data)}")
                        if len(result_data) > 0:
                            logger.info(f"恐惧贪婪指数API响应 - 第一条数据: {result_data[0]}")
                
                # 如果是列表，记录前几条数据的结构
                if isinstance(result_data, list) and len(result_data) > 0:
                    logger.debug(f"API返回数据示例（第一条）: {result_data[0]}")
                elif result_data is None:
                    logger.warning(f"API返回code=0但data为None - endpoint: {endpoint}")
                elif isinstance(result_data, dict):
                    logger.debug(f"API返回数据是字典，字段: {list(result_data.keys())}")
                return result_data
            else:
                error_msg = data.get('msg', 'Unknown error')
                error_code = data.get('code')
                
                # 特殊处理"Upgrade plan"错误
                if 'upgrade' in error_msg.lower() or error_code == '400':
                    logger.warning(f"CoinGlass API需要升级计划 - endpoint: {endpoint}, "
                                 f"code: {error_code}, msg: {error_msg}")
                else:
                    logger.error(f"CoinGlass API错误: {error_msg}, "
                               f"code: {error_code}, endpoint: {endpoint}, 响应: {data}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"CoinGlass API请求失败: {e}, URL: {url if 'url' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"CoinGlass API处理失败: {e}, endpoint: {endpoint}", exc_info=True)
            return None
    
    def get_open_interest_history(
        self,
        symbol: str,
        exchange: str = "OKX",
        interval: str = "4h",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> Optional[List[Dict]]:
        """
        获取未平仓合约历史数据
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            exchange: 交易所名称，默认OKX
            interval: 时间间隔，默认4h（支持：1m, 5m, 15m, 30m, 1h, 4h, 12h, 1d等）
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            
        Returns:
            未平仓合约数据列表
        """
        params = {
            'symbol': symbol,
            'exchange': exchange,
            'interval': interval,
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('/api/futures/open-interest/aggregated-history', params)
    
    def get_long_short_ratio_history(
        self,
        symbol: str,
        exchange: str = "Binance",
        interval: str = "4h",
        limit: int = 1000,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> Optional[List[Dict]]:
        """
        获取多空持仓人数比历史数据
        
        Args:
            symbol: 币种名称（BTC, ETH等），会自动转换为BTCUSDT、ETHUSDT格式
            exchange: 交易所名称，默认Binance
            interval: 时间间隔，默认4h
            limit: 返回数量限制，默认1000
            start_time: 开始时间戳（毫秒）
            end_time: 结束时间戳（毫秒）
            
        Returns:
            多空比数据列表
        """
        # 将BTC/ETH转换为BTCUSDT/ETHUSDT格式
        symbol_upper = symbol.upper()
        if symbol_upper.endswith('USDT'):
            symbol_param = symbol_upper
        else:
            symbol_param = f"{symbol_upper}USDT"
        
        params = {
            'exchange': exchange,
            'symbol': symbol_param,
            'interval': interval,
            'limit': limit,
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('/api/futures/global-long-short-account-ratio/history', params)
    
    def get_etf_flow_history(
        self,
        symbol: str
    ) -> Optional[List[Dict]]:
        """
        获取ETF净资产和资金流历史数据
        
        Args:
            symbol: 币种名称（BTC或ETH）
            
        Returns:
            ETF净资产和资金流数据列表，包含：
            - net_assets_usd: 净资产总额（USD）
            - change_usd: 当日资金变化（USD）
            - timestamp: 日期（时间戳，单位毫秒）
            - price_usd: 当日币种价格（USD）
        """
        if symbol.upper() == 'BTC':
            endpoint = '/api/etf/bitcoin/net-assets/history'
        elif symbol.upper() == 'ETH':
            endpoint = '/api/etf/ethereum/net-assets/history'
        else:
            logger.error(f"不支持的ETF币种: {symbol}")
            return None
        
        return self._request(endpoint)
    
    def get_fear_greed_history(
        self,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> Optional[Dict]:
        """
        获取恐惧贪婪指数历史数据
        
        Args:
            start_time: 开始时间戳（毫秒，可选）
            end_time: 结束时间戳（毫秒，可选）
            
        Returns:
            恐惧贪婪指数数据（包含data_list, price_list, time_list）
        """
        params = {}
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('/api/index/fear-greed-history', params)
    
    def get_liquidation_history(
        self,
        symbol: str,
        exchange_list: str = "OKX",
        interval: str = "4h",
        limit: int = 1000,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> Optional[List[Dict]]:
        """
        获取币种爆仓历史数据
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            exchange_list: 交易所列表，以逗号分隔（例如："Binance, OKX, Bybit"），默认OKX
            interval: 时间间隔，默认4h（支持：1m、3m、5m、15m、30m、1h、4h、6h、8h、12h、1d、1w）
            limit: 返回数据条数，默认1000，最大1000
            start_time: 开始时间戳（毫秒，可选）
            end_time: 结束时间戳（毫秒，可选）
            
        Returns:
            爆仓历史数据列表，包含：
            - aggregated_long_liquidation_usd: 聚合多单爆仓金额（美元）
            - aggregated_short_liquidation_usd: 聚合空单爆仓金额（美元）
            - time: 时间戳（毫秒）
        """
        params = {
            'symbol': symbol.upper(),
            'exchange_list': exchange_list,
            'interval': interval,
            'limit': min(limit, 1000)  # 限制最大值为1000
        }
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        return self._request('/api/futures/liquidation/aggregated-history', params)

