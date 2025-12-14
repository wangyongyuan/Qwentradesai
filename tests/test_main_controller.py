"""
主控循环模块测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from app.layers.main_controller import MainController
from app.components.position_manager import PositionManager
from app.components.api_manager import APIManager
from app.layers.market_detector import MarketDetector, MarketSignal


class TestMainController:
    """主控循环测试类"""
    
    @pytest.fixture
    def mock_db(self):
        """模拟数据库"""
        db = Mock()
        db.get_session = Mock()
        return db
    
    @pytest.fixture
    def mock_api_manager(self):
        """模拟API管理器"""
        api_manager = Mock(spec=APIManager)
        api_manager.running = True
        return api_manager
    
    @pytest.fixture
    def mock_position_manager(self):
        """模拟持仓管理器"""
        position_manager = Mock(spec=PositionManager)
        position_manager.has_position = Mock(return_value=False)
        return position_manager
    
    @pytest.fixture
    def mock_market_detector(self):
        """模拟市场检测器"""
        detector = Mock(spec=MarketDetector)
        detector.detect = Mock(return_value=None)
        return detector
    
    @pytest.fixture
    def controller(self, mock_db, mock_api_manager, mock_position_manager, mock_market_detector):
        """创建主控循环实例"""
        return MainController(
            db=mock_db,
            api_manager=mock_api_manager,
            position_manager=mock_position_manager,
            market_detector=mock_market_detector
        )
    
    def test_health_check_database(self, controller):
        """测试数据库健康检查"""
        # 模拟数据库连接成功
        mock_session = Mock()
        mock_session.execute = Mock()
        controller.db.get_session.return_value = mock_session
        
        result = controller._check_database()
        assert result is True, "数据库连接正常时应该返回True"
    
    def test_health_check_database_failure(self, controller):
        """测试数据库健康检查失败"""
        # 模拟数据库连接失败
        controller.db.get_session.side_effect = Exception("连接失败")
        
        result = controller._check_database()
        assert result is False, "数据库连接失败时应该返回False"
    
    def test_health_check_api(self, controller):
        """测试API健康检查"""
        controller.api_manager.running = True
        result = controller._check_api_connection()
        assert result is True, "API管理器运行时应该返回True"
        
        controller.api_manager.running = False
        result = controller._check_api_connection()
        assert result is False, "API管理器未运行时应该返回False"
    
    def test_is_in_cooldown(self, controller):
        """测试冷静期检查"""
        # 模拟数据库查询
        mock_session = Mock()
        mock_result = Mock()
        mock_row = Mock()
        
        # 测试不在冷静期
        mock_row.__getitem__.return_value = ''  # 空值
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result
        controller.db.get_session.return_value = mock_session
        
        result = controller._is_in_cooldown()
        assert result is False, "冷静期为空时应该返回False"
        
        # 测试在冷静期内
        future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        mock_row.__getitem__.return_value = future_time
        mock_result.fetchone.return_value = mock_row
        
        result = controller._is_in_cooldown()
        assert result is True, "在冷静期内应该返回True"
    
    def test_check_daily_limit(self, controller):
        """测试今日交易次数检查"""
        mock_session = Mock()
        mock_result = Mock()
        mock_row = Mock()
        
        # 测试未达上限
        mock_row.__getitem__.return_value = '2'  # 今日2次
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result
        controller.db.get_session.return_value = mock_session
        
        with patch('app.layers.main_controller.settings') as mock_settings:
            mock_settings.DAILY_TRADE_LIMIT = 3
            result = controller._check_daily_limit()
            assert result is False, "未达上限时应该返回False"
        
        # 测试已达上限
        mock_row.__getitem__.return_value = '3'  # 今日3次
        with patch('app.layers.main_controller.settings') as mock_settings:
            mock_settings.DAILY_TRADE_LIMIT = 3
            result = controller._check_daily_limit()
            assert result is True, "已达上限时应该返回True"
    
    def test_check_weekly_limit(self, controller):
        """测试本周交易次数检查"""
        mock_session = Mock()
        mock_result = Mock()
        mock_row = Mock()
        
        # 测试未达上限
        mock_row.__getitem__.return_value = '8'  # 本周8次
        mock_result.fetchone.return_value = mock_row
        mock_session.execute.return_value = mock_result
        controller.db.get_session.return_value = mock_session
        
        with patch('app.layers.main_controller.settings') as mock_settings:
            mock_settings.WEEKLY_TRADE_LIMIT = 10
            result = controller._check_weekly_limit()
            assert result is False, "未达上限时应该返回False"
    
    def test_check_limits_with_position(self, controller):
        """测试限制条件检查（有持仓）"""
        controller.position_manager.has_position.return_value = True
        
        result = controller._check_limits()
        assert result is False, "有持仓时应该返回False"
    
    @patch('app.layers.main_controller.settings')
    def test_run_cycle_with_signal(self, mock_settings, controller):
        """测试运行循环（检测到信号）"""
        mock_settings.get_trading_symbols.return_value = ['BTC']
        
        # 模拟健康检查和限制检查通过
        controller._health_check = Mock(return_value=True)
        controller._check_limits = Mock(return_value=True)
        
        # 模拟检测到信号
        controller.market_detector.detect.return_value = (
            MarketSignal.BREAKOUT_LONG, 85.0, Mock()
        )
        
        result = controller.run_cycle()
        assert result is not None, "检测到信号时应该返回结果"
        assert result[0] == MarketSignal.BREAKOUT_LONG, "应该返回正确的信号类型"
        assert result[1] == 85.0, "应该返回正确的分数"
    
    @patch('app.layers.main_controller.settings')
    def test_run_cycle_no_signal(self, mock_settings, controller):
        """测试运行循环（未检测到信号）"""
        mock_settings.get_trading_symbols.return_value = ['BTC']
        
        # 模拟健康检查和限制检查通过
        controller._health_check = Mock(return_value=True)
        controller._check_limits = Mock(return_value=True)
        
        # 模拟未检测到信号
        controller.market_detector.detect.return_value = None
        
        result = controller.run_cycle()
        assert result is None, "未检测到信号时应该返回None"
    
    def test_start_stop(self, controller):
        """测试启动和停止"""
        controller.start()
        assert controller.running is True, "启动后running应该为True"
        assert controller.thread is not None, "应该有线程对象"
        
        controller.stop()
        assert controller.running is False, "停止后running应该为False"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

