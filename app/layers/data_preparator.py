"""
数据准备器模块
负责为AI Agent准备标准化的市场数据
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database.connection import db
from app.database.klines import KlineRepository
from app.database.funding_rate import FundingRateRepository
from app.database.open_interest import OpenInterestRepository
from app.database.market_sentiment import MarketSentimentRepository
from app.database.order_book import OrderBookRepository
from app.database.etf_flow import ETFFlowRepository
from app.database.fear_greed import FearGreedRepository
from app.database.trades import TradeRepository
from app.utils.logger import logger


class DataPreparationError(Exception):
    """数据准备错误"""
    pass


class DataIncompleteError(DataPreparationError):
    """数据不完整错误"""
    pass


class DataStaleError(DataPreparationError):
    """数据过期错误"""
    pass


@dataclass
class TradingData:
    """交易数据对象"""

    # 市场概况
    symbol: str
    current_price: Decimal
    price_change_1h: Optional[Decimal]
    price_change_24h: Optional[Decimal]
    funding_rate: Optional[Decimal]
    open_interest: Optional[Decimal]

    # K线数据（最近的几根）
    klines_15m: List[Dict[str, Any]]  # 最近100根15分钟K线
    klines_4h: List[Dict[str, Any]]   # 最近50根4小时K线
    klines_1d: List[Dict[str, Any]]   # 最近30根日线K线

    # 情绪面数据
    market_sentiment: Optional[Dict[str, Any]]  # 市场情绪
    order_book: Optional[Dict[str, Any]]        # 盘口挂单
    etf_flow: Optional[Dict[str, Any]]          # ETF资金流
    fear_greed_index: Optional[Dict[str, Any]]  # 恐惧贪婪指数

    # 历史交易记录
    recent_trades: List[Dict[str, Any]]  # 最近20笔交易
    win_rate: float                      # 胜率
    consecutive_losses: int              # 连续亏损次数

    # 当前持仓（如果有）
    current_position: Optional[Dict[str, Any]]

    # 账户信息
    account_balance: Decimal  # 账户余额（USDT）

    # 数据时间戳
    data_timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'current_price': float(self.current_price),
            'price_change_1h': float(self.price_change_1h) if self.price_change_1h else None,
            'price_change_24h': float(self.price_change_24h) if self.price_change_24h else None,
            'funding_rate': float(self.funding_rate) if self.funding_rate else None,
            'open_interest': float(self.open_interest) if self.open_interest else None,
            'klines_15m': self.klines_15m,
            'klines_4h': self.klines_4h,
            'klines_1d': self.klines_1d,
            'market_sentiment': self.market_sentiment,
            'order_book': self.order_book,
            'etf_flow': self.etf_flow,
            'fear_greed_index': self.fear_greed_index,
            'recent_trades': self.recent_trades,
            'win_rate': self.win_rate,
            'consecutive_losses': self.consecutive_losses,
            'current_position': self.current_position,
            'account_balance': float(self.account_balance),
            'data_timestamp': self.data_timestamp.isoformat()
        }


class DataPreparator:
    """数据准备器"""

    def __init__(self, symbol: str):
        """
        初始化数据准备器

        Args:
            symbol: 币种名称（如：ETH）
        """
        self.symbol = symbol
        self.session = db.get_session()

    def __del__(self):
        """关闭数据库会话"""
        if hasattr(self, 'session') and self.session:
            self.session.close()

    def prepare_data(self, account_balance: Decimal = Decimal('10000')) -> TradingData:
        """
        准备完整的交易数据

        Args:
            account_balance: 账户余额（USDT）

        Returns:
            TradingData对象

        Raises:
            DataIncompleteError: 数据不完整
            DataStaleError: 数据过期
        """
        try:
            logger.info(f"开始准备 {self.symbol} 的交易数据...")

            # 1. 获取K线数据
            klines_15m = self._get_klines('15m', limit=100)
            klines_4h = self._get_klines('4h', limit=50)
            klines_1d = self._get_klines('1d', limit=30)

            if not klines_15m:
                raise DataIncompleteError(f"{self.symbol} 15分钟K线数据缺失")

            # 获取当前价格（从最新的15分钟K线）
            current_price = Decimal(str(klines_15m[0]['close']))

            # 2. 计算价格变化
            price_change_1h = self._calculate_price_change(klines_15m, periods=4)  # 4根15分钟=1小时
            price_change_24h = self._calculate_price_change(klines_15m, periods=96)  # 96根15分钟=24小时

            # 3. 获取资金费率
            funding_rate = self._get_latest_funding_rate()

            # 4. 获取未平仓合约
            open_interest = self._get_latest_open_interest()

            # 5. 获取情绪面数据
            market_sentiment = self._get_market_sentiment()
            order_book = self._get_order_book()
            etf_flow = self._get_etf_flow()
            fear_greed_index = self._get_fear_greed_index()

            # 6. 获取历史交易记录
            recent_trades = TradeRepository.get_recent_trades(self.session, self.symbol, limit=20)
            win_rate = TradeRepository.get_win_rate(self.session, self.symbol, limit=20)
            consecutive_losses = TradeRepository.get_consecutive_losses(self.session, self.symbol)

            # 7. 获取当前持仓
            current_position = self._get_current_position()

            # 8. 创建TradingData对象
            trading_data = TradingData(
                symbol=self.symbol,
                current_price=current_price,
                price_change_1h=price_change_1h,
                price_change_24h=price_change_24h,
                funding_rate=funding_rate,
                open_interest=open_interest,
                klines_15m=klines_15m,
                klines_4h=klines_4h,
                klines_1d=klines_1d,
                market_sentiment=market_sentiment,
                order_book=order_book,
                etf_flow=etf_flow,
                fear_greed_index=fear_greed_index,
                recent_trades=recent_trades,
                win_rate=win_rate,
                consecutive_losses=consecutive_losses,
                current_position=current_position,
                account_balance=account_balance,
                data_timestamp=datetime.now(timezone.utc)
            )

            logger.info(f"{self.symbol} 数据准备完成: 当前价格={current_price}, 胜率={win_rate:.1f}%")
            return trading_data

        except Exception as e:
            logger.error(f"准备 {self.symbol} 数据失败: {e}", exc_info=True)
            raise

    def _get_klines(self, timeframe: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取K线数据"""
        try:
            if timeframe == '15m':
                return KlineRepository.get_latest_klines_15m(self.session, self.symbol, limit=limit)
            elif timeframe == '4h':
                return KlineRepository.get_latest_klines_4h(self.session, self.symbol, limit=limit)
            elif timeframe == '1d':
                return KlineRepository.get_latest_klines_1d(self.session, self.symbol, limit=limit)
            else:
                raise ValueError(f"不支持的时间周期: {timeframe}")
        except Exception as e:
            logger.error(f"获取 {timeframe} K线失败: {e}")
            return []

    def _calculate_price_change(self, klines: List[Dict[str, Any]], periods: int) -> Optional[Decimal]:
        """计算价格变化百分比"""
        try:
            if len(klines) < periods:
                return None

            current_price = Decimal(str(klines[0]['close']))
            past_price = Decimal(str(klines[periods - 1]['close']))

            if past_price == 0:
                return None

            change = ((current_price - past_price) / past_price) * 100
            return change
        except Exception as e:
            logger.error(f"计算价格变化失败: {e}")
            return None

    def _get_latest_funding_rate(self) -> Optional[Decimal]:
        """获取最新资金费率"""
        try:
            rate = FundingRateRepository.get_latest_funding_rate(self.session, self.symbol)
            if rate:
                return Decimal(str(rate['funding_rate']))
            return None
        except Exception as e:
            logger.error(f"获取资金费率失败: {e}")
            return None

    def _get_latest_open_interest(self) -> Optional[Decimal]:
        """获取最新未平仓合约"""
        try:
            oi = OpenInterestRepository.get_latest_open_interest(self.session, self.symbol)
            if oi:
                return Decimal(str(oi['open_interest']))
            return None
        except Exception as e:
            logger.error(f"获取未平仓合约失败: {e}")
            return None

    def _get_market_sentiment(self) -> Optional[Dict[str, Any]]:
        """获取市场情绪"""
        try:
            return MarketSentimentRepository.get_latest_sentiment(self.session, self.symbol)
        except Exception as e:
            logger.error(f"获取市场情绪失败: {e}")
            return None

    def _get_order_book(self) -> Optional[Dict[str, Any]]:
        """获取盘口挂单"""
        try:
            return OrderBookRepository.get_latest_distribution(self.session, self.symbol)
        except Exception as e:
            logger.error(f"获取盘口挂单失败: {e}")
            return None

    def _get_etf_flow(self) -> Optional[Dict[str, Any]]:
        """获取ETF资金流"""
        try:
            # ETF资金流是BTC的，不区分币种
            return ETFFlowRepository.get_latest_flow(self.session)
        except Exception as e:
            logger.error(f"获取ETF资金流失败: {e}")
            return None

    def _get_fear_greed_index(self) -> Optional[Dict[str, Any]]:
        """获取恐惧贪婪指数"""
        try:
            # 恐惧贪婪指数是全市场的，不区分币种
            return FearGreedRepository.get_latest_index(self.session)
        except Exception as e:
            logger.error(f"获取恐惧贪婪指数失败: {e}")
            return None

    def _get_current_position(self) -> Optional[Dict[str, Any]]:
        """获取当前持仓"""
        try:
            sql = text("SELECT * FROM positions WHERE symbol = :symbol")
            result = self.session.execute(sql, {'symbol': self.symbol}).fetchone()
            return dict(result._mapping) if result else None
        except Exception as e:
            logger.error(f"获取当前持仓失败: {e}")
            return None

    def format_for_ai_prompt(self, trading_data: TradingData) -> str:
        """
        格式化数据为AI提示词

        Args:
            trading_data: 交易数据对象

        Returns:
            格式化的提示词字符串
        """
        # 获取最新K线数据
        latest_15m = trading_data.klines_15m[0] if trading_data.klines_15m else {}
        latest_4h = trading_data.klines_4h[0] if trading_data.klines_4h else {}
        latest_1d = trading_data.klines_1d[0] if trading_data.klines_1d else {}

        # 构建提示词
        prompt = f"""【市场概况】
- 当前价格：${trading_data.current_price:.2f}
- 1小时涨跌：{trading_data.price_change_1h:+.2f}% (如果有)
- 24小时涨跌：{trading_data.price_change_24h:+.2f}% (如果有)
- 资金费率：{float(trading_data.funding_rate):.4f}% (如果有)
- 持仓量：{float(trading_data.open_interest):,.0f} {trading_data.symbol} (如果有)

【技术面分析】
【15分钟周期】
- RSI：{latest_15m.get('rsi_7', 'N/A')}
- MACD：{'金叉向上' if latest_15m.get('histogram', 0) > 0 else '死叉向下'}
- 布林带位置：{self._calculate_bb_position(latest_15m):.1f}%
- 波动率比率：{latest_15m.get('atr_14', 'N/A')}
- EMA9: ${latest_15m.get('ema_9', 'N/A')}
- EMA21: ${latest_15m.get('ema_21', 'N/A')}
- EMA55: ${latest_15m.get('ema_55', 'N/A')}

【4小时周期】
- RSI：{latest_4h.get('rsi_14', 'N/A')}
- 布林带位置：{self._calculate_bb_position(latest_4h):.1f}%
- 趋势：{self._determine_trend(latest_4h)}

【日线周期】
- 趋势：{self._determine_trend(latest_1d)}

【情绪面分析】
{self._format_sentiment_data(trading_data)}

【历史交易记录】
- 最近20笔交易：盈利{sum(1 for t in trading_data.recent_trades if t.get('pnl', 0) > 0)}笔，亏损{sum(1 for t in trading_data.recent_trades if t.get('pnl', 0) < 0)}笔
- 胜率：{trading_data.win_rate:.1f}%
- 连续亏损次数：{trading_data.consecutive_losses}次

【当前持仓状态】
{self._format_position_data(trading_data.current_position)}

【账户余额】
- 账户余额：{float(trading_data.account_balance):,.2f} USDT
"""
        return prompt

    def _calculate_bb_position(self, kline: Dict[str, Any]) -> float:
        """计算价格在布林带中的位置百分比"""
        try:
            close = float(kline.get('close', 0))
            bb_upper = float(kline.get('bb_upper', 0))
            bb_lower = float(kline.get('bb_lower', 0))

            if bb_upper == 0 or bb_lower == 0 or bb_upper == bb_lower:
                return 50.0

            position = ((close - bb_lower) / (bb_upper - bb_lower)) * 100
            return max(0, min(100, position))
        except:
            return 50.0

    def _determine_trend(self, kline: Dict[str, Any]) -> str:
        """判断趋势"""
        try:
            close = float(kline.get('close', 0))
            ema_9 = float(kline.get('ema_9', 0))
            ema_21 = float(kline.get('ema_21', 0))

            if close > ema_9 > ema_21:
                return "上升"
            elif close < ema_9 < ema_21:
                return "下降"
            else:
                return "震荡"
        except:
            return "未知"

    def _format_sentiment_data(self, trading_data: TradingData) -> str:
        """格式化情绪面数据"""
        sentiment_text = ""

        if trading_data.market_sentiment:
            ms = trading_data.market_sentiment
            sentiment_text += f"- 市场情绪：多空比 {ms.get('long_ratio', 'N/A')}:{ms.get('short_ratio', 'N/A')}\n"

        if trading_data.order_book:
            ob = trading_data.order_book
            sentiment_text += f"- 盘口挂单：买卖比 {ob.get('buy_sell_ratio', 'N/A')}\n"

        if trading_data.etf_flow:
            etf = trading_data.etf_flow
            sentiment_text += f"- ETF资金流：当日净流入 {etf.get('net_flow', 'N/A')} 万美元\n"

        if trading_data.fear_greed_index:
            fg = trading_data.fear_greed_index
            sentiment_text += f"- 恐惧贪婪指数：{fg.get('value', 'N/A')} ({fg.get('classification', 'N/A')})\n"

        return sentiment_text if sentiment_text else "- 暂无情绪面数据\n"

    def _format_position_data(self, position: Optional[Dict[str, Any]]) -> str:
        """格式化持仓数据"""
        if not position:
            return "- 当前无持仓"

        return f"""- 持仓方向：{position.get('side', 'N/A')}
- 入场价格：${position.get('entry_price', 'N/A')}
- 当前价格：${position.get('current_price', 'N/A')}
- 未实现盈亏：${position.get('unrealized_pnl', 'N/A')} ({position.get('unrealized_pnl_percentage', 'N/A')}%)
- 止损价格：${position.get('stop_loss', 'N/A')}
- 止盈价格：${position.get('take_profit', 'N/A')}"""
