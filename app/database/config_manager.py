"""
配置管理模块
从数据库读取配置，替代config.py中的硬编码配置
"""
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.connection import Database
import logging
import json

# 使用基础logging，避免循环导入
logger = logging.getLogger("qwentradeai")


class ConfigManager:
    """配置管理器 - 从数据库读取配置"""
    
    def __init__(self, db: Database):
        """
        初始化配置管理器
        
        Args:
            db: 数据库连接实例
        """
        self.db = db
        self._cache: Dict[str, Any] = {}  # 配置缓存
        self._load_all_configs()
    
    def _load_all_configs(self):
        """从数据库加载所有配置到缓存"""
        try:
            session = self.db.get_session()
            try:
                result = session.execute(
                    text("SELECT config_key, value, value_type FROM system_config")
                )
                rows = result.fetchall()
                
                for row in rows:
                    key, value, value_type = row
                    # 根据类型转换值
                    if value_type == 'int':
                        self._cache[key] = int(value) if value else None
                    elif value_type == 'float':
                        self._cache[key] = float(value) if value else None
                    elif value_type == 'boolean' or value_type == 'bool':
                        self._cache[key] = value.lower() in ('true', '1', 'yes') if value else False
                    elif value_type == 'json':
                        self._cache[key] = json.loads(value) if value else None
                    else:  # string
                        self._cache[key] = value
                
                logger.info(f"已从数据库加载 {len(self._cache)} 个配置项")
            finally:
                session.close()
        except Exception as e:
            logger.error(f"加载配置失败: {e}", exc_info=True)
            # 如果数据库中没有配置表，使用默认值
            self._load_default_configs()
    
    def _load_default_configs(self):
        """加载默认配置（当数据库配置表不存在时使用）"""
        logger.warning("数据库配置表不存在，使用默认配置")
        # 这里可以设置一些关键配置的默认值
        self._cache = {
            'APP_NAME': 'QwenTradeAI',
            'APP_VERSION': '2.0',
            'DEBUG': False,
            'LOG_LEVEL': 'INFO',
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键名
            default: 默认值（如果配置不存在）
            
        Returns:
            配置值
        """
        return self._cache.get(key, default)
    
    def get_string(self, key: str, default: str = '') -> str:
        """获取字符串配置"""
        value = self.get(key, default)
        return str(value) if value is not None else default
    
    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数配置"""
        value = self.get(key, default)
        try:
            return int(value) if value is not None else default
        except (ValueError, TypeError):
            return default
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """获取浮点数配置"""
        value = self.get(key, default)
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置"""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value) if value is not None else default
    
    def set(self, key: str, value: Any, value_type: str = 'string', description: str = ''):
        """
        设置配置值（同时更新数据库和缓存）
        
        Args:
            key: 配置键名
            value: 配置值
            value_type: 配置类型（string/int/float/boolean/json）
            description: 配置说明
        """
        try:
            session = self.db.get_session()
            try:
                # 转换为字符串存储
                if value_type == 'json':
                    value_str = json.dumps(value, ensure_ascii=False)
                else:
                    value_str = str(value)
                
                # 更新或插入数据库
                session.execute(
                    text("""
                        INSERT INTO system_config (config_key, value, value_type, description)
                        VALUES (:key, :value, :type, :description)
                        ON CONFLICT (config_key) DO UPDATE SET
                            value = EXCLUDED.value,
                            value_type = EXCLUDED.value_type,
                            description = EXCLUDED.description,
                            updated_at = NOW()
                    """),
                    {
                        'key': key,
                        'value': value_str,
                        'type': value_type,
                        'description': description
                    }
                )
                session.commit()
                
                # 更新缓存
                self._cache[key] = value
                
                logger.info(f"配置已更新: {key} = {value}")
            finally:
                session.close()
        except Exception as e:
            logger.error(f"设置配置失败: {e}", exc_info=True)
    
    def reload(self):
        """重新加载所有配置（从数据库）"""
        self._cache.clear()
        self._load_all_configs()
    
    def get_trading_symbols(self) -> List[str]:
        """获取交易币种列表"""
        symbols_str = self.get_string('TRADING_SYMBOLS', 'ETH')
        if not symbols_str:
            return ['ETH']  # 默认ETH
        return [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    
    def symbol_to_ccxt_format(self, symbol: str) -> str:
        """将币种名称转换为CCXT格式"""
        return f"{symbol}/USDT:USDT"
    
    def get_ws_url(self) -> str:
        """获取WebSocket公共频道URL（根据EXCHANGE_SANDBOX自动选择）"""
        sandbox = self.get_bool('EXCHANGE_SANDBOX', True)
        if sandbox:
            return "wss://wspap.okx.com:8443/ws/v5/public"
        else:
            return "wss://ws.okx.com:8443/ws/v5/public"
    
    def get_ws_private_url(self) -> str:
        """获取WebSocket私有频道URL（根据EXCHANGE_SANDBOX自动选择）"""
        sandbox = self.get_bool('EXCHANGE_SANDBOX', True)
        if sandbox:
            return "wss://wspap.okx.com:8443/ws/v5/private"
        else:
            return "wss://ws.okx.com:8443/ws/v5/private"

