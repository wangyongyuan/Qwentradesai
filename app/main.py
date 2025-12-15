"""
FastAPI应用入口
"""
from typing import Dict
from fastapi import FastAPI
from app.config import settings
from app.utils.logger import logger
from app.api.routes import api_test, kline_test, coinglass_test
from app.components.api_manager import APIManager
from app.components.kline_sync import KlineSyncManager
from app.components.funding_rate_sync import FundingRateSyncManager
from app.components.coinglass_client import CoinGlassClient
from app.components.open_interest_sync import OpenInterestSyncManager
from app.components.market_sentiment_sync import MarketSentimentSyncManager
from app.components.order_book_sync import OrderBookSyncManager
from app.components.etf_flow_sync import ETFFlowSyncManager
from app.components.fear_greed_sync import FearGreedSyncManager
from app.components.liquidation_sync import LiquidationSyncManager
# 持仓同步和OKX订单历史同步已删除
# from app.components.position_manager import PositionManager
# from app.components.position_sync import PositionSyncManager
# from app.components.okx_orders_sync import OKXOrdersSyncManager
# from app.components.okx_positions_history_sync import OKXPositionsHistorySyncManager
# from app.components.risk_guard_thread import RiskGuardThread
# AI和市场检测相关模块已删除
# from app.layers.market_detector import MarketDetector, MarketDetectorConfig
# from app.layers.data_preparator import DataPreparator
# from app.layers.ai_council import AICouncil
# from app.layers.main_controller import MainController
# from app.layers.trade_executor import TradeExecutor
from app.database.connection import db
from queue import Queue

# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="数据同步系统 - 仅负责市场数据同步，不进行AI分析和交易执行",
    docs_url="/docs",  # Swagger UI文档地址
    redoc_url="/redoc",  # ReDoc文档地址
    openapi_url="/openapi.json"  # OpenAPI JSON地址
)

# 注册路由
app.include_router(api_test.router)
app.include_router(kline_test.router)
app.include_router(coinglass_test.router)

# 全局组件实例
api_manager: APIManager = None
coinglass_client: CoinGlassClient = None
kline_sync_managers: Dict[str, KlineSyncManager] = {}  # 每个币种一个同步管理器
funding_rate_sync_managers: Dict[str, FundingRateSyncManager] = {}  # 每个币种一个资金费率同步管理器
open_interest_sync_managers: Dict[str, OpenInterestSyncManager] = {}  # 每个币种一个未平仓合约同步管理器
market_sentiment_sync_managers: Dict[str, MarketSentimentSyncManager] = {}  # 每个币种一个市场情绪同步管理器
order_book_sync_managers: Dict[str, OrderBookSyncManager] = {}  # 每个币种一个盘口挂单同步管理器
etf_flow_sync_managers: Dict[str, ETFFlowSyncManager] = {}  # 每个币种一个ETF资金流同步管理器
fear_greed_sync_manager: FearGreedSyncManager = None  # 恐惧贪婪指数同步管理器（全局唯一）
liquidation_sync_managers: Dict[str, LiquidationSyncManager] = {}  # 每个币种一个爆仓历史同步管理器
# 持仓同步和OKX订单历史同步已删除
# position_sync_manager: PositionSyncManager = None  # 持仓同步管理器（全局唯一）
# okx_orders_sync_manager: OKXOrdersSyncManager = None  # OKX订单历史同步管理器（全局唯一）
# okx_positions_history_sync_manager: OKXPositionsHistorySyncManager = None  # OKX历史持仓同步管理器（全局唯一）
# position_manager: PositionManager = None  # 持仓管理器
# AI和市场检测相关组件已删除
# market_detector: MarketDetector = None  # 市场检测器
# data_preparator: DataPreparator = None  # 数据准备器
# ai_council: AICouncil = None  # AI委员会
# trade_executor: TradeExecutor = None  # 交易执行器
# main_controller: MainController = None  # 主控循环
# risk_guard_thread: RiskGuardThread = None  # 风控守护线程


