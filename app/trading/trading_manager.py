"""
交易管理器
提供开仓、加仓、减仓、平仓等交易功能
"""
import json
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import text
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.trading_relations import TradingRelationsRepository
from app.database.market_signal import MarketSignalRepository
from app.trading.clord_id_generator import ClOrdIdGenerator
from app.config import settings
from app.utils.logger import logger


class TradingManager:
    """交易管理器"""
    
    def __init__(self, api_manager: APIManager):
        """
        初始化交易管理器
        
        Args:
            api_manager: API管理器实例
            
        Raises:
            ValueError: 如果api_manager为None
        """
        if api_manager is None:
            raise ValueError("api_manager不能为None")
        
        # 依赖注入
        self.api_manager = api_manager
        self.db = db
        
        # 验证数据库连接
        try:
            with self.db.get_session() as session:
                session.execute(text("SELECT 1"))
            logger.debug("数据库连接验证成功")
        except Exception as e:
            logger.warning(f"数据库连接验证失败: {e}")
        
        # Repository实例（虽然都是静态方法，但保持一致性）
        self.trading_relations_repo = TradingRelationsRepository
        self.market_signal_repo = MarketSignalRepository
        
        # clOrdId生成器
        self.cl_ord_id_generator = ClOrdIdGenerator
        
        # 内存管理：当前活跃的clOrdId（一次只能开一单）
        self.current_cl_ord_id: Optional[str] = None
        
        # 当前持仓方向（LONG/SHORT）
        self.current_position_side: Optional[str] = None
        
        # 当前持仓数量（币数量，用于部分平仓后更新）
        self.current_position_amount: Optional[float] = None
        
        logger.info("交易管理器已初始化")
    
    # ============================================
    # 内存管理方法
    # ============================================
    
    def _set_current_cl_ord_id(self, cl_ord_id: str, position_side: str, position_amount: Optional[float] = None) -> None:
        """
        设置当前活跃的clOrdId和持仓方向
        
        Args:
            cl_ord_id: 客户端订单ID
            position_side: 持仓方向（LONG/SHORT）
            position_amount: 持仓数量（可选，币数量）
        """
        self.current_cl_ord_id = cl_ord_id
        self.current_position_side = position_side
        if position_amount is not None:
            self.current_position_amount = position_amount
        logger.debug(
            f"内存管理：设置当前clOrdId={cl_ord_id}, 持仓方向={position_side}, "
            f"持仓数量={position_amount}"
        )
    
    def _clear_current_cl_ord_id(self) -> None:
        """清除当前活跃的clOrdId和持仓方向（全部平仓后调用）"""
        old_cl_ord_id = self.current_cl_ord_id
        self.current_cl_ord_id = None
        self.current_position_side = None
        self.current_position_amount = None
        logger.debug(f"内存管理：清除当前clOrdId={old_cl_ord_id}")
    
    def _update_position_amount(self, new_amount: float) -> None:
        """
        更新当前持仓数量（部分平仓后调用）
        
        Args:
            new_amount: 新的持仓数量（币数量）
        """
        if new_amount <= 0:
            logger.warning(f"更新持仓数量失败: 新数量必须大于0，当前值: {new_amount}")
            return
        
        old_amount = self.current_position_amount
        self.current_position_amount = new_amount
        logger.debug(
            f"内存管理：更新持仓数量: {old_amount} -> {new_amount}, "
            f"clOrdId={self.current_cl_ord_id}"
        )
    
    def has_active_position(self) -> bool:
        """
        检查是否有活跃的持仓（通过内存中的clOrdId判断）
        
        Returns:
            是否有活跃持仓
        """
        return self.current_cl_ord_id is not None
    
    def get_current_cl_ord_id(self) -> Optional[str]:
        """
        获取当前活跃的clOrdId
        
        Returns:
            当前clOrdId，如果没有则返回None
        """
        return self.current_cl_ord_id
    
    def get_current_position_side(self) -> Optional[str]:
        """
        获取当前持仓方向
        
        Returns:
            当前持仓方向（LONG/SHORT），如果没有则返回None
        """
        return self.current_position_side
    
    # ============================================
    # Symbol转换方法
    # ============================================
    
    def _symbol_to_ccxt_format(self, symbol: str) -> str:
        """
        将币种名称转换为CCXT格式
        
        Args:
            symbol: 币种名称（如BTC、ETH）
            
        Returns:
            CCXT格式的交易对（如BTC/USDT:USDT）
        """
        # 如果已经是CCXT格式，直接返回
        if '/' in symbol:
            return symbol
        
        # BTC -> BTC/USDT:USDT
        return f"{symbol}/USDT:USDT"
    
    def _symbol_to_okx_format(self, symbol: str) -> str:
        """
        将币种名称转换为OKX格式
        
        Args:
            symbol: 币种名称（如BTC、ETH）或CCXT格式（如BTC/USDT:USDT）
            
        Returns:
            OKX格式的交易对（如BTC-USDT-SWAP）
        """
        # 先转换为CCXT格式（如果还不是）
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        
        # BTC/USDT:USDT -> BTC-USDT-SWAP
        okx_symbol = ccxt_symbol.replace('/', '-').replace(':USDT', '-SWAP')
        
        return okx_symbol
    
    # ============================================
    # 方向转换方法
    # ============================================
    
    def _position_side_to_okx_side(self, position_side: str) -> str:
        """
        将持仓方向（LONG/SHORT）转换为OKX API的side（buy/sell）
        
        Args:
            position_side: 持仓方向（LONG/SHORT）
            
        Returns:
            OKX API的side（buy/sell）
            
        Raises:
            ValueError: 如果position_side不是LONG或SHORT
        """
        position_side_upper = position_side.upper()
        if position_side_upper == 'LONG':
            return 'buy'
        elif position_side_upper == 'SHORT':
            return 'sell'
        else:
            raise ValueError(f"无效的持仓方向: {position_side}，必须是LONG或SHORT")
    
    def _position_side_to_okx_pos_side(self, position_side: str) -> str:
        """
        将持仓方向（LONG/SHORT）转换为OKX API的posSide（long/short）
        
        Args:
            position_side: 持仓方向（LONG/SHORT）
            
        Returns:
            OKX API的posSide（long/short）
            
        Raises:
            ValueError: 如果position_side不是LONG或SHORT
        """
        position_side_upper = position_side.upper()
        if position_side_upper == 'LONG':
            return 'long'
        elif position_side_upper == 'SHORT':
            return 'short'
        else:
            raise ValueError(f"无效的持仓方向: {position_side}，必须是LONG或SHORT")
    
    # ============================================
    # 止损止盈价格验证方法
    # ============================================
    
    def _validate_stop_loss_take_profit(
        self,
        entry_price: float,
        stop_loss_trigger: Optional[float],
        take_profit_trigger: Optional[float],
        position_side: str
    ) -> bool:
        """
        验证止损止盈价格的合理性
        
        Args:
            entry_price: 开仓价格
            stop_loss_trigger: 止损触发价格（可选）
            take_profit_trigger: 止盈触发价格（可选）
            position_side: 持仓方向（long/short 或 LONG/SHORT）
            
        Returns:
            验证是否通过（True=通过，False=不通过）
        """
        position_side_upper = position_side.upper()
        
        # 验证止损价格（如果提供）
        if stop_loss_trigger is not None:
            if position_side_upper == 'LONG':
                if stop_loss_trigger >= entry_price:
                    logger.warning(
                        f"止损价格验证失败（LONG）: 止损价={stop_loss_trigger} >= 开仓价={entry_price}"
                    )
                    return False
            elif position_side_upper == 'SHORT':
                if stop_loss_trigger <= entry_price:
                    logger.warning(
                        f"止损价格验证失败（SHORT）: 止损价={stop_loss_trigger} <= 开仓价={entry_price}"
                    )
                    return False
            else:
                logger.warning(f"未知的持仓方向: {position_side}")
                return False
        
        # 验证止盈价格（如果提供）
        if take_profit_trigger is not None:
            if position_side_upper == 'LONG':
                if take_profit_trigger <= entry_price:
                    logger.warning(
                        f"止盈价格验证失败（LONG）: 止盈价={take_profit_trigger} <= 开仓价={entry_price}"
                    )
                    return False
            elif position_side_upper == 'SHORT':
                if take_profit_trigger >= entry_price:
                    logger.warning(
                        f"止盈价格验证失败（SHORT）: 止盈价={take_profit_trigger} >= 开仓价={entry_price}"
                    )
                    return False
            else:
                logger.warning(f"未知的持仓方向: {position_side}")
                return False
        
        return True
    
    # ============================================
    # 辅助方法：从order_history查询sz并转换为币数量
    # ============================================
    
    def _get_amount_from_order_history(
        self,
        session,
        ord_id: str,
        symbol: str,
        fallback_amount: float
    ) -> float:
        """
        从order_history查询acc_fill_sz字段并转换为币数量
        
        Args:
            session: 数据库会话
            ord_id: 订单ID
            symbol: 币种名称（如BTC、ETH）
            fallback_amount: 如果查询不到，使用的默认值（币数量）
            
        Returns:
            币数量
        """
        try:
            sql = text("""
                SELECT acc_fill_sz, symbol
                FROM order_history
                WHERE ord_id = :ord_id
                LIMIT 1
            """)
            result = session.execute(sql, {'ord_id': ord_id}).fetchone()
            
            if result and result[0] is not None:
                acc_fill_sz_contracts = float(result[0])  # acc_fill_sz是累计成交数量（合约数量）
                result_symbol = result[1] if len(result) > 1 else symbol
                
                # 获取合约乘数
                contract_size = 0.1 if result_symbol.upper() == 'ETH' else 1.0
                
                # 转换为币数量
                amount = acc_fill_sz_contracts * contract_size
                # 【查询amount日志】trading_manager.py:327 - 从order_history查询acc_fill_sz成功
                logger.info(
                    f"【查询amount】位置: trading_manager.py:327 (_get_amount_from_order_history) | "
                    f"ord_id: {ord_id} | symbol: {result_symbol} | "
                    f"查询到的acc_fill_sz(合约): {acc_fill_sz_contracts} | contract_size: {contract_size} | "
                    f"转换后的amount(币): {amount}"
                )
                return amount
            else:
                # 【查询amount日志】trading_manager.py:330 - 查询失败，使用fallback
                logger.warning(
                    f"【查询amount】位置: trading_manager.py:330 (_get_amount_from_order_history) | "
                    f"ord_id: {ord_id} | order_history中未找到，使用fallback_amount(币): {fallback_amount}"
                )
                return fallback_amount
        except Exception as e:
            logger.warning(f"查询order_history.acc_fill_sz失败: ord_id={ord_id}, error={e}，使用fallback_amount={fallback_amount}")
            return fallback_amount
    
    # ============================================
    # 开仓方法
    # ============================================
    
    def open_position(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_loss_trigger: float,
        take_profit_trigger: float,
        leverage: float,
        signal_id: int
    ) -> str:
        """
        开仓（必须设置止损止盈）
        
        Args:
            symbol: 币种名称（如BTC、ETH）
            side: 持仓方向（LONG/SHORT）
            amount: 开仓数量（绝对值）
            stop_loss_trigger: 止损触发价格
            take_profit_trigger: 止盈触发价格
            leverage: 杠杆倍数（AI返回的杠杆）
            signal_id: 信号ID（market_signals.id）
            
        Returns:
            clOrdId（客户端订单ID）
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 已有活跃持仓或开仓失败
        """
        # 参数验证
        if not symbol or not symbol.strip():
            raise ValueError("symbol不能为空")
        
        symbol = symbol.strip().upper()
        
        if side.upper() not in ['LONG', 'SHORT']:
            raise ValueError(f"side必须是LONG或SHORT，当前值: {side}")
        
        if amount <= 0:
            raise ValueError(f"amount必须大于0，当前值: {amount}")
        
        if stop_loss_trigger <= 0:
            raise ValueError(f"stop_loss_trigger必须大于0，当前值: {stop_loss_trigger}")
        
        if take_profit_trigger <= 0:
            raise ValueError(f"take_profit_trigger必须大于0，当前值: {take_profit_trigger}")
        
        if leverage <= 0:
            raise ValueError(f"leverage必须大于0，当前值: {leverage}")
        
        # 验证杠杆不超过配置的最大杠杆
        max_leverage = settings._get('MAX_LEVERAGE', 10, 'float')
        if leverage > max_leverage:
            raise ValueError(
                f"杠杆倍数{leverage}超过最大杠杆{max_leverage}，拒绝开单"
            )
        
        if signal_id <= 0:
            raise ValueError(f"signal_id必须大于0，当前值: {signal_id}")
        
        # 检查是否已有活跃持仓（一次只能开一单）
        if self.has_active_position():
            # 兜底检查：查询OKX API的实际持仓，如果实际持仓为0，但内存中还有cl_ord_id，则清除内存状态
            try:
                position_info = self._get_current_position_from_okx(symbol)
                current_pos_size = position_info.get('pos', 0)
                
                if current_pos_size == 0 or abs(current_pos_size) < 0.0001:
                    # 实际持仓为0，但内存中还有cl_ord_id，说明外部平仓后没有正确清除内存状态
                    logger.warning(
                        f"检测到内存中有cl_ord_id={self.current_cl_ord_id}，但OKX API查询实际持仓为0，"
                        f"自动清除内存状态"
                    )
                    self._clear_current_cl_ord_id()
                else:
                    # 实际有持仓，抛出异常
                    raise RuntimeError(
                        f"已有活跃持仓（clOrdId={self.current_cl_ord_id}），"
                        f"一次只能开一单，请先平仓后再开新单"
                    )
            except RuntimeError as e:
                # 如果是因为持仓为0导致的异常，清除内存状态并继续开仓
                error_msg = str(e)
                if "当前持仓数量为0" in error_msg or "未找到" in error_msg:
                    logger.warning(
                        f"检测到内存中有cl_ord_id={self.current_cl_ord_id}，但OKX API查询实际持仓为0，"
                        f"自动清除内存状态"
                    )
                    self._clear_current_cl_ord_id()
                else:
                    # 其他错误，仍然抛出异常（保守策略）
                    logger.error(f"查询OKX实际持仓失败: {e}", exc_info=True)
                    raise RuntimeError(
                        f"已有活跃持仓（clOrdId={self.current_cl_ord_id}），"
                        f"一次只能开一单，请先平仓后再开新单"
                    )
            except Exception as e:
                # 其他异常，记录日志但不阻止开仓（可能是网络问题等）
                logger.warning(f"查询OKX实际持仓时发生异常: {e}，继续尝试开仓")
                # 不清除内存状态，因为可能是临时网络问题
        
        # 转换symbol格式
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        okx_inst_id = self._symbol_to_okx_format(symbol)
        
        # 获取当前价格（用于验证止损止盈）
        current_price = self.api_manager.get_current_price(ccxt_symbol)
        
        if current_price is None:
            raise RuntimeError(f"无法获取{symbol}的当前价格")
        
        # 验证止损止盈价格
        if not self._validate_stop_loss_take_profit(
            entry_price=current_price,
            stop_loss_trigger=stop_loss_trigger,
            take_profit_trigger=take_profit_trigger,
            position_side=side
        ):
            raise ValueError(
                f"止损止盈价格验证失败: "
                f"当前价格={current_price}, 止损={stop_loss_trigger}, 止盈={take_profit_trigger}, "
                f"持仓方向={side}"
            )
        
        # 生成clOrdId
        cl_ord_id = self.cl_ord_id_generator.generate()
        
        logger.info(
            f"开仓准备: symbol={symbol}, side={side}, amount={amount}, "
            f"止损={stop_loss_trigger}, 止盈={take_profit_trigger}, "
            f"杠杆={leverage}, signal_id={signal_id}, clOrdId={cl_ord_id}"
        )
        
        # 转换方向
        okx_side = self._position_side_to_okx_side(side)
        okx_pos_side = self._position_side_to_okx_pos_side(side)
        
        # 获取合约信息并转换数量（币数量 -> 合约张数）
        try:
            market = self.api_manager.exchange.market(ccxt_symbol)
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
                f"数量转换: 币数量={amount:.6f}, "
                f"合约乘数={contract_size}, 合约张数={contracts:.1f}"
            )
        else:
            order_amount = amount
            logger.info(f"数量: {amount:.6f} (合约乘数=1，无需转换)")
        
        # 构建OKX API请求参数
        okx_params = {
            'instId': okx_inst_id,
            'tdMode': 'cross',  # 全仓模式（默认）
            'side': okx_side,
            'ordType': 'market',  # 市价单
            'sz': str(order_amount),  # 合约张数
            'posSide': okx_pos_side,
            'lever': str(int(leverage)),  # 杠杆倍数
            'clOrdId': cl_ord_id  # 客户端订单ID
        }
        
        # 构建止盈止损参数（attachAlgoOrds）
        # 生成策略委托单的客户端订单ID（开头必须是algo，总长度1-32位）
        # 格式：algo + clOrdId的后缀（确保总长度不超过32位）
        # algo占4位，所以后缀最多28位
        max_suffix_length = 28
        algo_cl_ord_id_suffix = cl_ord_id[-max_suffix_length:] if len(cl_ord_id) > max_suffix_length else cl_ord_id
        attach_algo_cl_ord_id = f"algo{algo_cl_ord_id_suffix}"
        
        attach_algo_ords = [{
            'tpTriggerPx': str(take_profit_trigger),
            'tpTriggerPxType': 'last',  # 使用最新价格触发
            'tpOrdPx': '-1',  # '-1'表示市价单
            'slTriggerPx': str(stop_loss_trigger),
            'slTriggerPxType': 'last',  # 使用最新价格触发
            'slOrdPx': '-1',  # '-1'表示市价单
            'attachAlgoClOrdId': attach_algo_cl_ord_id  # 策略委托单的客户端订单ID
        }]
        okx_params['attachAlgoOrds'] = attach_algo_ords
        
        logger.debug(f"OKX API参数: {okx_params}")
        
        # 调用OKX API下单
        try:
            # 检查API密钥是否配置
            if not settings.EXCHANGE_API_KEY:
                raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
            
            # 调用OKX原始API
            result = self.api_manager.exchange.private_post_trade_order(okx_params)
            
            # 处理API响应
            if not result:
                raise RuntimeError("OKX API返回结果为空")
            
            error_code = result.get('code', 'N/A')
            if error_code != '0':
                error_msg = result.get('msg', '未知错误')
                logger.error(f"OKX API下单失败: [{error_code}] {error_msg}")
                raise RuntimeError(f"OKX API下单失败: [{error_code}] {error_msg}")
            
            # 提取订单数据
            order_data_list = result.get('data', [])
            if not order_data_list:
                raise RuntimeError("OKX API返回的订单数据为空")
            
            # 提取所有订单ID（OKX可能拆单，一个clOrdId可能对应多个ordId）
            ord_ids = []
            for order_data in order_data_list:
                ord_id = order_data.get('ordId', '')
                if ord_id:
                    ord_ids.append(ord_id)
                    logger.info(f"订单创建成功: ordId={ord_id}, clOrdId={cl_ord_id}")
            
            if not ord_ids:
                raise RuntimeError("未获取到有效的订单ID")
            
            # 记录止盈止损策略订单ID（如果有）
            for order_data in order_data_list:
                if 'attachAlgoOrds' in order_data:
                    algo_orders = order_data.get('attachAlgoOrds', [])
                    if algo_orders:
                        algo_ids = [algo.get('algoId', 'N/A') for algo in algo_orders]
                        logger.info(f"止盈止损策略订单已创建: {algo_ids}")
            
            logger.info(
                f"开仓成功: symbol={symbol}, side={side}, amount={amount}, "
                f"clOrdId={cl_ord_id}, ordIds={ord_ids}"
            )
            
            # 保存订单信息供后续步骤使用
            order_info = {
                'cl_ord_id': cl_ord_id,
                'ord_ids': ord_ids,
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'current_price': current_price
            }
            
            # 记录trading_relations关联表和更新market_signals.trade_id（使用同一个事务）
            with self.db.get_session() as session:
                try:
                    # 记录trading_relations关联表
                    # 一个clOrdId可能对应多个ordId（OKX拆单），需要为每个ordId插入一条记录
                    for ord_id in ord_ids:
                        # 从order_history查询sz并转换为币数量
                        actual_amount = self._get_amount_from_order_history(
                            session=session,
                            ord_id=ord_id,
                            symbol=symbol,
                            fallback_amount=amount
                        )
                        # 【更新amount日志】trading_manager.py:614 - 开仓操作
                        logger.info(
                            f"【更新amount】位置: trading_manager.py:614 (open_position) | "
                            f"操作类型: open | ord_id: {ord_id} | cl_ord_id: {cl_ord_id} | "
                            f"请求数量(币): {amount} | 查询到的acc_fill_sz(合约): {actual_amount / (0.1 if symbol.upper() == 'ETH' else 1.0) if actual_amount > 0 else 0} | "
                            f"最终amount(币): {actual_amount} | 价格: {current_price}"
                        )
                        success = self.trading_relations_repo.insert_relation(
                            session=session,
                            signal_id=signal_id,
                            cl_ord_id=cl_ord_id,
                            operation_type='open',
                            ord_id=ord_id,
                            position_history_id=None,  # 开仓时还没有仓位历史ID
                            amount=actual_amount,
                            price=current_price
                        )
                        if not success:
                            logger.warning(f"记录trading_relations失败: ordId={ord_id}")
                        else:
                            logger.debug(f"已记录trading_relations: signal_id={signal_id}, clOrdId={cl_ord_id}, ordId={ord_id}")
                    
                    # 更新market_signals.trade_id为clOrdId
                    sql = text("""
                        UPDATE market_signals
                        SET trade_id = :trade_id, updated_at = NOW()
                        WHERE id = :signal_id
                    """)
                    result = session.execute(sql, {
                        'signal_id': signal_id,
                        'trade_id': cl_ord_id
                    })
                    session.commit()
                    
                    if result.rowcount > 0:
                        logger.info(f"已更新market_signals.trade_id: signal_id={signal_id}, trade_id={cl_ord_id}")
                    else:
                        logger.warning(f"更新market_signals.trade_id失败: signal_id={signal_id}不存在")
                        
                except Exception as e:
                    session.rollback()
                    logger.error(f"保存开仓记录失败: {e}", exc_info=True)
                    # 不抛出异常，因为订单已经创建成功，只是记录失败
            
            # 更新内存中的clOrdId、持仓方向和持仓数量
            self._set_current_cl_ord_id(cl_ord_id, side, position_amount=amount)
            
            logger.info(
                f"开仓完成: symbol={symbol}, side={side}, amount={amount}, "
                f"clOrdId={cl_ord_id}, signal_id={signal_id}"
            )
            
            return cl_ord_id
            
        except Exception as e:
            error_str = str(e)
            # 检查是否是认证错误
            if ('401' in error_str or 'Unauthorized' in error_str or
                'apiKey' in error_str or 'credential' in error_str.lower() or
                'authentication' in error_str.lower()):
                logger.error(f"下单失败（API密钥未配置或无效）: {error_str}")
            else:
                logger.error(f"调用OKX API下单失败: {error_str}", exc_info=True)
            raise
    
    # ============================================
    # 设置止损止盈方法
    # ============================================
    
    def _validate_plans(
        self,
        plans: List[Dict[str, Any]],
        current_position_size: float
    ) -> None:
        """
        验证分批止盈止损计划
        
        Args:
            plans: 止盈止损计划列表
            current_position_size: 当前持仓数量（币数量）
            
        Raises:
            ValueError: 验证失败
        """
        # 检查plans不为空
        if not plans or len(plans) == 0:
            raise ValueError("plans不能为空")
        
        # 分离止盈和止损订单
        take_profit_plans = [p for p in plans if 'take_profit' in p]
        stop_loss_plans = [p for p in plans if 'stop_loss' in p]
        
        # 检查至少有一个止盈订单
        if len(take_profit_plans) == 0:
            raise ValueError("必须至少有一个止盈订单")
        
        # 检查至少有一个止损订单
        if len(stop_loss_plans) == 0:
            raise ValueError("必须至少有一个止损订单")
        
        # 计算止盈订单数量总和
        take_profit_total = sum(float(p['amount']) for p in take_profit_plans)
        
        # 验证止盈订单数量总和等于持仓
        if abs(take_profit_total - current_position_size) > 0.0001:  # 允许浮点数误差
            raise ValueError(
                f"止盈订单数量总和({take_profit_total})不等于当前持仓({current_position_size})"
            )
        
        # 计算止损订单数量总和
        stop_loss_total = sum(float(p['amount']) for p in stop_loss_plans)
        
        # 验证止损订单数量总和等于持仓
        if abs(stop_loss_total - current_position_size) > 0.0001:  # 允许浮点数误差
            raise ValueError(
                f"止损订单数量总和({stop_loss_total})不等于当前持仓({current_position_size})"
            )
    
    def _cancel_all_pending_algo_orders(
        self,
        inst_id: str
    ) -> None:
        """
        取消所有未完成的策略委托订单
        
        Args:
            inst_id: 产品ID，如 'ETH-USDT-SWAP'
            
        Raises:
            RuntimeError: 查询或取消失败
        """
        try:
            # 查询未完成的策略委托单（需要查询 oco 和 conditional 两种类型）
            algo_orders = []
            
            # 查询 oco 类型的订单
            result_oco = self.api_manager.get_pending_algo_orders(
                inst_id=inst_id,
                ord_type='oco'
            )
            if result_oco.get('success', False):
                algo_orders.extend(result_oco.get('data', []))
            
            # 查询 conditional 类型的订单
            result_conditional = self.api_manager.get_pending_algo_orders(
                inst_id=inst_id,
                ord_type='conditional'
            )
            if result_conditional.get('success', False):
                algo_orders.extend(result_conditional.get('data', []))
            
            if not algo_orders:
                logger.debug(f"未找到未完成的策略委托单，无需取消")
                return
            
            # 提取algoId列表
            algo_order_list = [
                {"instId": order.get('instId', ''), "algoId": order.get('algoId', '')}
                for order in algo_orders
                if order.get('algoId')
            ]
            
            if not algo_order_list:
                logger.debug(f"未找到有效的策略委托单ID，无需取消")
                return
            
            # 调用取消接口
            cancel_result = self.api_manager.cancel_algo_orders(algo_order_list)
            
            if cancel_result.get('success', False):
                logger.info(f"成功取消{len(algo_order_list)}个策略委托订单")
            else:
                logger.warning(f"取消策略委托订单失败: {cancel_result.get('message', '未知错误')}")
                
        except Exception as e:
            # 只记录日志，不做任何处理
            logger.error(f"取消策略委托订单时发生错误: {e}", exc_info=True)
    
    def _create_take_profit_algo_order(
        self,
        inst_id: str,
        td_mode: str,
        pos_side: str,
        amount: float,
        take_profit_trigger: float,
        contract_size: float
    ) -> bool:
        """
        创建止盈策略订单
        
        Args:
            inst_id: 产品ID
            td_mode: 交易模式
            pos_side: 持仓方向
            amount: 数量（币数量）
            take_profit_trigger: 止盈触发价格
            contract_size: 合约乘数
            
        Returns:
            是否创建成功
        """
        try:
            # 转换币数量为合约张数
            if contract_size != 1.0 and contract_size > 0:
                contracts = amount / contract_size
                contracts = round(contracts, 1)
                order_sz = contracts
            else:
                order_sz = amount
            
            # 调用API创建策略订单
            result = self.api_manager.create_algo_order(
                inst_id=inst_id,
                td_mode=td_mode,
                pos_side=pos_side,
                sz=order_sz,
                take_profit_trigger=take_profit_trigger,
                take_profit_price='-1'  # 市价
            )
            
            if result.get('success', False):
                algo_id = result.get('algo_id', '')
                logger.info(
                    f"创建止盈策略订单成功: algoId={algo_id}, "
                    f"币数量={amount}, 合约张数={order_sz}, 止盈价格={take_profit_trigger}"
                )
                return True
            else:
                logger.error(f"创建止盈策略订单失败: {result.get('message', '未知错误')}")
                return False
                
        except Exception as e:
            logger.error(f"创建止盈策略订单时发生错误: {e}", exc_info=True)
            return False
    
    def _create_stop_loss_algo_order(
        self,
        inst_id: str,
        td_mode: str,
        pos_side: str,
        amount: float,
        stop_loss_trigger: float,
        contract_size: float
    ) -> bool:
        """
        创建止损策略订单
        
        Args:
            inst_id: 产品ID
            td_mode: 交易模式
            pos_side: 持仓方向
            amount: 数量（币数量）
            stop_loss_trigger: 止损触发价格
            contract_size: 合约乘数
            
        Returns:
            是否创建成功
        """
        try:
            # 转换币数量为合约张数
            if contract_size != 1.0 and contract_size > 0:
                contracts = amount / contract_size
                contracts = round(contracts, 1)
                order_sz = contracts
            else:
                order_sz = amount
            
            # 调用API创建策略订单
            result = self.api_manager.create_algo_order(
                inst_id=inst_id,
                td_mode=td_mode,
                pos_side=pos_side,
                sz=order_sz,
                stop_loss_trigger=stop_loss_trigger,
                stop_loss_price='-1'  # 市价
            )
            
            if result.get('success', False):
                algo_id = result.get('algo_id', '')
                logger.info(
                    f"创建止损策略订单成功: algoId={algo_id}, "
                    f"币数量={amount}, 合约张数={order_sz}, 止损价格={stop_loss_trigger}"
                )
                return True
            else:
                logger.error(f"创建止损策略订单失败: {result.get('message', '未知错误')}")
                return False
                
        except Exception as e:
            logger.error(f"创建止损策略订单时发生错误: {e}", exc_info=True)
            return False
    
    def set_stop_loss_take_profit(
        self,
        cl_ord_id: str,
        plans: List[Dict[str, Any]]
    ) -> bool:
        """
        设置止盈止损（支持多个，分批止盈止损）
        
        Args:
            cl_ord_id: 客户端订单ID
            plans: 止盈止损计划列表，格式：
                [
                    {"take_profit": 3500.0, "amount": 0.03},
                    {"take_profit": 3600.0, "amount": 0.03},
                    {"stop_loss": 3000.0, "amount": 0.1}
                ]
            
        Returns:
            是否设置成功
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 没有活跃持仓或设置失败
        """
        # 参数验证
        if not cl_ord_id:
            raise ValueError("cl_ord_id不能为空")
        
        if not plans or len(plans) == 0:
            raise ValueError("plans不能为空")
        
        # 检查是否有活跃持仓
        if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
            raise RuntimeError(
                f"没有找到对应的活跃持仓: clOrdId={cl_ord_id}"
            )
        
        # 从数据库查询关联信息，获取symbol
        symbol = None
        with self.db.get_session() as session:
            relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not relations:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}的关联记录")
            
            first_relation = relations[0]
            signal_id = first_relation['signal_id']
            
            # 方法1：优先从order_history查询获取symbol
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if ord_ids:
                sql = text("""
                    SELECT symbol
                    FROM order_history
                    WHERE ord_id = :ord_id
                    LIMIT 1
                """)
                result = session.execute(sql, {'ord_id': ord_ids[0]})
                row = result.fetchone()
                if row:
                    symbol = row[0]
            
            # 方法2：从market_signals获取symbol
            if not symbol and signal_id:
                sql = text("""
                    SELECT symbol
                    FROM market_signals
                    WHERE id = :signal_id
                    LIMIT 1
                """)
                result = session.execute(sql, {'signal_id': signal_id})
                row = result.fetchone()
                if row:
                    symbol = row[0]
        
        # 方法3：从OKX API获取所有持仓
        if not symbol:
            try:
                positions_result = self.api_manager.exchange.private_get_account_positions({})
                
                if positions_result and positions_result.get('code') == '0':
                    positions_data = positions_result.get('data', [])
                    if positions_data:
                        active_positions = [
                            p for p in positions_data 
                            if float(p.get('pos', '0')) != 0
                        ]
                        
                        if len(active_positions) == 1:
                            inst_id = active_positions[0].get('instId', '')
                            if inst_id:
                                parts = inst_id.split('-')
                                if len(parts) > 0:
                                    symbol = parts[0]
                        elif len(active_positions) > 1:
                            logger.warning(f"发现多个活跃持仓，使用第一个持仓的symbol")
                            inst_id = active_positions[0].get('instId', '')
                            if inst_id:
                                parts = inst_id.split('-')
                                if len(parts) > 0:
                                    symbol = parts[0]
            except Exception as e:
                logger.warning(f"从OKX API获取symbol失败: {e}")
        
        if not symbol:
            raise RuntimeError(f"无法获取clOrdId={cl_ord_id}对应的symbol")
        
        # 从OKX API查询当前持仓
        position_info = self._get_current_position_from_okx(symbol)
        pos_side = position_info['pos_side']
        pos = position_info['pos']  # 合约张数
        inst_id = position_info['inst_id']
        avg_px = position_info['avg_px']
        
        # 获取合约信息（用于单位转换）
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        try:
            market = self.api_manager.exchange.market(ccxt_symbol)
            contract_size = market.get('contractSize', 0.1)
        except:
            if 'ETH' in symbol.upper():
                contract_size = 0.1
            else:
                contract_size = 1.0
            logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
        
        # 将合约张数转换为币数量（plans中的amount是币数量）
        pos_amount = pos * contract_size
        
        # 验证plans（使用币数量进行对比）
        self._validate_plans(plans, pos_amount)
        
        # 取消所有未完成的策略订单
        self._cancel_all_pending_algo_orders(inst_id)
        
        # 遍历plans，创建策略订单
        success_count = 0
        for plan in plans:
            if 'take_profit' in plan:
                # 创建止盈订单
                take_profit = float(plan['take_profit'])
                amount = float(plan['amount'])
                
                # 验证止盈价格
                if not self._validate_stop_loss_take_profit(
                    entry_price=avg_px,
                    stop_loss_trigger=None,
                    take_profit_trigger=take_profit,
                    position_side=pos_side
                ):
                    logger.warning(
                        f"止盈价格验证失败: 开仓均价={avg_px}, 止盈={take_profit}, "
                        f"持仓方向={pos_side}，跳过此订单"
                    )
                    continue
                
                if self._create_take_profit_algo_order(
                    inst_id=inst_id,
                    td_mode='cross',
                    pos_side=pos_side,
                    amount=amount,
                    take_profit_trigger=take_profit,
                    contract_size=contract_size
                ):
                    success_count += 1
                    
            elif 'stop_loss' in plan:
                # 创建止损订单
                stop_loss = float(plan['stop_loss'])
                amount = float(plan['amount'])
                
                # 验证止损价格
                if not self._validate_stop_loss_take_profit(
                    entry_price=avg_px,
                    stop_loss_trigger=stop_loss,
                    take_profit_trigger=None,
                    position_side=pos_side
                ):
                    logger.warning(
                        f"止损价格验证失败: 开仓均价={avg_px}, 止损={stop_loss}, "
                        f"持仓方向={pos_side}，跳过此订单"
                    )
                    continue
                
                if self._create_stop_loss_algo_order(
                    inst_id=inst_id,
                    td_mode='cross',
                    pos_side=pos_side,
                    amount=amount,
                    stop_loss_trigger=stop_loss,
                    contract_size=contract_size
                ):
                    success_count += 1
        
        if success_count == 0:
            raise RuntimeError("所有策略订单创建失败")
        
        logger.info(
            f"设置止盈止损成功: clOrdId={cl_ord_id}, "
            f"成功创建{success_count}个策略订单，共{len(plans)}个计划"
        )
        
        return True
    
    # ============================================
    # 加仓方法
    # ============================================
    
    def add_position(
        self,
        cl_ord_id: str,
        amount: float
    ) -> bool:
        """
        加仓（复用原clOrdId，同方向）
        
        Args:
            cl_ord_id: 客户端订单ID
            amount: 加仓数量（绝对值）
            
        Returns:
            是否加仓成功
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 没有活跃持仓或加仓失败
        """
        # 参数验证
        if not cl_ord_id:
            raise ValueError("cl_ord_id不能为空")
        
        if amount <= 0:
            raise ValueError(f"amount必须大于0，当前值: {amount}")
        
        # 检查是否有活跃持仓
        if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
            raise RuntimeError(
                f"没有找到对应的活跃持仓: clOrdId={cl_ord_id}"
            )
        
        # 获取当前持仓方向
        position_side = self.get_current_position_side()
        if not position_side:
            raise RuntimeError("无法获取当前持仓方向")
        
        # 从数据库查询关联信息，获取symbol和signal_id
        with self.db.get_session() as session:
            relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not relations:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}的关联记录")
            
            first_relation = relations[0]
            signal_id = first_relation['signal_id']
            
            # 从order_history查询获取symbol和杠杆
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not ord_ids:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}对应的订单ID")
            
            # 查询第一个订单获取symbol和杠杆
            sql = text("""
                SELECT symbol, inst_id, lever
                FROM order_history
                WHERE ord_id = :ord_id
                LIMIT 1
            """)
            result = session.execute(sql, {'ord_id': ord_ids[0]})
            row = result.fetchone()
            
            if not row:
                raise RuntimeError(f"未找到ordId={ord_ids[0]}的订单记录")
            
            symbol = row[0]
            inst_id = row[1]
            leverage = float(row[2]) if row[2] else 1.0
        
        # 转换symbol格式
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        okx_inst_id = self._symbol_to_okx_format(symbol)
        
        # 转换方向（加仓：同方向）
        okx_side = self._position_side_to_okx_side(position_side)
        okx_pos_side = self._position_side_to_okx_pos_side(position_side)
        
        # 获取合约信息并转换数量
        try:
            market = self.api_manager.exchange.market(ccxt_symbol)
            contract_size = market.get('contractSize', 0.1)
        except:
            if 'ETH' in symbol.upper():
                contract_size = 0.1
            else:
                contract_size = 1.0
            logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
        
        # 将币的数量转换为合约张数
        if contract_size != 1.0 and contract_size > 0:
            contracts = amount / contract_size
            contracts = round(contracts, 1)
            order_amount = contracts
        else:
            order_amount = amount
        
        # 获取当前价格
        current_price = self.api_manager.get_current_price(ccxt_symbol)
        if current_price is None:
            raise RuntimeError(f"无法获取{symbol}的当前价格")
        
        # 构建OKX API参数（复用clOrdId）
        okx_params = {
            'instId': okx_inst_id,
            'tdMode': 'cross',  # 全仓模式
            'side': okx_side,  # 同方向
            'ordType': 'market',  # 市价单
            'sz': str(order_amount),
            'posSide': okx_pos_side,
            'lever': str(int(leverage)),  # 使用原订单的杠杆
            'clOrdId': cl_ord_id  # 复用原clOrdId
        }
        
        logger.debug(f"加仓API参数: {okx_params}")
        
        # 调用OKX API下单
        try:
            if not settings.EXCHANGE_API_KEY:
                raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
            
            result = self.api_manager.exchange.private_post_trade_order(okx_params)
            
            if not result:
                raise RuntimeError("OKX API返回结果为空")
            
            error_code = result.get('code', 'N/A')
            if error_code != '0':
                error_msg = result.get('msg', '未知错误')
                logger.error(f"加仓失败: [{error_code}] {error_msg}")
                raise RuntimeError(f"加仓失败: [{error_code}] {error_msg}")
            
            # 提取订单ID
            order_data_list = result.get('data', [])
            if not order_data_list:
                raise RuntimeError("OKX API返回的订单数据为空")
            
            ord_ids = []
            for order_data in order_data_list:
                ord_id = order_data.get('ordId', '')
                if ord_id:
                    ord_ids.append(ord_id)
                    logger.info(f"加仓订单创建成功: ordId={ord_id}, clOrdId={cl_ord_id}")
            
            if not ord_ids:
                raise RuntimeError("未获取到有效的订单ID")
            
            # 记录trading_relations关联表
            with self.db.get_session() as session:
                for ord_id in ord_ids:
                    # 从order_history查询sz并转换为币数量
                    actual_amount = self._get_amount_from_order_history(
                        session=session,
                        ord_id=ord_id,
                        symbol=symbol,
                        fallback_amount=amount
                    )
                    # 【更新amount日志】trading_manager.py:1273 - 加仓操作
                    logger.info(
                        f"【更新amount】位置: trading_manager.py:1273 (add_position) | "
                        f"操作类型: add | ord_id: {ord_id} | cl_ord_id: {cl_ord_id} | "
                        f"请求数量(币): {amount} | 查询到的acc_fill_sz(合约): {actual_amount / (0.1 if symbol.upper() == 'ETH' else 1.0) if actual_amount > 0 else 0} | "
                        f"最终amount(币): {actual_amount} | 价格: {current_price}"
                    )
                    success = self.trading_relations_repo.insert_relation(
                        session=session,
                        signal_id=signal_id,
                        cl_ord_id=cl_ord_id,
                        operation_type='add',
                        ord_id=ord_id,
                        position_history_id=None,
                        amount=actual_amount,
                        price=current_price
                    )
                    if not success:
                        logger.warning(f"记录trading_relations失败: ordId={ord_id}")
            
            logger.info(
                f"加仓成功: clOrdId={cl_ord_id}, amount={amount}, "
                f"ordIds={ord_ids}"
            )
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if ('401' in error_str or 'Unauthorized' in error_str or
                'apiKey' in error_str or 'credential' in error_str.lower() or
                'authentication' in error_str.lower()):
                logger.error(f"加仓失败（API密钥未配置或无效）: {error_str}")
            else:
                logger.error(f"加仓失败: {error_str}", exc_info=True)
            raise
    
    # ============================================
    # 减仓方法
    # ============================================
    
    def reduce_position(
        self,
        cl_ord_id: str,
        amount: float
    ) -> bool:
        """
        减仓（复用原clOrdId，反向平仓）
        
        Args:
            cl_ord_id: 客户端订单ID
            amount: 减仓数量（绝对值）
            
        Returns:
            是否减仓成功
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 没有活跃持仓或减仓失败
        """
        # 参数验证
        if not cl_ord_id:
            raise ValueError("cl_ord_id不能为空")
        
        if amount <= 0:
            raise ValueError(f"amount必须大于0，当前值: {amount}")
        
        # 检查是否有活跃持仓
        if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
            raise RuntimeError(
                f"没有找到对应的活跃持仓: clOrdId={cl_ord_id}"
            )
        
        # 从数据库查询关联信息，获取symbol和signal_id
        with self.db.get_session() as session:
            relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not relations:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}的关联记录")
            
            first_relation = relations[0]
            signal_id = first_relation['signal_id']
            
            # 从order_history查询获取symbol和杠杆
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not ord_ids:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}对应的订单ID")
            
            # 查询第一个订单获取symbol和杠杆
            sql = text("""
                SELECT symbol, inst_id, lever
                FROM order_history
                WHERE ord_id = :ord_id
                LIMIT 1
            """)
            result = session.execute(sql, {'ord_id': ord_ids[0]})
            row = result.fetchone()
            
            if not row:
                raise RuntimeError(f"未找到ordId={ord_ids[0]}的订单记录")
            
            symbol = row[0]
            inst_id = row[1]
            leverage = float(row[2]) if row[2] else 1.0
        
        # 转换symbol格式
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        okx_inst_id = self._symbol_to_okx_format(symbol)
        
        # 从OKX API查询当前持仓（保证实时）
        try:
            # 使用OKX API查询当前持仓
            positions_result = self.api_manager.exchange.private_get_account_positions({
                'instId': okx_inst_id
            })
            
            if not positions_result or positions_result.get('code') != '0':
                raise RuntimeError(f"查询当前持仓失败: {positions_result.get('msg', '未知错误')}")
            
            positions_data = positions_result.get('data', [])
            if not positions_data:
                raise RuntimeError(f"未找到{symbol}的当前持仓")
            
            # 获取第一个持仓（通常只有一个）
            position = positions_data[0]
            position_direction = position.get('posSide', '')  # long/short
            current_pos_size = float(position.get('pos', '0'))  # 当前持仓数量
            
            if current_pos_size <= 0:
                raise RuntimeError(f"当前持仓数量为0，无法减仓")
            
            # 验证减仓数量不超过当前持仓
            if amount > current_pos_size:
                raise ValueError(
                    f"减仓数量{amount}超过当前持仓{current_pos_size}，无法减仓"
                )
            
            # 确定减仓方向（反向平仓）
            # LONG持仓减仓 = sell, SHORT持仓减仓 = buy
            if position_direction == 'long':
                okx_side = 'sell'  # 反向平仓
                position_side = 'LONG'
            elif position_direction == 'short':
                okx_side = 'buy'  # 反向平仓
                position_side = 'SHORT'
            else:
                raise RuntimeError(f"未知的持仓方向: {position_direction}")
            
            okx_pos_side = position_direction
            
        except Exception as e:
            logger.error(f"查询当前持仓失败: {e}", exc_info=True)
            raise RuntimeError(f"查询当前持仓失败: {e}")
        
        # 获取合约信息并转换数量
        try:
            market = self.api_manager.exchange.market(ccxt_symbol)
            contract_size = market.get('contractSize', 0.1)
        except:
            if 'ETH' in symbol.upper():
                contract_size = 0.1
            else:
                contract_size = 1.0
            logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
        
        # 将币的数量转换为合约张数
        if contract_size != 1.0 and contract_size > 0:
            contracts = amount / contract_size
            contracts = round(contracts, 1)
            order_amount = contracts
        else:
            order_amount = amount
        
        # 获取当前价格
        current_price = self.api_manager.get_current_price(ccxt_symbol)
        if current_price is None:
            raise RuntimeError(f"无法获取{symbol}的当前价格")
        
        # 构建OKX API参数（复用clOrdId，反向平仓）
        okx_params = {
            'instId': okx_inst_id,
            'tdMode': 'cross',  # 全仓模式
            'side': okx_side,  # 反向平仓
            'ordType': 'market',  # 市价单
            'sz': str(order_amount),
            'posSide': okx_pos_side,
            'lever': str(int(leverage)),
            'clOrdId': cl_ord_id  # 复用原clOrdId
        }
        
        logger.debug(f"减仓API参数: {okx_params}")
        
        # 调用OKX API下单
        try:
            if not settings.EXCHANGE_API_KEY:
                raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
            
            result = self.api_manager.exchange.private_post_trade_order(okx_params)
            
            if not result:
                raise RuntimeError("OKX API返回结果为空")
            
            error_code = result.get('code', 'N/A')
            if error_code != '0':
                error_msg = result.get('msg', '未知错误')
                logger.error(f"减仓失败: [{error_code}] {error_msg}")
                raise RuntimeError(f"减仓失败: [{error_code}] {error_msg}")
            
            # 提取订单ID
            order_data_list = result.get('data', [])
            if not order_data_list:
                raise RuntimeError("OKX API返回的订单数据为空")
            
            ord_ids = []
            for order_data in order_data_list:
                ord_id = order_data.get('ordId', '')
                if ord_id:
                    ord_ids.append(ord_id)
                    logger.info(f"减仓订单创建成功: ordId={ord_id}, clOrdId={cl_ord_id}")
            
            if not ord_ids:
                raise RuntimeError("未获取到有效的订单ID")
            
            # 记录trading_relations关联表
            with self.db.get_session() as session:
                for ord_id in ord_ids:
                    # 从order_history查询sz并转换为币数量
                    actual_amount = self._get_amount_from_order_history(
                        session=session,
                        ord_id=ord_id,
                        symbol=symbol,
                        fallback_amount=amount
                    )
                    # 【更新amount日志】trading_manager.py:1504 - 减仓操作
                    logger.info(
                        f"【更新amount】位置: trading_manager.py:1504 (reduce_position) | "
                        f"操作类型: reduce | ord_id: {ord_id} | cl_ord_id: {cl_ord_id} | "
                        f"请求数量(币): {amount} | 查询到的acc_fill_sz(合约): {actual_amount / (0.1 if symbol.upper() == 'ETH' else 1.0) if actual_amount > 0 else 0} | "
                        f"最终amount(币): {actual_amount} | 价格: {current_price}"
                    )
                    success = self.trading_relations_repo.insert_relation(
                        session=session,
                        signal_id=signal_id,
                        cl_ord_id=cl_ord_id,
                        operation_type='reduce',
                        ord_id=ord_id,
                        position_history_id=None,
                        amount=actual_amount,
                        price=current_price
                    )
                    if not success:
                        logger.warning(f"记录trading_relations失败: ordId={ord_id}")
                    else:
                        # 主动尝试更新position_history_id
                        try:
                            self.trading_relations_repo.try_update_position_history_id_by_ord_id(
                                session, ord_id, max_retries=3, retry_delay=1.0
                            )
                        except Exception as e:
                            logger.debug(f"主动更新position_history_id失败 ord_id={ord_id}: {e}")
            
            logger.info(
                f"减仓成功: clOrdId={cl_ord_id}, amount={amount}, "
                f"ordIds={ord_ids}"
            )
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if ('401' in error_str or 'Unauthorized' in error_str or
                'apiKey' in error_str or 'credential' in error_str.lower() or
                'authentication' in error_str.lower()):
                logger.error(f"减仓失败（API密钥未配置或无效）: {error_str}")
            else:
                logger.error(f"减仓失败: {error_str}", exc_info=True)
            raise
    
    # ============================================
    # 平仓方法
    # ============================================
    
    def _get_current_position_from_okx(
        self,
        symbol: str
    ) -> Dict[str, Any]:
        """
        从OKX API查询当前持仓（保证实时）
        
        Args:
            symbol: 币种名称（如BTC、ETH）
            
        Returns:
            持仓信息字典，包含：
            - pos_side: 持仓方向（long/short）
            - pos: 当前持仓数量
            - pos_id: 持仓ID
            - avg_px: 开仓均价
            - lever: 杠杆倍数
            - avail_pos: 可平仓数量
            - upl: 未实现盈亏（API原始值）
            - upl_ratio: 未实现盈亏率
            - mark_px: 标记价格
            - margin: 保证金
            - mgn_ratio: 保证金率
            - notional_usd: 持仓名义价值（美元）
            - mgn_mode: 保证金模式
            - ccy: 占用保证金的币种
            - c_time: 持仓创建时间（毫秒时间戳）
            - u_time: 持仓更新时间（毫秒时间戳）
            - funding_fee: 资金费用
            - algo_id: 策略委托单ID
            
        Raises:
            RuntimeError: 查询失败或没有持仓
        """
        okx_inst_id = self._symbol_to_okx_format(symbol)
        
        try:
            # 使用OKX API查询当前持仓
            positions_result = self.api_manager.exchange.private_get_account_positions({
                'instId': okx_inst_id
            })
            
            if not positions_result or positions_result.get('code') != '0':
                error_msg = positions_result.get('msg', '未知错误') if positions_result else '返回结果为空'
                raise RuntimeError(f"查询当前持仓失败: {error_msg}")
            
            positions_data = positions_result.get('data', [])
            if not positions_data:
                raise RuntimeError(f"未找到{symbol}的当前持仓")
            
            # 获取第一个持仓（通常只有一个）
            position = positions_data[0]
            pos_side = position.get('posSide', '')  # long/short
            pos = float(position.get('pos', '0'))  # 当前持仓数量
            
            if pos <= 0:
                raise RuntimeError(f"当前持仓数量为0")
            
            # 转换数值字段的辅助函数
            def to_float(value, default=0.0):
                """转换为float，如果为空或None则返回默认值"""
                if value is None or value == '':
                    return default
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default
            
            def to_int(value, default=None):
                """转换为int，如果为空或None则返回默认值"""
                if value is None or value == '':
                    return default
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default
            
            return {
                'pos_side': pos_side,
                'pos': pos,
                'pos_id': position.get('posId', ''),
                'avg_px': to_float(position.get('avgPx', '0')),
                'lever': position.get('lever', '1'),
                'inst_id': position.get('instId', ''),
                'avail_pos': to_float(position.get('availPos', '0')),  # 可平仓数量
                'upl': to_float(position.get('upl', '0')),  # 未实现盈亏（API原始值）
                'upl_ratio': to_float(position.get('uplRatio', '0')),  # 未实现盈亏率
                'mark_px': to_float(position.get('markPx', '0')),  # 标记价格
                'margin': to_float(position.get('margin', '0')),  # 保证金
                'mgn_ratio': to_float(position.get('mgnRatio', '0')),  # 保证金率
                'notional_usd': to_float(position.get('notionalUsd', '0')),  # 持仓名义价值（美元）
                'mgn_mode': position.get('mgnMode', ''),  # 保证金模式
                'ccy': position.get('ccy', ''),  # 占用保证金的币种
                'c_time': to_int(position.get('cTime')),  # 持仓创建时间（毫秒时间戳）
                'u_time': to_int(position.get('uTime')),  # 持仓更新时间（毫秒时间戳）
                'funding_fee': to_float(position.get('fundingFee', '0')),  # 资金费用
                'algo_id': position.get('algoId', ''),  # 策略委托单ID
                'raw_data': position
            }
            
        except Exception as e:
            logger.error(f"查询当前持仓失败: {e}", exc_info=True)
            raise RuntimeError(f"查询当前持仓失败: {e}")
    
    def _determine_close_amount(
        self,
        current_position_size: float,
        requested_amount: Optional[float]
    ) -> Tuple[float, bool]:
        """
        判断全部/部分平仓逻辑
        
        Args:
            current_position_size: 当前持仓数量
            requested_amount: 请求平仓数量（None表示全部平仓）
            
        Returns:
            (实际平仓数量, 是否全部平仓) 元组
        """
        if requested_amount is None:
            # 未指定数量，全部平仓
            return current_position_size, True
        
        if requested_amount <= 0:
            raise ValueError(f"平仓数量必须大于0，当前值: {requested_amount}")
        
        if requested_amount > current_position_size:
            # 请求数量 > 当前持仓，自动调整为全部平仓
            logger.warning(
                f"请求平仓数量{requested_amount}超过当前持仓{current_position_size}，"
                f"自动调整为全部平仓"
            )
            return current_position_size, True
        
        # 部分平仓
        return requested_amount, False
    
    def close_position(
        self,
        cl_ord_id: str,
        amount: Optional[float] = None,
        is_system_call: bool = True
    ) -> bool:
        """
        平仓（支持全部/部分平仓）
        
        Args:
            cl_ord_id: 客户端订单ID
            amount: 平仓数量（None=全部平仓，传入值=部分平仓）
            is_system_call: 是否为系统主动调用（True=系统调用，False=外部调用，默认True）
            
        Returns:
            是否平仓成功
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 没有活跃持仓或平仓失败
        """
        # 参数验证
        if not cl_ord_id:
            raise ValueError("cl_ord_id不能为空")
        
        # 检查是否有活跃持仓
        if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
            raise RuntimeError(
                f"没有找到对应的活跃持仓: clOrdId={cl_ord_id}"
            )
        
        # 从数据库查询关联信息，获取symbol和signal_id
        with self.db.get_session() as session:
            relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not relations:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}的关联记录")
            
            first_relation = relations[0]
            signal_id = first_relation['signal_id']
            
            # 从order_history查询获取symbol和杠杆
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not ord_ids:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}对应的订单ID")
            
            # 查询第一个订单获取symbol和杠杆
            sql = text("""
                SELECT symbol, inst_id, lever
                FROM order_history
                WHERE ord_id = :ord_id
                LIMIT 1
            """)
            result = session.execute(sql, {'ord_id': ord_ids[0]})
            row = result.fetchone()
            
            if not row:
                raise RuntimeError(f"未找到ordId={ord_ids[0]}的订单记录")
            
            symbol = row[0]
            inst_id = row[1]
            leverage = float(row[2]) if row[2] else 1.0
        
        # 从OKX API查询当前持仓（保证实时）
        position_info = self._get_current_position_from_okx(symbol)
        current_pos_size_contracts = position_info['pos']  # 合约数量
        pos_side = position_info['pos_side']
        pos_id = position_info['pos_id']
        
        # 转换symbol格式
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        okx_inst_id = self._symbol_to_okx_format(symbol)
        
        # 获取合约信息
        try:
            market = self.api_manager.exchange.market(ccxt_symbol)
            contract_size = market.get('contractSize', 0.1)
        except:
            if 'ETH' in symbol.upper():
                contract_size = 0.1
            else:
                contract_size = 1.0
            logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
        
        # 将合约数量转换为币数量
        current_pos_size_coins = current_pos_size_contracts * contract_size
        
        # 判断全部/部分平仓逻辑（使用币数量）
        close_amount_coins, is_full_close = self._determine_close_amount(
            current_position_size=current_pos_size_coins,
            requested_amount=amount
        )
        
        # 确定平仓方向（反向平仓）
        if pos_side == 'long':
            okx_side = 'sell'  # 反向平仓
        elif pos_side == 'short':
            okx_side = 'buy'  # 反向平仓
        else:
            raise RuntimeError(f"未知的持仓方向: {pos_side}")
        
        # 将币的数量转换为合约张数（用于下单）
        if contract_size != 1.0 and contract_size > 0:
            contracts = close_amount_coins / contract_size
            contracts = round(contracts, 1)
            order_amount = contracts
        else:
            order_amount = close_amount_coins
        
        # 用于后续记录trading_relations的amount（币数量）
        close_amount = close_amount_coins
        
        # 获取当前价格
        current_price = self.api_manager.get_current_price(ccxt_symbol)
        if current_price is None:
            raise RuntimeError(f"无法获取{symbol}的当前价格")
        
        # 构建OKX API参数（复用clOrdId，反向平仓）
        okx_params = {
            'instId': okx_inst_id,
            'tdMode': 'cross',  # 全仓模式
            'side': okx_side,  # 反向平仓
            'ordType': 'market',  # 市价单
            'sz': str(order_amount),
            'posSide': pos_side,
            'lever': str(int(leverage)),
            'clOrdId': cl_ord_id  # 复用原clOrdId
        }
        
        logger.debug(f"平仓API参数: {okx_params}, 全部平仓={is_full_close}")
        
        # 调用OKX API下单
        try:
            if not settings.EXCHANGE_API_KEY:
                raise ValueError("EXCHANGE_API_KEY未配置，无法下单")
            
            result = self.api_manager.exchange.private_post_trade_order(okx_params)
            
            if not result:
                raise RuntimeError("OKX API返回结果为空")
            
            error_code = result.get('code', 'N/A')
            if error_code != '0':
                error_msg = result.get('msg', '未知错误')
                logger.error(f"平仓失败: [{error_code}] {error_msg}")
                raise RuntimeError(f"平仓失败: [{error_code}] {error_msg}")
            
            # 提取订单ID
            order_data_list = result.get('data', [])
            if not order_data_list:
                raise RuntimeError("OKX API返回的订单数据为空")
            
            ord_ids = []
            for order_data in order_data_list:
                ord_id = order_data.get('ordId', '')
                if ord_id:
                    ord_ids.append(ord_id)
                    logger.info(f"平仓订单创建成功: ordId={ord_id}, clOrdId={cl_ord_id}")
            
            if not ord_ids:
                raise RuntimeError("未获取到有效的订单ID")
            
            # 记录trading_relations关联表（包括position_history_id）
            # 注意：平仓时可能还没有position_history记录（因为同步是每30秒一次）
            # 所以先不关联，后续可以通过定时任务或手动更新
            with self.db.get_session() as session:
                # 尝试查询position_history.id（根据pos_id和最新的u_time）
                position_history_id = self.trading_relations_repo.get_position_history_id_by_pos_id(
                    session, pos_id
                )
                
                # 判断是否为全部平仓：需要查询总开仓数量和总平仓数量（包括本次）
                # 如果总平仓数量 >= 总开仓数量（允许1%误差），则为全部平仓
                actual_operation_type = 'close' if is_full_close else 'reduce'
                if is_full_close:
                    # 即使is_full_close=True，也需要验证是否真的全部平仓
                    # 因为可能外部已经部分平仓了，系统平仓时只是平掉了剩余部分
                    try:
                        # 查询总开仓数量
                        get_open_total_sql = text("""
                            SELECT COALESCE(SUM(acc_fill_sz), 0)
                            FROM order_history
                            WHERE cl_ord_id = :cl_ord_id
                              AND side = :open_side
                              AND pos_side = :pos_side
                              AND state = 'filled'
                        """)
                        open_side = 'buy' if pos_side == 'long' else 'sell'
                        open_total_result = session.execute(get_open_total_sql, {
                            'cl_ord_id': cl_ord_id,
                            'open_side': open_side,
                            'pos_side': pos_side
                        }).fetchone()
                        open_total = float(open_total_result[0]) if open_total_result and open_total_result[0] else 0.0
                        
                        # 查询总平仓数量（包括本次系统平仓）
                        close_side = 'sell' if pos_side == 'long' else 'buy'
                        get_close_total_sql = text("""
                            SELECT COALESCE(SUM(acc_fill_sz), 0)
                            FROM order_history
                            WHERE cl_ord_id = :cl_ord_id
                              AND side = :close_side
                              AND pos_side = :pos_side
                              AND state = 'filled'
                        """)
                        close_total_result = session.execute(get_close_total_sql, {
                            'cl_ord_id': cl_ord_id,
                            'close_side': close_side,
                            'pos_side': pos_side
                        }).fetchone()
                        close_total = float(close_total_result[0]) if close_total_result and close_total_result[0] else 0.0
                        
                        # 重要：系统平仓的订单可能还没有同步到order_history表（异步同步）
                        # 所以查询的总平仓数量可能不包含本次订单，需要加上本次平仓数量
                        # 注意：close_amount是币数量，但acc_fill_sz是合约数量，需要转换单位
                        # 将币数量转换为合约数量
                        close_amount_contracts = close_amount / contract_size
                        
                        close_total_with_current = close_total + close_amount_contracts
                        
                        # 判断是否真的全部平仓
                        if open_total > 0:
                            close_ratio = close_total_with_current / open_total
                            # 允许1%的误差
                            if close_ratio >= 0.99:
                                actual_operation_type = 'close'
                            else:
                                actual_operation_type = 'reduce'
                                logger.debug(
                                    f"系统平仓时，虽然is_full_close=True，但总平仓数量({close_total_with_current}) < 总开仓数量({open_total})，"
                                    f"实际为部分平仓，operation_type设为'reduce'"
                                )
                    except Exception as e:
                        logger.warning(f"判断系统平仓operation_type失败，使用默认值: {e}")
                        # 如果查询失败，使用is_full_close的判断结果
                        actual_operation_type = 'close' if is_full_close else 'reduce'
                
                for ord_id in ord_ids:
                    # 从order_history查询acc_fill_sz并转换为币数量
                    actual_amount = self._get_amount_from_order_history(
                        session=session,
                        ord_id=ord_id,
                        symbol=symbol,
                        fallback_amount=close_amount
                    )
                    # 【更新amount日志】trading_manager.py:1932 - 系统平仓操作
                    logger.info(
                        f"【更新amount】位置: trading_manager.py:1932 (close_position) | "
                        f"操作类型: {actual_operation_type} | ord_id: {ord_id} | cl_ord_id: {cl_ord_id} | "
                        f"请求数量(币): {close_amount} | 查询到的acc_fill_sz(合约): {actual_amount / (0.1 if symbol.upper() == 'ETH' else 1.0) if actual_amount > 0 else 0} | "
                        f"最终amount(币): {actual_amount} | 价格: {current_price} | 是否全部平仓: {is_full_close}"
                    )
                    success = self.trading_relations_repo.insert_relation(
                        session=session,
                        signal_id=signal_id,
                        cl_ord_id=cl_ord_id,
                        operation_type=actual_operation_type,
                        ord_id=ord_id,
                        position_history_id=position_history_id,  # 平仓后关联仓位历史ID（如果找到）
                        amount=actual_amount,
                        price=current_price
                    )
                    if not success:
                        logger.warning(f"记录trading_relations失败: ordId={ord_id}")
                    else:
                        # 如果插入时没有position_history_id，主动尝试更新
                        if position_history_id is None:
                            try:
                                updated_id = self.trading_relations_repo.try_update_position_history_id_by_ord_id(
                                    session, ord_id, max_retries=3, retry_delay=1.0
                                )
                                if updated_id:
                                    position_history_id = updated_id
                            except Exception as e:
                                logger.debug(f"主动更新position_history_id失败 ord_id={ord_id}: {e}")
                
                # 如果没有找到position_history_id，记录日志，后续可以通过定时任务更新
                if position_history_id is None:
                    logger.debug(f"平仓时未找到position_history记录，pos_id={pos_id}，后续可通过定时任务更新")
            
            # 如果是全部平仓，清除内存中的clOrdId
            if is_full_close:
                self._clear_current_cl_ord_id()
                logger.info(f"全部平仓完成，已清除内存中的clOrdId: {cl_ord_id}")
            
            logger.info(
                f"平仓成功: clOrdId={cl_ord_id}, amount={close_amount}, "
                f"全部平仓={is_full_close}, ordIds={ord_ids}, posId={pos_id}, "
                f"系统调用={is_system_call}"
            )
            
            return True
            
        except Exception as e:
            error_str = str(e)
            if ('401' in error_str or 'Unauthorized' in error_str or
                'apiKey' in error_str or 'credential' in error_str.lower() or
                'authentication' in error_str.lower()):
                logger.error(f"平仓失败（API密钥未配置或无效）: {error_str}")
            else:
                logger.error(f"平仓失败: {error_str}", exc_info=True)
            raise
    
    # ============================================
    # 外部平仓处理方法
    # ============================================
    
    def handle_external_close_position(
        self,
        pos_id: str,
        cl_ord_id: str,
        close_amount: float,
        close_price: Optional[float] = None,
        is_full_close: bool = False,
        inst_id: Optional[str] = None,
        pos_side: Optional[str] = None,
        u_time: Optional[str] = None
    ) -> bool:
        """
        处理外部平仓（不调用OKX API，只处理业务逻辑）
        
        Args:
            pos_id: 持仓ID（OKX的posId）
            cl_ord_id: 客户端订单ID
            close_amount: 平仓数量（币数量）
            close_price: 平仓价格（markPx）
            is_full_close: 是否完全平仓
            inst_id: 交易对ID（可选，如ETH-USDT-SWAP）
            pos_side: 持仓方向（可选，如long/short）
            u_time: 更新时间（可选，用于精确去重）
            
        Returns:
            是否处理成功
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 不是系统管理的持仓或处理失败
        """
        # 参数验证
        if not pos_id:
            raise ValueError("pos_id不能为空")
        if not cl_ord_id:
            raise ValueError("cl_ord_id不能为空")
        if close_amount <= 0:
            raise ValueError(f"平仓数量必须大于0，当前值: {close_amount}")
        if close_price is not None and close_price <= 0:
            raise ValueError(f"平仓价格必须大于0，当前值: {close_price}")
        
        try:
            # 检查是否系统管理的持仓
            if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
                logger.warning(
                    f"外部平仓检测到非系统管理的持仓: pos_id={pos_id}, "
                    f"cl_ord_id={cl_ord_id}, current_cl_ord_id={self.current_cl_ord_id}"
                )
                return False
            
            # 从数据库查询关联信息，获取signal_id
            with self.db.get_session() as session:
                relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                    session, cl_ord_id
                )
                
                if not relations:
                    logger.warning(f"未找到clOrdId={cl_ord_id}的关联记录")
                    return False
                
                first_relation = relations[0]
                signal_id = first_relation['signal_id']
                
                # 检查是否已处理（改进的去重逻辑）
                # 1. 如果有u_time，通过position_history查询是否有相同的(pos_id, c_time)记录
                # 2. 如果没有u_time或position_history中没有记录，检查是否有相同的ord_id（如果有订单的话）
                # 3. 如果都没有，检查30秒内相同operation_type且amount相近的记录（作为最后的fallback）
                operation_type = 'close' if is_full_close else 'reduce'
                already_processed = False
                
                if u_time:
                    # 方法1：通过position_history查询是否有相同的(pos_id, c_time)记录
                    # 先查询该pos_id对应的c_time（开仓时间），然后检查是否有相同的(pos_id, c_time)记录
                    # 如果position_history中有相同的(pos_id, c_time)，说明这个平仓事件已经处理过
                    try:
                        u_time_int = int(u_time) if u_time else 0
                        if u_time_int > 0:
                            # 先查询该pos_id对应的最新记录的c_time
                            get_c_time_sql = text("""
                                SELECT c_time_ms
                                FROM position_history
                                WHERE pos_id = :pos_id
                                ORDER BY u_time DESC
                                LIMIT 1
                            """)
                            c_time_result = session.execute(get_c_time_sql, {
                                'pos_id': pos_id
                            }).fetchone()
                            
                            if c_time_result and c_time_result[0]:
                                c_time_ms = c_time_result[0]
                                # 检查是否有相同的(pos_id, c_time)记录且已关联到trading_relations
                                check_sql = text("""
                                    SELECT COUNT(*) 
                                    FROM position_history ph
                                    JOIN trading_relations tr ON tr.position_history_id = ph.id
                                    WHERE ph.pos_id = :pos_id
                                      AND ph.c_time_ms = :c_time_ms
                                      AND tr.cl_ord_id = :cl_ord_id
                                      AND tr.operation_type = :operation_type
                                """)
                                check_result = session.execute(check_sql, {
                                    'pos_id': pos_id,
                                    'c_time_ms': c_time_ms,
                                    'cl_ord_id': cl_ord_id,
                                    'operation_type': operation_type
                                }).fetchone()
                                
                                if check_result and check_result[0] > 0:
                                    already_processed = True
                                    logger.debug(
                                        f"外部平仓已处理过（通过position_history检查）: cl_ord_id={cl_ord_id}, "
                                        f"operation_type={operation_type}, pos_id={pos_id}, c_time_ms={c_time_ms}"
                                    )
                    except Exception as e:
                        logger.debug(f"通过position_history检查去重失败: {e}")
                
                if not already_processed:
                    # 方法2：检查是否有相同的ord_id（如果有订单的话）
                    # 先尝试查询最近的平仓订单
                    if inst_id and pos_side:
                        try:
                            close_side = 'sell' if pos_side == 'long' else 'buy'
                            query_sql = text("""
                                SELECT ord_id
                                FROM order_history
                                WHERE cl_ord_id = :cl_ord_id
                                  AND side = :close_side
                                  AND pos_side = :pos_side
                                  AND state IN ('filled', 'partially_filled')
                                ORDER BY fill_time DESC NULLS LAST, u_time DESC
                                LIMIT 1
                            """)
                            query_result = session.execute(query_sql, {
                                'cl_ord_id': cl_ord_id,
                                'close_side': close_side,
                                'pos_side': pos_side
                            }).fetchone()
                            
                            if query_result and query_result[0]:
                                ord_id_found = query_result[0]
                                # 检查该ord_id是否已经在trading_relations中
                                check_ord_sql = text("""
                                    SELECT id
                                    FROM trading_relations
                                    WHERE ord_id = :ord_id
                                    LIMIT 1
                                """)
                                check_ord_result = session.execute(check_ord_sql, {
                                    'ord_id': ord_id_found
                                }).fetchone()
                                
                                if check_ord_result:
                                    already_processed = True
                                    logger.debug(
                                        f"外部平仓已处理过（通过ord_id检查）: cl_ord_id={cl_ord_id}, "
                                        f"operation_type={operation_type}, pos_id={pos_id}, ord_id={ord_id_found}"
                                    )
                        except Exception as e:
                            logger.debug(f"通过ord_id检查去重失败: {e}")
                
                if not already_processed:
                    # 方法3：如果没有查询到订单，检查最近的外部平仓记录（没有ord_id的记录）
                    # 使用更精确的判断：检查最近30秒内是否有相同operation_type且amount相近的记录
                    # 这样可以避免误跳过不同的外部平仓
                    from datetime import datetime, timezone, timedelta
                    thirty_seconds_ago = datetime.now(timezone.utc) - timedelta(seconds=30)
                    
                    sql = text("""
                        SELECT id, created_at, amount
                        FROM trading_relations
                        WHERE cl_ord_id = :cl_ord_id
                          AND operation_type = :operation_type
                          AND created_at >= :thirty_seconds_ago
                          AND (ord_id IS NULL OR ord_id = '')
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    result = session.execute(sql, {
                        'cl_ord_id': cl_ord_id,
                        'operation_type': operation_type,
                        'thirty_seconds_ago': thirty_seconds_ago
                    }).fetchone()
                    
                    if result:
                        # 检查amount是否相近（允许1%误差），如果相近，可能是重复的外部平仓
                        prev_amount = float(result[2]) if result[2] else 0.0
                        amount_diff = abs(close_amount - prev_amount)
                        amount_ratio = amount_diff / close_amount if close_amount > 0 else 1.0
                        
                        if amount_ratio < 0.01:  # 数量差异小于1%，可能是重复
                            already_processed = True
                            logger.info(
                                f"外部平仓已处理过（30秒内相同operation_type且amount相近）: "
                                f"cl_ord_id={cl_ord_id}, operation_type={operation_type}, pos_id={pos_id}, "
                                f"当前amount={close_amount}, 已存在amount={prev_amount}, 差异={amount_ratio*100:.2f}%"
                            )
                        else:
                            logger.debug(
                                f"外部平仓数量不同，继续处理: cl_ord_id={cl_ord_id}, "
                                f"当前amount={close_amount}, 已存在amount={prev_amount}, 差异={amount_ratio*100:.2f}%"
                            )
                
                # 如果已经通过精确方法判断为已处理，直接返回
                if already_processed:
                    # 【去重日志】trading_manager.py:2200 - 外部平仓去重检查
                    logger.info(
                        f"【去重检查】位置: trading_manager.py:2200 (handle_external_close_position) | "
                        f"外部平仓已处理过，跳过: cl_ord_id={cl_ord_id}, operation_type={operation_type}, "
                        f"pos_id={pos_id}, u_time={u_time or 'None'}"
                    )
                    return True
                
                # 尝试查询position_history.id（根据pos_id）
                position_history_id = self.trading_relations_repo.get_position_history_id_by_pos_id(
                    session, pos_id
                )
                
                # 从position_history查询平仓信息（可选，用于验证）
                close_total_pos = None
                close_avg_px = None
                if position_history_id:
                    sql = text("""
                        SELECT close_total_pos, close_avg_px
                        FROM position_history
                        WHERE id = :position_history_id
                    """)
                    result = session.execute(sql, {'position_history_id': position_history_id}).fetchone()
                    if result:
                        close_total_pos = float(result[0]) if result[0] else None
                        close_avg_px = float(result[1]) if result[1] else None
                
                # 尝试查询最近的平仓订单（外部平仓可能通过订单WebSocket或API拉取检测到）
                actual_amount = close_amount
                ord_id_for_relation = None
                if inst_id and pos_side:
                    # 确定平仓方向
                    close_side = 'sell' if pos_side == 'long' else 'buy'
                    try:
                        # 查询最近的平仓订单
                        query_sql = text("""
                            SELECT ord_id, sz, symbol
                            FROM order_history
                            WHERE cl_ord_id = :cl_ord_id
                              AND side = :close_side
                              AND pos_side = :pos_side
                              AND state IN ('filled', 'partially_filled')
                            ORDER BY fill_time DESC NULLS LAST, u_time DESC
                            LIMIT 1
                        """)
                        query_result = session.execute(query_sql, {
                            'cl_ord_id': cl_ord_id,
                            'close_side': close_side,
                            'pos_side': pos_side
                        }).fetchone()
                        
                        if query_result and query_result[0]:
                            ord_id_for_relation = query_result[0]
                            sz_contracts = float(query_result[1]) if query_result[1] else 0.0
                            result_symbol = query_result[2] if len(query_result) > 2 else None
                            
                            # 转换为币数量
                            contract_size = 0.1 if (result_symbol or '').upper() == 'ETH' else 1.0
                            actual_amount = sz_contracts * contract_size
                            logger.debug(f"外部平仓找到订单: ord_id={ord_id_for_relation}, sz={sz_contracts}, amount={actual_amount}")
                        else:
                            # 查询不到订单，使用close_amount作为fallback（注意：close_amount可能是合约数量）
                            logger.warning(
                                f"外部平仓查询不到订单，使用close_amount作为fallback: "
                                f"cl_ord_id={cl_ord_id}, close_amount={close_amount}, "
                                f"注意：close_amount可能是合约数量，需要转换"
                            )
                    except Exception as e:
                        logger.debug(f"查询外部平仓订单失败: {e}，使用close_amount={close_amount}")
                
                # 【更新amount日志】trading_manager.py:2131 - 外部平仓操作
                logger.info(
                    f"【更新amount】位置: trading_manager.py:2131 (handle_external_close_position) | "
                    f"操作类型: {operation_type} | ord_id: {ord_id_for_relation or 'None'} | cl_ord_id: {cl_ord_id} | "
                    f"pos_id: {pos_id} | 传入close_amount(可能是合约数量): {close_amount} | "
                    f"查询到的sz(合约): {actual_amount / (0.1 if (inst_id or '').upper().startswith('ETH') else 1.0) if actual_amount > 0 else 0} | "
                    f"最终amount(币): {actual_amount} | 价格: {close_price} | 是否全部平仓: {is_full_close}"
                )
                # 记录到trading_relations表
                success = self.trading_relations_repo.insert_relation(
                    session=session,
                    signal_id=signal_id,
                    cl_ord_id=cl_ord_id,
                    operation_type=operation_type,
                    ord_id=ord_id_for_relation,  # 如果找到订单ID则使用，否则为None
                    position_history_id=position_history_id,
                    amount=actual_amount,
                    price=close_price
                )
                
                if not success:
                    logger.error(f"记录外部平仓到trading_relations失败: cl_ord_id={cl_ord_id}, pos_id={pos_id}")
                    return False
                
                session.commit()
                
                # 如果没有找到position_history_id，记录日志
                if position_history_id is None:
                    logger.debug(
                        f"外部平仓时未找到position_history记录，pos_id={pos_id}，"
                        f"后续可通过定时任务更新"
                    )
            
            # 更新内存状态
            if is_full_close:
                # 完全平仓：清除内存中的clOrdId
                self._clear_current_cl_ord_id()
                logger.info(f"外部完全平仓处理完成，已清除内存中的clOrdId: {cl_ord_id}")
            else:
                # 部分平仓：更新持仓数量
                # 计算新的持仓数量：当前数量 - 平仓数量
                if self.current_position_amount is not None:
                    new_amount = self.current_position_amount - close_amount
                    if new_amount > 0:
                        self._update_position_amount(new_amount)
                        logger.info(
                            f"外部部分平仓处理完成: cl_ord_id={cl_ord_id}, "
                            f"平仓数量={close_amount}, 剩余持仓={new_amount}"
                        )
                    else:
                        # 如果部分平仓后数量<=0，当作全部平仓处理
                        self._clear_current_cl_ord_id()
                        logger.warning(
                            f"外部部分平仓后持仓数量异常，当作全部平仓处理: cl_ord_id={cl_ord_id}, "
                            f"当前数量={self.current_position_amount}, 平仓数量={close_amount}, "
                            f"计算结果={new_amount}"
                        )
                else:
                    logger.warning(
                        f"外部部分平仓时无法更新持仓数量: cl_ord_id={cl_ord_id}, "
                        f"current_position_amount为None"
                    )
            
            logger.info(
                f"外部平仓处理成功: cl_ord_id={cl_ord_id}, pos_id={pos_id}, "
                f"平仓数量={close_amount}, 平仓价格={close_price}, "
                f"完全平仓={is_full_close}, position_history_id={position_history_id}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"处理外部平仓失败: cl_ord_id={cl_ord_id}, pos_id={pos_id}, 错误: {e}", exc_info=True)
            return False
    
    # ============================================
    # 查询方法
    # ============================================
    
    def _find_cl_ord_id_by_pos_id(
        self,
        pos_id: str,
        inst_id: Optional[str] = None,
        pos_side: Optional[str] = None
    ) -> Optional[str]:
        """
        根据pos_id查找cl_ord_id
        
        查找路径（按优先级）：
        1. 方案A：pos_id → position_history.id → trading_relations.position_history_id → trading_relations.cl_ord_id
        2. 方案B：inst_id + pos_side + 时间 → trading_relations（最近的开仓记录）
        3. 方案C：内存中的current_cl_ord_id（如果持仓方向匹配）
        
        Args:
            pos_id: 持仓ID（OKX的posId）
            inst_id: 交易对ID（可选，如ETH-USDT-SWAP）
            pos_side: 持仓方向（可选，如long/short）
            
        Returns:
            cl_ord_id，如果未找到则返回None
        """
        if not pos_id:
            return None
        
        try:
            with self.db.get_session() as session:
                # 方案A：通过position_history查找
                position_history_id = self.trading_relations_repo.get_position_history_id_by_pos_id(
                    session, pos_id
                )
                
                if position_history_id:
                    # 通过position_history_id查找trading_relations
                    sql = text("""
                        SELECT cl_ord_id
                        FROM trading_relations
                        WHERE position_history_id = :position_history_id
                        ORDER BY created_at DESC
                        LIMIT 1
                    """)
                    result = session.execute(sql, {'position_history_id': position_history_id}).fetchone()
                    if result and result[0]:
                        cl_ord_id = result[0]
                        logger.debug(f"通过position_history找到cl_ord_id: {cl_ord_id}, pos_id={pos_id}")
                        return cl_ord_id
                
                # 方案B：通过inst_id + pos_side + 时间查找（如果提供了inst_id和pos_side）
                if inst_id and pos_side:
                    # 从inst_id提取symbol（如ETH-USDT-SWAP -> ETH）
                    symbol = inst_id.split('-')[0] if '-' in inst_id else None
                    
                    if symbol:
                        # 转换pos_side格式（long -> LONG, short -> SHORT）
                        pos_side_upper = pos_side.upper()
                        if pos_side_upper in ['LONG', 'SHORT']:
                            # 查找最近的开仓记录（operation_type='open'）
                            # 通过order_history表关联，因为order_history有inst_id和pos_side
                            sql = text("""
                                SELECT tr.cl_ord_id
                                FROM trading_relations tr
                                INNER JOIN order_history oh ON tr.ord_id = oh.ord_id
                                WHERE tr.operation_type = 'open'
                                  AND oh.inst_id = :inst_id
                                  AND oh.pos_side = :pos_side
                                ORDER BY tr.created_at DESC
                                LIMIT 1
                            """)
                            result = session.execute(sql, {
                                'inst_id': inst_id,
                                'pos_side': pos_side.lower()
                            }).fetchone()
                            if result and result[0]:
                                cl_ord_id = result[0]
                                logger.debug(f"通过inst_id+pos_side找到cl_ord_id: {cl_ord_id}, pos_id={pos_id}")
                                return cl_ord_id
                
                # 方案C：检查内存中的current_cl_ord_id（如果持仓方向匹配）
                if self.current_cl_ord_id and pos_side:
                    # 检查持仓方向是否匹配
                    current_side = self.current_position_side
                    if current_side:
                        pos_side_upper = pos_side.upper()
                        current_side_upper = current_side.upper()
                        # long对应LONG，short对应SHORT
                        if ((pos_side_upper == 'LONG' and current_side_upper == 'LONG') or
                            (pos_side_upper == 'SHORT' and current_side_upper == 'SHORT')):
                            logger.debug(f"通过内存current_cl_ord_id找到: {self.current_cl_ord_id}, pos_id={pos_id}")
                            return self.current_cl_ord_id
                
                logger.warning(f"未找到cl_ord_id: pos_id={pos_id}, inst_id={inst_id}, pos_side={pos_side}")
                return None
                
        except Exception as e:
            logger.error(f"查找cl_ord_id失败: pos_id={pos_id}, 错误: {e}", exc_info=True)
            return None
    
    def get_order_status(
        self,
        cl_ord_id: str
    ) -> Dict[str, Any]:
        """
        查询订单状态（通过clOrdId）
        
        Args:
            cl_ord_id: 客户端订单ID
            
        Returns:
            订单状态信息字典，包含：
            - cl_ord_id: 客户端订单ID
            - ord_ids: 订单ID列表（OKX可能拆单）
            - orders: 订单详情列表
            - total_filled: 总成交数量
            - total_amount: 总订单数量
            - status: 整体状态（open/closed/partially_filled）
            
        Raises:
            RuntimeError: 查询失败
        """
        # 从数据库查询所有关联的订单ID
        with self.db.get_session() as session:
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not ord_ids:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}对应的订单ID")
            
            # 从数据库查询订单信息
            from app.database.order_history import OrderHistoryRepository
            orders = []
            total_filled = 0.0
            total_amount = 0.0
            
            for ord_id in ord_ids:
                sql = text("""
                    SELECT 
                        ord_id, cl_ord_id, symbol, inst_id, ord_type, side, pos_side,
                        sz, acc_fill_sz, fill_px, avg_px, state,
                        c_time, u_time
                    FROM order_history
                    WHERE ord_id = :ord_id
                    ORDER BY c_time DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'ord_id': ord_id})
                row = result.fetchone()
                
                if row:
                    order_info = {
                        'ord_id': row[0],
                        'cl_ord_id': row[1],
                        'symbol': row[2],
                        'inst_id': row[3],
                        'ord_type': row[4],
                        'side': row[5],
                        'pos_side': row[6],
                        'sz': float(row[7]) if row[7] else 0.0,
                        'acc_fill_sz': float(row[8]) if row[8] else 0.0,
                        'fill_px': float(row[9]) if row[9] else None,
                        'avg_px': float(row[10]) if row[10] else None,
                        'state': row[11],
                        'c_time': row[12],
                        'u_time': row[13]
                    }
                    orders.append(order_info)
                    total_filled += order_info['acc_fill_sz']
                    total_amount += order_info['sz']
        
        # 判断整体状态
        if total_filled <= 0:
            status = 'open'
        elif total_filled >= total_amount:
            status = 'closed'
        else:
            status = 'partially_filled'
        
        return {
            'cl_ord_id': cl_ord_id,
            'ord_ids': ord_ids,
            'orders': orders,
            'total_filled': total_filled,
            'total_amount': total_amount,
            'status': status
        }
    
    def get_current_position(
        self,
        cl_ord_id: str
    ) -> Dict[str, Any]:
        """
        查询当前持仓（通过clOrdId，从OKX API实时查询）
        
        Args:
            cl_ord_id: 客户端订单ID
            
        Returns:
            持仓信息字典，包含：
            - cl_ord_id: 客户端订单ID
            - symbol: 币种名称
            - pos_side: 持仓方向（long/short）
            - pos: 当前持仓数量
            - pos_id: 持仓ID
            - avg_px: 开仓均价
            - lever: 杠杆倍数
            - current_price: 当前价格
            - unrealized_pnl: 未实现盈亏（手动计算，如果有）
            - avail_pos: 可平仓数量
            - upl: 未实现盈亏（API原始值）
            - upl_ratio: 未实现盈亏率
            - mark_px: 标记价格
            - margin: 保证金
            - mgn_ratio: 保证金率
            - notional_usd: 持仓名义价值（美元）
            - mgn_mode: 保证金模式
            - ccy: 占用保证金的币种
            - c_time: 持仓创建时间（毫秒时间戳）
            - u_time: 持仓更新时间（毫秒时间戳）
            - funding_fee: 资金费用
            - inst_id: 产品ID
            - algo_id: 策略委托单ID
            
        Raises:
            RuntimeError: 查询失败或没有持仓
        """
        # 检查是否有活跃持仓
        if not self.has_active_position() or self.current_cl_ord_id != cl_ord_id:
            raise RuntimeError(
                f"没有找到对应的活跃持仓: clOrdId={cl_ord_id}"
            )
        
        # 从数据库查询获取symbol（优先从order_history，如果不存在则从market_signals获取）
        symbol = None
        with self.db.get_session() as session:
            relations = self.trading_relations_repo.get_relations_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if not relations:
                raise RuntimeError(f"未找到clOrdId={cl_ord_id}的关联记录")
            
            first_relation = relations[0]
            signal_id = first_relation['signal_id']
            
            # 方法1：优先从order_history查询获取symbol（如果订单已同步）
            ord_ids = self.trading_relations_repo.get_ord_ids_by_cl_ord_id(
                session, cl_ord_id
            )
            
            if ord_ids:
                sql = text("""
                    SELECT symbol
                    FROM order_history
                    WHERE ord_id = :ord_id
                    LIMIT 1
                """)
                result = session.execute(sql, {'ord_id': ord_ids[0]})
                row = result.fetchone()
                if row:
                    symbol = row[0]
            
            # 方法2：如果order_history中没有，从market_signals获取symbol
            if not symbol and signal_id:
                sql = text("""
                    SELECT symbol
                    FROM market_signals
                    WHERE id = :signal_id
                    LIMIT 1
                """)
                result = session.execute(sql, {'signal_id': signal_id})
                row = result.fetchone()
                if row:
                    symbol = row[0]
        
        # 方法3：如果前两种方法都失败，直接从OKX API获取所有持仓，然后从inst_id提取symbol
        if not symbol:
            try:
                # 调用OKX API获取所有持仓（不传instId参数）
                positions_result = self.api_manager.exchange.private_get_account_positions({})
                
                if positions_result and positions_result.get('code') == '0':
                    positions_data = positions_result.get('data', [])
                    if positions_data:
                        # 找到所有有持仓的（pos != 0）
                        active_positions = []
                        for position in positions_data:
                            pos = float(position.get('pos', '0'))
                            if pos != 0:
                                active_positions.append(position)
                        
                        if len(active_positions) == 1:
                            # 如果只有一个活跃持仓，使用它
                            inst_id = active_positions[0].get('instId', '')
                            if inst_id:
                                # 从instId提取symbol（例如：ETH-USDT-SWAP -> ETH）
                                parts = inst_id.split('-')
                                if len(parts) > 0:
                                    symbol = parts[0]
                                    logger.debug(f"从OKX API获取symbol成功: {symbol}（通过唯一活跃持仓）")
                        elif len(active_positions) > 1:
                            # 如果有多个活跃持仓，尝试根据trading_relations中的信息匹配
                            # 或者使用第一个（因为系统设计是一次只能开一单，这种情况应该很少见）
                            logger.warning(f"发现多个活跃持仓，使用第一个持仓的symbol")
                            inst_id = active_positions[0].get('instId', '')
                            if inst_id:
                                parts = inst_id.split('-')
                                if len(parts) > 0:
                                    symbol = parts[0]
                        else:
                            # 没有活跃持仓
                            logger.warning(f"从OKX API获取所有持仓，但没有找到活跃持仓")
            except Exception as e:
                logger.warning(f"从OKX API获取symbol失败: {e}")
        
        # 如果仍然没有symbol，报错
        if not symbol:
            raise RuntimeError(f"无法获取clOrdId={cl_ord_id}对应的symbol，请检查订单是否已同步或信号是否存在")
        
        # 从OKX API查询当前持仓（保证实时）
        position_info = self._get_current_position_from_okx(symbol)
        
        # 获取当前价格（用于计算未实现盈亏）
        ccxt_symbol = self._symbol_to_ccxt_format(symbol)
        current_price = self.api_manager.get_current_price(ccxt_symbol)
        
        # 计算未实现盈亏（如果有持仓）
        unrealized_pnl = None
        if position_info['pos'] > 0 and current_price:
            avg_px = position_info['avg_px']
            if avg_px > 0:
                if position_info['pos_side'] == 'long':
                    # LONG持仓：未实现盈亏 = (当前价 - 开仓均价) * 持仓数量
                    unrealized_pnl = (current_price - avg_px) * position_info['pos']
                elif position_info['pos_side'] == 'short':
                    # SHORT持仓：未实现盈亏 = (开仓均价 - 当前价) * 持仓数量
                    unrealized_pnl = (avg_px - current_price) * position_info['pos']
        
        return {
            'cl_ord_id': cl_ord_id,
            'symbol': symbol,
            'pos_side': position_info['pos_side'],
            'pos': position_info['pos'],
            'pos_id': position_info['pos_id'],
            'avg_px': position_info['avg_px'],
            'lever': position_info['lever'],
            'current_price': current_price,
            'unrealized_pnl': unrealized_pnl,
            'inst_id': position_info['inst_id'],
            'avail_pos': position_info.get('avail_pos', 0.0),  # 可平仓数量
            'upl': position_info.get('upl', 0.0),  # 未实现盈亏（API原始值）
            'upl_ratio': position_info.get('upl_ratio', 0.0),  # 未实现盈亏率
            'mark_px': position_info.get('mark_px', 0.0),  # 标记价格
            'margin': position_info.get('margin', 0.0),  # 保证金
            'mgn_ratio': position_info.get('mgn_ratio', 0.0),  # 保证金率
            'notional_usd': position_info.get('notional_usd', 0.0),  # 持仓名义价值（美元）
            'mgn_mode': position_info.get('mgn_mode', ''),  # 保证金模式
            'ccy': position_info.get('ccy', ''),  # 占用保证金的币种
            'c_time': position_info.get('c_time'),  # 持仓创建时间（毫秒时间戳）
            'u_time': position_info.get('u_time'),  # 持仓更新时间（毫秒时间戳）
            'funding_fee': position_info.get('funding_fee', 0.0),  # 资金费用
            'algo_id': position_info.get('algo_id', '')  # 策略委托单ID
        }

