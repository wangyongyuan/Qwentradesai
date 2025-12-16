"""
配置管理模块
从数据库读取配置，如果数据库不可用则从环境变量加载
"""
from pydantic_settings import BaseSettings
from typing import Optional, List, Any
import logging


class DatabaseSettings(BaseSettings):
    """数据库连接配置 - 仅用于初始化数据库连接，从环境变量读取"""
    
    DATABASE_URL: str = "postgresql://qwentradeai:qwentradeai@45.197.144.57:5432/qwentradeai"
    """PostgreSQL数据库连接URL，格式：postgresql://用户名:密码@主机:端口/数据库名"""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


class Settings:
    """应用配置类 - 所有配置项从数据库读取，如果数据库不可用则使用默认值"""
    
    def __init__(self):
        """初始化配置，从数据库读取"""
        # 首先从环境变量读取数据库连接URL（用于连接数据库）
        db_settings = DatabaseSettings()
        self._database_url = db_settings.DATABASE_URL
        
        # 初始化数据库连接和配置管理器
        self._db = None
        self._config_manager = None
        self._init_config_manager()
    
    def _init_config_manager(self):
        """初始化配置管理器"""
        # 使用基础logging，避免循环导入
        _logger = logging.getLogger("qwentradeai")
        try:
            from app.database.connection import Database
            from app.database.config_manager import ConfigManager
            self._db = Database(database_url=self._database_url)
            self._config_manager = ConfigManager(self._db)
            _logger.info("配置已从数据库加载")
        except Exception as e:
            _logger.warning(f"无法从数据库加载配置: {e}，将使用默认值")
            self._config_manager = None
    
    def _get(self, key: str, default: Any = None, value_type: str = 'string') -> Any:
        """从数据库获取配置值，如果不存在则返回默认值"""
        if self._config_manager:
            if value_type == 'int':
                return self._config_manager.get_int(key, default if isinstance(default, int) else 0)
            elif value_type == 'float':
                return self._config_manager.get_float(key, default if isinstance(default, float) else 0.0)
            elif value_type == 'bool':
                return self._config_manager.get_bool(key, default if isinstance(default, bool) else False)
            else:
                return self._config_manager.get_string(key, default if isinstance(default, str) else '')
        return default
    
    # ============================================
    # 应用基础配置
    # ============================================
    @property
    def APP_NAME(self) -> str:
        """应用名称，用于日志和API文档"""
        return self._get('APP_NAME', 'QwenTradeAI', 'string')
    
    @property
    def APP_VERSION(self) -> str:
        """应用版本号"""
        return self._get('APP_VERSION', '2.0', 'string')
    
    @property
    def DEBUG(self) -> bool:
        """调试模式开关，True时输出更详细的日志信息"""
        return self._get('DEBUG', False, 'bool')
    
    # ============================================
    # 数据库配置
    # ============================================
    @property
    def DATABASE_URL(self) -> str:
        """PostgreSQL数据库连接URL"""
        return self._database_url
    
    # ============================================
    # 交易所配置（OKX）
    # ============================================
    @property
    def EXCHANGE_NAME(self) -> str:
        """交易所名称，使用CCXT库支持的交易所名称，当前固定为okx"""
        return self._get('EXCHANGE_NAME', 'okx', 'string')
    
    @property
    def EXCHANGE_API_KEY(self) -> Optional[str]:
        """OKX API密钥（可选，如果不需要交易功能可以不填），从OKX官网申请"""
        value = self._get('EXCHANGE_API_KEY', '', 'string')
        return value if value else None
    
    @property
    def EXCHANGE_SECRET(self) -> Optional[str]:
        """OKX API密钥对应的Secret（可选，如果不需要交易功能可以不填），从OKX官网申请"""
        value = self._get('EXCHANGE_SECRET', '', 'string')
        return value if value else None
    
    @property
    def EXCHANGE_PASSPHRASE(self) -> Optional[str]:
        """OKX API密钥对应的Passphrase（可选，如果不需要交易功能可以不填），创建API密钥时设置的密码"""
        value = self._get('EXCHANGE_PASSPHRASE', '', 'string')
        return value if value else None
    
    @property
    def EXCHANGE_SANDBOX(self) -> bool:
        """是否使用交易所沙箱环境，True=测试环境（模拟盘），False=生产环境（真实盘）"""
        return self._get('EXCHANGE_SANDBOX', True, 'bool')
    
    # ============================================
    # CoinGlass API配置（可选）
    # ============================================
    @property
    def COINGLASS_API_KEY(self) -> Optional[str]:
        """CoinGlass API密钥（可选），用于获取市场情绪数据、未平仓合约、ETF资金流、恐惧贪婪指数等"""
        value = self._get('COINGLASS_API_KEY', '95c31ba79d054646b2ca68c23bfb4839', 'string')
        return value if value else None
    
    @property
    def COINGLASS_BASE_URL(self) -> str:
        """CoinGlass API基础URL，通常不需要修改"""
        return self._get('COINGLASS_BASE_URL', 'https://open-api-v4.coinglass.com', 'string')
    
    # ============================================
    # 交易配置（仅用于数据同步）
    # ============================================
    @property
    def SYMBOL(self) -> str:
        """默认交易币种（CCXT格式），格式：币种/USDT:USDT（永续合约）"""
        return self._get('SYMBOL', 'ETH/USDT:USDT', 'string')
    
    @property
    def TRADING_SYMBOLS(self) -> str:
        """交易币种列表（逗号分隔），币种名称如BTC、ETH，系统会为每个币种创建独立的同步线程。当前仅支持ETH"""
        return self._get('TRADING_SYMBOLS', 'ETH', 'string')
    
    # ============================================
    # 技术指标配置
    # ============================================
    # RSI（相对强弱指标）配置
    @property
    def RSI_15M_PERIOD(self) -> int:
        """15分钟K线RSI计算周期，用于短期超买超卖判断"""
        return self._get('RSI_15M_PERIOD', 7, 'int')
    
    @property
    def RSI_15M_OVERSOLD(self) -> float:
        """15分钟RSI超卖阈值，低于此值认为超卖（可能反弹）"""
        return self._get('RSI_15M_OVERSOLD', 20.0, 'float')
    
    @property
    def RSI_15M_OVERBOUGHT(self) -> float:
        """15分钟RSI超买阈值，高于此值认为超买（可能回调）"""
        return self._get('RSI_15M_OVERBOUGHT', 80.0, 'float')
    
    @property
    def RSI_4H_PERIOD(self) -> int:
        """4小时K线RSI计算周期，用于中期超买超卖判断"""
        return self._get('RSI_4H_PERIOD', 14, 'int')
    
    @property
    def RSI_4H_OVERSOLD(self) -> float:
        """4小时RSI超卖阈值，低于此值认为超卖"""
        return self._get('RSI_4H_OVERSOLD', 30.0, 'float')
    
    @property
    def RSI_4H_OVERBOUGHT(self) -> float:
        """4小时RSI超买阈值，高于此值认为超买"""
        return self._get('RSI_4H_OVERBOUGHT', 70.0, 'float')
    
    # MACD（指数平滑异同移动平均线）配置
    @property
    def MACD_15M_FAST(self) -> int:
        """15分钟K线MACD快线周期（EMA快线）"""
        return self._get('MACD_15M_FAST', 8, 'int')
    
    @property
    def MACD_15M_SLOW(self) -> int:
        """15分钟K线MACD慢线周期（EMA慢线）"""
        return self._get('MACD_15M_SLOW', 17, 'int')
    
    @property
    def MACD_15M_SIGNAL(self) -> int:
        """15分钟K线MACD信号线周期（MACD线的EMA平滑）"""
        return self._get('MACD_15M_SIGNAL', 9, 'int')
    
    @property
    def MACD_4H_FAST(self) -> int:
        """4小时K线MACD快线周期（EMA快线）"""
        return self._get('MACD_4H_FAST', 12, 'int')
    
    @property
    def MACD_4H_SLOW(self) -> int:
        """4小时K线MACD慢线周期（EMA慢线）"""
        return self._get('MACD_4H_SLOW', 26, 'int')
    
    @property
    def MACD_4H_SIGNAL(self) -> int:
        """4小时K线MACD信号线周期（MACD线的EMA平滑）"""
        return self._get('MACD_4H_SIGNAL', 9, 'int')
    
    # EMA（指数移动平均线）配置
    @property
    def EMA_SHORT(self) -> int:
        """EMA短期周期，用于短期趋势判断"""
        return self._get('EMA_SHORT', 9, 'int')
    
    @property
    def EMA_MID(self) -> int:
        """EMA中期周期，用于中期趋势判断"""
        return self._get('EMA_MID', 21, 'int')
    
    @property
    def EMA_LONG(self) -> int:
        """EMA长期周期，仅用于15分钟K线，用于长期趋势判断"""
        return self._get('EMA_LONG', 55, 'int')
    
    # 布林带（Bollinger Bands）配置
    @property
    def BB_PERIOD(self) -> int:
        """布林带周期，中轨移动平均线的周期"""
        return self._get('BB_PERIOD', 20, 'int')
    
    @property
    def BB_STD(self) -> float:
        """布林带标准差倍数，上轨=中轨+倍数*标准差，下轨=中轨-倍数*标准差"""
        return self._get('BB_STD', 2.0, 'float')
    
    # ATR（平均真实波幅）配置
    @property
    def ATR_15M_PERIOD(self) -> int:
        """15分钟K线ATR计算周期，用于衡量市场波动性"""
        return self._get('ATR_15M_PERIOD', 14, 'int')
    
    # OBV（能量潮指标）配置
    @property
    def OBV_EMA_SMOOTH(self) -> int:
        """OBV平滑周期，15分钟K线使用EMA9对OBV进行平滑处理"""
        return self._get('OBV_EMA_SMOOTH', 9, 'int')
    
    # ============================================
    # K线历史数据同步配置
    # ============================================
    @property
    def KLINE_15M_START_DAYS(self) -> int:
        """15分钟K线初始同步天数，系统启动时从多少天前开始同步历史数据"""
        return self._get('KLINE_15M_START_DAYS', 30, 'int')
    
    @property
    def KLINE_4H_START_DAYS(self) -> int:
        """4小时K线初始同步天数，系统启动时从多少天前开始同步历史数据"""
        return self._get('KLINE_4H_START_DAYS', 180, 'int')
    
    @property
    def KLINE_1D_START_DAYS(self) -> int:
        """日线K线初始同步天数，系统启动时从多少天前开始同步历史数据"""
        return self._get('KLINE_1D_START_DAYS', 600, 'int')
    
    # ============================================
    # 资金费率同步配置
    # ============================================
    @property
    def FUNDING_RATE_START_DAYS(self) -> int:
        """资金费率初始同步天数，系统启动时从多少天前开始同步历史数据（每8小时一条记录）"""
        return self._get('FUNDING_RATE_START_DAYS', 30, 'int')
    
    # ============================================
    # API管理器配置
    # ============================================
    @property
    def API_RATE_LIMIT(self) -> int:
        """API请求速率限制：每时间窗口内允许的最大请求次数（默认：每2秒10次）"""
        return self._get('API_RATE_LIMIT', 10, 'int')
    
    @property
    def API_RATE_WINDOW(self) -> float:
        """API限流时间窗口（秒），与API_RATE_LIMIT配合使用"""
        return self._get('API_RATE_WINDOW', 2.0, 'float')
    
    @property
    def API_MIN_INTERVAL(self) -> float:
        """API请求最小间隔时间（秒），防止请求过于频繁，默认200毫秒"""
        return self._get('API_MIN_INTERVAL', 0.2, 'float')
    
    @property
    def API_REQUEST_TIMEOUT(self) -> int:
        """API请求超时时间（秒），超过此时间无响应则认为请求失败"""
        return self._get('API_REQUEST_TIMEOUT', 30, 'int')
    
    @property
    def API_MAX_RETRIES(self) -> int:
        """API请求最大重试次数，请求失败时自动重试的次数"""
        return self._get('API_MAX_RETRIES', 3, 'int')
    
    # ============================================
    # WebSocket配置
    # ============================================
    @property
    def WS_URL(self) -> str:
        """WebSocket连接URL（公共频道），OKX交易所的WebSocket地址（会根据EXCHANGE_SANDBOX自动切换）"""
        return self.get_ws_url()
    
    @property
    def WS_PRIVATE_URL(self) -> str:
        """WebSocket连接URL（私人频道），用于订阅持仓等私人数据（会根据EXCHANGE_SANDBOX自动切换）"""
        return self.get_ws_private_url()
    
    def get_ws_url(self) -> str:
        """获取WebSocket公共频道URL（根据EXCHANGE_SANDBOX自动选择）"""
        if self.EXCHANGE_SANDBOX:
            return "wss://wspap.okx.com:8443/ws/v5/public"
        else:
            return "wss://ws.okx.com:8443/ws/v5/public"
    
    def get_ws_private_url(self) -> str:
        """获取WebSocket私有频道URL（根据EXCHANGE_SANDBOX自动选择）"""
        if self.EXCHANGE_SANDBOX:
            return "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            return "wss://ws.okx.com:8443/ws/v5/private"
    
    @property
    def WS_RECONNECT_INTERVAL(self) -> int:
        """WebSocket重连间隔（秒），连接断开后每多少秒尝试重连"""
        return self._get('WS_RECONNECT_INTERVAL', 5, 'int')
    
    @property
    def WS_HEARTBEAT_INTERVAL(self) -> int:
        """WebSocket心跳间隔（秒），N < 30，每次收到消息后重置定时器，N秒内没收到消息则发送ping"""
        return self._get('WS_HEARTBEAT_INTERVAL', 20, 'int')
    
    @property
    def WS_PING_TIMEOUT(self) -> int:
        """WebSocket ping超时时间（秒），发送ping后等待pong的最大时间，超时则重连"""
        return self._get('WS_PING_TIMEOUT', 5, 'int')
    
    @property
    def WS_CONNECT_TIMEOUT(self) -> int:
        """WebSocket连接超时时间（秒），连接后30秒内必须完成登录和订阅"""
        return self._get('WS_CONNECT_TIMEOUT', 30, 'int')
    
    @property
    def WS_SUBSCRIBE_TIMEOUT(self) -> int:
        """WebSocket订阅超时时间（秒），订阅后30秒内必须收到数据"""
        return self._get('WS_SUBSCRIBE_TIMEOUT', 30, 'int')
    
    @property
    def WS_PRICE_TIMEOUT(self) -> int:
        """WebSocket价格超时时间（秒），超过此时间未收到价格更新则认为连接异常"""
        return self._get('WS_PRICE_TIMEOUT', 30, 'int')
    
    @property
    def WS_QUEUE_MAXSIZE(self) -> int:
        """WebSocket价格队列最大长度，超过此长度会丢弃旧数据"""
        return self._get('WS_QUEUE_MAXSIZE', 100, 'int')
    
    @property
    def WS_SUBSCRIBE_POSITIONS(self) -> bool:
        """是否订阅持仓频道（已废弃，持仓改为从REST API获取）"""
        return self._get('WS_SUBSCRIBE_POSITIONS', False, 'bool')
    
    @property
    def WS_SSL_VERIFY(self) -> bool:
        """是否验证SSL证书，True=验证（推荐），False=不验证（仅用于测试环境）"""
        return self._get('WS_SSL_VERIFY', True, 'bool')
    
    @property
    def WS_SSL_CERT_PATH(self) -> Optional[str]:
        """SSL证书文件路径（可选），如果为None则使用系统默认证书，如果WS_SSL_VERIFY=False则忽略此选项"""
        value = self._get('WS_SSL_CERT_PATH', '', 'string')
        return value if value else None
    
    # ============================================
    # 日志配置
    # ============================================
    @property
    def LOG_LEVEL(self) -> str:
        """日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL"""
        return self._get('LOG_LEVEL', 'INFO', 'string')
    
    @property
    def LOG_FILE(self) -> str:
        """日志文件路径，日志会写入此文件"""
        return self._get('LOG_FILE', 'logs/qwentradeai.log', 'string')
    
    @property
    def LOG_MAX_BYTES(self) -> int:
        """单个日志文件最大大小（字节），默认10MB，超过此大小会轮转"""
        return self._get('LOG_MAX_BYTES', 10485760, 'int')
    
    @property
    def LOG_BACKUP_COUNT(self) -> int:
        """日志文件备份数量，保留多少个历史日志文件"""
        return self._get('LOG_BACKUP_COUNT', 5, 'int')
    
    # ============================================
    # 市场检测器配置
    # ============================================
    # 环境层参数
    @property
    def DETECTOR_EMA_TREND_PERIOD(self) -> int:
        """市场检测器：用于趋势判断的EMA周期（环境层），默认55"""
        return self._get('DETECTOR_EMA_TREND_PERIOD', 55, 'int')
    
    @property
    def DETECTOR_BB_WIDTH_THRESHOLD(self) -> float:
        """市场检测器：布林带宽度阈值（相对于20根平均值的倍数），低于此值认为市场不活跃，默认0.5"""
        return self._get('DETECTOR_BB_WIDTH_THRESHOLD', 0.5, 'float')
    
    # 触发层参数
    @property
    def DETECTOR_RSI_LONG_THRESHOLD(self) -> float:
        """市场检测器：做多信号RSI上限（RSI低于此值才允许做多，防止极端过热），默认80.0"""
        return self._get('DETECTOR_RSI_LONG_THRESHOLD', 80.0, 'float')
    
    @property
    def DETECTOR_RSI_SHORT_THRESHOLD(self) -> float:
        """市场检测器：做空信号RSI下限（RSI高于此值才允许做空，防止极端超卖），默认20.0"""
        return self._get('DETECTOR_RSI_SHORT_THRESHOLD', 20.0, 'float')
    
    @property
    def DETECTOR_RSI_DOUBLE_POSITION_LONG(self) -> float:
        """市场检测器：做多时RSI低于此值加倍仓位（更好的盈亏比），默认50.0"""
        return self._get('DETECTOR_RSI_DOUBLE_POSITION_LONG', 50.0, 'float')
    
    @property
    def DETECTOR_RSI_DOUBLE_POSITION_SHORT(self) -> float:
        """市场检测器：做空时RSI高于此值加倍仓位（更好的盈亏比），默认50.0"""
        return self._get('DETECTOR_RSI_DOUBLE_POSITION_SHORT', 50.0, 'float')
    
    # 确认层参数
    @property
    def DETECTOR_VOLUME_STD_MULTIPLIER(self) -> float:
        """市场检测器：成交量确认阈值（平均值 + 此倍数 × 标准差），降低此值可增加信号数量，默认1.5"""
        return self._get('DETECTOR_VOLUME_STD_MULTIPLIER', 1.5, 'float')
    
    # 数据量参数
    @property
    def DETECTOR_KLINE_15M_COUNT(self) -> int:
        """市场检测器：使用的15分钟K线数量，默认100"""
        return self._get('DETECTOR_KLINE_15M_COUNT', 100, 'int')
    
    @property
    def DETECTOR_KLINE_4H_COUNT(self) -> int:
        """市场检测器：使用的4小时K线数量，默认60"""
        return self._get('DETECTOR_KLINE_4H_COUNT', 60, 'int')
    
    # 其他参数
    @property
    def DETECTOR_ENABLE_MULTI_TF(self) -> bool:
        """市场检测器：是否启用多时间框架确认（15m和4h共振加分），默认true"""
        return self._get('DETECTOR_ENABLE_MULTI_TF', True, 'bool')
    
    @property
    def DETECTOR_SIGNAL_EXPIRE_HOURS(self) -> int:
        """市场检测器：信号有效期（小时），超过此时间信号自动过期，默认4"""
        return self._get('DETECTOR_SIGNAL_EXPIRE_HOURS', 4, 'int')
    
    # ============================================
    # 报警通知配置（可选）
    # ============================================
    @property
    def NOTIFICATION_ENABLED(self) -> bool:
        """是否启用报警通知，True=启用，False=禁用"""
        return self._get('NOTIFICATION_ENABLED', False, 'bool')
    
    @property
    def TELEGRAM_BOT_TOKEN(self) -> Optional[str]:
        """Telegram机器人Token（可选），用于发送Telegram消息通知"""
        value = self._get('TELEGRAM_BOT_TOKEN', '', 'string')
        return value if value else None
    
    @property
    def TELEGRAM_CHAT_ID(self) -> Optional[str]:
        """Telegram聊天ID（可选），接收通知的聊天ID"""
        value = self._get('TELEGRAM_CHAT_ID', '', 'string')
        return value if value else None
    
    @property
    def SERVER_CHAN_KEY(self) -> Optional[str]:
        """Server酱API Key（可选），用于发送微信消息通知"""
        value = self._get('SERVER_CHAN_KEY', '', 'string')
        return value if value else None
    
    def get_trading_symbols(self) -> List[str]:
        """获取交易币种列表"""
        symbols_str = self.TRADING_SYMBOLS
        if not symbols_str:
            return ["ETH"]  # 默认ETH
        return [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    
    def symbol_to_ccxt_format(self, symbol: str) -> str:
        """将币种名称转换为CCXT格式"""
        # BTC -> BTC/USDT:USDT
        return f"{symbol}/USDT:USDT"


# 全局配置实例
settings = Settings()