@app.on_event("startup")
async def startup():
    """应用启动时初始化"""
    global api_manager, coinglass_client
    global kline_sync_managers, funding_rate_sync_managers
    global open_interest_sync_managers, market_sentiment_sync_managers
    global order_book_sync_managers, etf_flow_sync_managers, fear_greed_sync_manager
    # 持仓同步和OKX订单历史同步已删除
    # global position_sync_manager, okx_orders_sync_manager, okx_positions_history_sync_manager, position_manager
    # AI和市场检测相关组件已删除
    # global market_detector, data_preparator, ai_council, trade_executor, main_controller, risk_guard_thread
    
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    
    try:
        # 初始化API管理器
        logger.info("初始化API管理器...")
        api_manager = APIManager()
        api_manager.start()  # 启动API管理器工作线程
        logger.info("API管理器初始化完成")
        
        # 初始化CoinGlass客户端
        logger.info("初始化CoinGlass客户端...")
        coinglass_client = CoinGlassClient(settings)
        logger.info("CoinGlass客户端初始化完成")
        
        # 为每个币种创建K线同步管理器
        trading_symbols = settings.get_trading_symbols()
        logger.info(f"初始化K线同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            kline_sync_manager = KlineSyncManager(api_manager, symbol)
            kline_sync_manager.start()
            kline_sync_managers[symbol] = kline_sync_manager
            logger.info(f"{symbol} K线同步管理器已启动")
        
        # 为每个币种创建资金费率同步管理器
        logger.info(f"初始化资金费率同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            funding_rate_sync_manager = FundingRateSyncManager(api_manager, symbol)
            funding_rate_sync_manager.start()
            funding_rate_sync_managers[symbol] = funding_rate_sync_manager
            logger.info(f"{symbol} 资金费率同步管理器已启动")
        
        # 为每个币种创建未平仓合约同步管理器
        logger.info(f"初始化未平仓合约同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            open_interest_sync_manager = OpenInterestSyncManager(coinglass_client, symbol)
            open_interest_sync_manager.start()
            open_interest_sync_managers[symbol] = open_interest_sync_manager
            logger.info(f"{symbol} 未平仓合约同步管理器已启动")
        
        # 为每个币种创建市场情绪同步管理器
        logger.info(f"初始化市场情绪同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            market_sentiment_sync_manager = MarketSentimentSyncManager(coinglass_client, symbol)
            market_sentiment_sync_manager.start()
            market_sentiment_sync_managers[symbol] = market_sentiment_sync_manager
            logger.info(f"{symbol} 市场情绪同步管理器已启动")
        
        # 为每个币种创建盘口挂单同步管理器
        logger.info(f"初始化盘口挂单同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            order_book_sync_manager = OrderBookSyncManager(api_manager, symbol)
            order_book_sync_manager.start()
            order_book_sync_managers[symbol] = order_book_sync_manager
            logger.info(f"{symbol} 盘口挂单同步管理器已启动")
        
        # 为BTC和ETH创建ETF资金流同步管理器
        etf_symbols = ['BTC', 'ETH']
        logger.info(f"初始化ETF资金流同步管理器（币种: {', '.join(etf_symbols)}）...")
        for symbol in etf_symbols:
            if symbol in trading_symbols:
                etf_flow_sync_manager = ETFFlowSyncManager(coinglass_client, symbol)
                etf_flow_sync_manager.start()
                etf_flow_sync_managers[symbol] = etf_flow_sync_manager
                logger.info(f"{symbol} ETF资金流同步管理器已启动")
        
        # 创建恐惧贪婪指数同步管理器（全局唯一）
        logger.info("初始化恐惧贪婪指数同步管理器...")
        fear_greed_sync_manager = FearGreedSyncManager(coinglass_client)
        fear_greed_sync_manager.start()
        logger.info("恐惧贪婪指数同步管理器已启动")
        
        # 为每个币种创建爆仓历史同步管理器
        logger.info(f"初始化爆仓历史同步管理器（币种: {', '.join(trading_symbols)}）...")
        for symbol in trading_symbols:
            liquidation_sync_manager = LiquidationSyncManager(coinglass_client, symbol)
            liquidation_sync_manager.start()
            liquidation_sync_managers[symbol] = liquidation_sync_manager
            logger.info(f"{symbol} 爆仓历史同步管理器已启动")
        
        # 持仓同步和OKX订单历史同步已删除
        # 系统现在只负责基础数据同步，不进行持仓和订单历史同步
        
        # AI和市场检测相关组件已删除
        # 系统现在只负责数据同步，不进行AI分析和交易执行
        logger.info("AI分析和市场检测功能已禁用，系统仅保留基础数据同步功能")
        
        logger.info("数据库连接: 已配置")
        logger.info("配置加载: 成功")
        logger.info(f"{settings.APP_NAME} 启动完成")
        
    except Exception as e:
        logger.error(f"启动失败: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown():
    """应用关闭时清理"""
    global kline_sync_managers, funding_rate_sync_managers, api_manager
    global open_interest_sync_managers, market_sentiment_sync_managers
    global order_book_sync_managers, etf_flow_sync_managers, fear_greed_sync_manager
    global liquidation_sync_managers
    # 持仓同步和OKX订单历史同步已删除
    # global position_sync_manager, okx_orders_sync_manager, okx_positions_history_sync_manager
    
    logger.info(f"{settings.APP_NAME} 正在关闭...")
    
    try:
        # 持仓同步和OKX订单历史同步已删除，无需停止
        
        # 停止恐惧贪婪指数同步线程
        if fear_greed_sync_manager:
            logger.info("正在停止恐惧贪婪指数同步线程...")
            try:
                fear_greed_sync_manager.stop()
                fear_greed_sync_manager.join(timeout=5)
                if fear_greed_sync_manager.is_alive():
                    logger.warning("恐惧贪婪指数同步线程未在5秒内停止")
                else:
                    logger.info("恐惧贪婪指数同步线程已停止")
            except Exception as e:
                logger.error(f"停止恐惧贪婪指数同步线程失败: {e}", exc_info=True)
        
        # 停止所有ETF资金流同步线程
        if etf_flow_sync_managers:
            logger.info("正在停止ETF资金流同步线程...")
            for symbol, manager in etf_flow_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} ETF资金流同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} ETF资金流同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} ETF资金流同步线程失败: {e}", exc_info=True)
        
        # 停止所有爆仓历史同步线程
        if liquidation_sync_managers:
            logger.info("正在停止爆仓历史同步线程...")
            for symbol, manager in liquidation_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} 爆仓历史同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} 爆仓历史同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} 爆仓历史同步线程失败: {e}", exc_info=True)
        
        # 停止所有盘口挂单同步线程
        if order_book_sync_managers:
            logger.info("正在停止盘口挂单同步线程...")
            for symbol, manager in order_book_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} 盘口挂单同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} 盘口挂单同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} 盘口挂单同步线程失败: {e}", exc_info=True)
        
        # 停止所有市场情绪同步线程
        if market_sentiment_sync_managers:
            logger.info("正在停止市场情绪同步线程...")
            for symbol, manager in market_sentiment_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} 市场情绪同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} 市场情绪同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} 市场情绪同步线程失败: {e}", exc_info=True)
        
        # 停止所有未平仓合约同步线程
        if open_interest_sync_managers:
            logger.info("正在停止未平仓合约同步线程...")
            for symbol, manager in open_interest_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} 未平仓合约同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} 未平仓合约同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} 未平仓合约同步线程失败: {e}", exc_info=True)
        
        # 停止所有资金费率同步线程
        if funding_rate_sync_managers:
            logger.info("正在停止资金费率同步线程...")
            for symbol, manager in funding_rate_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)
                    if manager.is_alive():
                        logger.warning(f"{symbol} 资金费率同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} 资金费率同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol}资金费率同步线程失败: {e}", exc_info=True)
        
        # 停止所有K线同步线程
        if kline_sync_managers:
            logger.info("正在停止K线同步线程...")
            for symbol, manager in kline_sync_managers.items():
                try:
                    manager.stop()
                    manager.join(timeout=5)  # 减少超时时间，加快关闭
                    if manager.is_alive():
                        logger.warning(f"{symbol} K线同步线程未在5秒内停止")
                    else:
                        logger.info(f"{symbol} K线同步线程已停止")
                except Exception as e:
                    logger.error(f"停止{symbol} K线同步线程失败: {e}", exc_info=True)
        
        # AI和市场检测相关组件已删除，无需停止
        
        # 关闭API管理器（不等待队列完成，直接停止）
        if api_manager:
            logger.info("正在关闭API管理器...")
            api_manager.running = False  # 直接设置标志，不等待队列
            if api_manager.worker_thread:
                api_manager.worker_thread.join(timeout=3)
            logger.info("API管理器已关闭")
        
        logger.info(f"{settings.APP_NAME} 已关闭")
        
    except Exception as e:
        logger.error(f"关闭时发生错误: {e}", exc_info=True)




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

