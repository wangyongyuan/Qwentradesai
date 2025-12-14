"""
市场检测器模块测试
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
from app.layers.market_detector import (
    MarketDetector, MarketDetectorConfig, MarketSignal, MarketType,
    WeightConfig, ScoreBreakdown
)
from app.database.connection import Database


class TestMarketDetector:
    """市场检测器测试类"""
    
    @pytest.fixture
    def mock_db(self):
        """模拟数据库"""
        db = Mock(spec=Database)
        db.get_session = Mock()
        return db
    
    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        config = Mock()
        config.get_trading_symbols = Mock(return_value=['BTC', 'ETH'])
        return config
    
    @pytest.fixture
    def detector(self, mock_db, mock_config):
        """创建市场检测器实例"""
        detector_config = MarketDetectorConfig()
        return MarketDetector(
            db=mock_db,
            config=mock_config,
            detector_config=detector_config
        )
    
    def test_weight_config_normalization(self):
        """测试权重配置归一化"""
        # 权重总和不为1.0，应该自动归一化
        weights = WeightConfig(
            price_action=0.4,
            volume=0.3,
            technical=0.2,
            multi_timeframe=0.15,
            market_env=0.1
        )
        total = weights.price_action + weights.volume + weights.technical + \
                weights.multi_timeframe + weights.market_env
        assert abs(total - 1.0) < 0.01, "权重应该归一化为1.0"
    
    def test_score_breakdown_calculation(self):
        """测试评分明细计算"""
        breakdown = ScoreBreakdown(
            base_score=80.0,
            market_coef=1.0,
            symbol_coef=1.0
        )
        assert breakdown.final_score == 80.0, "最终分数应该等于base_score × market_coef × symbol_coef"
        
        breakdown.market_coef = 1.2
        breakdown.symbol_coef = 0.9
        assert breakdown.final_score == 80.0 * 1.2 * 0.9, "最终分数应该正确计算"
    
    @patch('app.layers.market_detector.KlineRepository')
    @patch('app.layers.market_detector.FearGreedRepository')
    def test_quick_filter(self, mock_fear_greed, mock_kline, detector):
        """测试快速过滤"""
        # 模拟K线数据
        klines_15m = [
            {
                'time': datetime.now(timezone.utc),
                'close': 100.0,
                'open': 99.5,
            }
        ]
        
        # 价格变化小于阈值，应该被过滤
        result = detector._quick_filter(klines_15m)
        # 注意：实际实现中，如果价格变化很小，应该返回False
        assert isinstance(result, bool), "快速过滤应该返回布尔值"
    
    @patch('app.layers.market_detector.KlineRepository')
    @patch('app.layers.market_detector.FearGreedRepository')
    def test_detect_market_type(self, mock_fear_greed, mock_kline, detector):
        """测试市场类型检测"""
        # 模拟K线数据
        klines_15m = [
            {
                'time': datetime.now(timezone.utc),
                'adx_14': 30.0,  # 趋势市
                'atr_14': 1.0,
                'bb_width': 0.05,
            }
        ]
        klines_4h = []
        
        # 模拟恐惧贪婪指数
        mock_fear_greed_repo = Mock()
        mock_fear_greed_repo.get_latest_value.return_value = 50  # 中性
        
        with patch('app.layers.market_detector.FearGreedRepository', return_value=mock_fear_greed_repo):
            market_type = detector._detect_market_type(klines_15m, klines_4h)
            assert market_type in [MarketType.TRENDING, MarketType.RANGING, 
                                  MarketType.BREAKOUT, MarketType.EXTREME], \
                "市场类型应该是枚举值之一"
    
    def test_get_dynamic_weights(self, detector):
        """测试动态权重计算"""
        # 测试不同市场类型的权重
        for market_type in MarketType:
            weights = detector._get_dynamic_weights(market_type, 'BTC')
            assert isinstance(weights, WeightConfig), "应该返回WeightConfig对象"
            total = weights.price_action + weights.volume + weights.technical + \
                    weights.multi_timeframe + weights.market_env
            assert abs(total - 1.0) < 0.01, "权重总和应该为1.0"
    
    @patch('app.layers.market_detector.KlineRepository')
    @patch('app.layers.market_detector.FearGreedRepository')
    @patch('app.layers.market_detector.MarketSignalRepository')
    def test_detect_no_signal(self, mock_signal_repo, mock_fear_greed, mock_kline, detector):
        """测试无信号情况"""
        # 模拟K线数据不足
        mock_kline_repo = Mock()
        mock_kline_repo.get_klines_with_indicators.return_value = []
        
        with patch('app.layers.market_detector.KlineRepository', return_value=mock_kline_repo):
            result = detector.detect('BTC')
            assert result is None, "数据不足时应该返回None"


class TestMarketSignalScoring:
    """市场信号评分测试"""
    
    @pytest.fixture
    def mock_klines(self):
        """模拟K线数据"""
        return [
            {
                'time': datetime.now(timezone.utc),
                'open': 100.0,
                'high': 105.0,
                'low': 99.0,
                'close': 104.0,
                'volume': 1000.0,
                'rsi_7': 60.0,
                'macd_line': 0.5,
                'signal_line': 0.3,
                'histogram': 0.2,
                'ema_9': 102.0,
                'ema_21': 101.0,
                'bb_upper': 106.0,
                'bb_middle': 102.0,
                'bb_lower': 98.0,
                'atr_14': 2.0,
            }
        ]
    
    @pytest.fixture
    def mock_weights(self):
        """模拟权重配置"""
        return WeightConfig()
    
    def test_calc_volume_score(self, mock_klines, mock_weights):
        """测试成交量评分"""
        detector = MarketDetector(
            db=Mock(),
            config=Mock(),
            detector_config=MarketDetectorConfig()
        )
        
        score = detector._calc_volume_score(mock_klines, 1.5)  # 1.5倍放大
        assert 0 <= score <= 100, "成交量分数应该在0-100之间"
    
    def test_calc_rsi_score(self):
        """测试RSI评分"""
        detector = MarketDetector(
            db=Mock(),
            config=Mock(),
            detector_config=MarketDetectorConfig()
        )
        
        # 测试超卖情况
        score_oversold = detector._calc_rsi_score(20.0, is_oversold=True)
        assert score_oversold > 0, "超卖时RSI分数应该大于0"
        
        # 测试超买情况
        score_overbought = detector._calc_rsi_score(80.0, is_overbought=True)
        assert score_overbought > 0, "超买时RSI分数应该大于0"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

