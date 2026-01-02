"""
OKX历史订单数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
import json
from app.database.connection import db
from app.utils.logger import logger


class OrderHistoryRepository:
    """OKX历史订单数据仓库"""
    
    @staticmethod
    def extract_symbol_from_inst_id(inst_id: str) -> str:
        """
        从instId提取币种名称
        例如：BTC-USDT-SWAP -> BTC
        
        Args:
            inst_id: 产品ID
            
        Returns:
            币种名称
        """
        if not inst_id:
            return ''
        # 分割instId，取第一部分作为币种
        parts = inst_id.split('-')
        if len(parts) > 0:
            return parts[0]
        return ''
    
    @staticmethod
    def parse_timestamp_ms(timestamp_ms: str) -> Tuple[Optional[int], Optional[datetime]]:
        """
        解析毫秒时间戳，返回时间戳和格式化时间
        
        Args:
            timestamp_ms: 毫秒时间戳字符串
            
        Returns:
            (时间戳毫秒, 格式化时间) 元组
        """
        try:
            if not timestamp_ms:
                return None, None
            ts_ms = int(timestamp_ms)
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            return ts_ms, dt
        except (ValueError, TypeError) as e:
            logger.warning(f"解析时间戳失败: {timestamp_ms}, 错误: {e}")
            return None, None
    
    @staticmethod
    def insert_order(
        session: Session,
        order_data: Dict[str, Any],
        raw_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        插入历史订单数据
        
        Args:
            session: 数据库会话
            order_data: 订单数据（OKX API返回的订单对象）
            raw_data: 完整原始JSON数据（可选，如果不提供则使用order_data）
            
        Returns:
            是否插入成功
        """
        try:
            # 提取字段
            ord_id = order_data.get('ordId', '')
            if not ord_id:
                logger.warning("订单数据缺少ordId，跳过插入")
                return False
            
            # 从instId提取symbol
            inst_id = order_data.get('instId', '')
            symbol = OrderHistoryRepository.extract_symbol_from_inst_id(inst_id)
            
            # 解析时间戳
            c_time_ms, c_time = OrderHistoryRepository.parse_timestamp_ms(order_data.get('cTime', ''))
            u_time_ms, u_time = OrderHistoryRepository.parse_timestamp_ms(order_data.get('uTime', ''))
            fill_time_ms, fill_time = OrderHistoryRepository.parse_timestamp_ms(order_data.get('fillTime', ''))
            
            # 获取cl_ord_id，如果为空且是平仓订单，尝试关联
            cl_ord_id = order_data.get('clOrdId')
            if not cl_ord_id:
                # 如果是平仓订单（reduceOnly=true 或 side与pos_side反向），尝试关联cl_ord_id
                side = order_data.get('side', '').lower()
                pos_side = order_data.get('posSide', '').lower()
                reduce_only = order_data.get('reduceOnly', 'false').lower() == 'true'
                
                is_close_order = (
                    reduce_only or
                    (side == 'sell' and pos_side == 'long') or
                    (side == 'buy' and pos_side == 'short')
                )
                
                if is_close_order and fill_time_ms:
                    # 尝试根据时间范围查找对应的cl_ord_id
                    # 查找规则：在订单时间之前，有相同symbol和pos_side的未完全平仓的开仓订单
                    # 重要：只查找平仓订单之前的开仓订单，避免匹配到错误的开仓订单
                    try:
                        from datetime import datetime, timezone, timedelta
                        fill_time_dt = datetime.fromtimestamp(fill_time_ms / 1000.0, tz=timezone.utc)
                        # 只查找平仓订单之前的开仓订单，时间窗口限制在30分钟内（避免匹配到太早的开仓订单）
                        time_window_start = fill_time_dt - timedelta(minutes=30)
                        
                        # 查找在时间窗口内，相同symbol和pos_side的开仓订单（buy+long 或 sell+short）
                        # 重要：只查找平仓订单之前的开仓订单（fill_time < 平仓订单的fill_time）
                        # 并且该开仓订单还没有完全平仓（通过检查trading_relations和order_history判断）
                        open_side = 'buy' if pos_side == 'long' else 'sell'
                        close_side = 'sell' if pos_side == 'long' else 'buy'
                        lookup_sql = text("""
                            SELECT oh.cl_ord_id
                            FROM order_history oh
                            WHERE oh.symbol = :symbol
                              AND oh.side = :open_side
                              AND oh.pos_side = :pos_side
                              AND oh.cl_ord_id IS NOT NULL
                              AND oh.cl_ord_id != ''
                              AND oh.fill_time >= :time_window_start
                              AND oh.fill_time < :fill_time
                              AND oh.ord_id != :current_ord_id
                              AND NOT EXISTS (
                                  -- 检查该开仓订单是否已经完全平仓（通过trading_relations）
                                  SELECT 1 FROM trading_relations tr
                                  WHERE tr.cl_ord_id = oh.cl_ord_id
                                    AND tr.operation_type = 'close'
                              )
                              AND NOT EXISTS (
                                  -- 检查该开仓订单是否已经完全平仓（通过order_history计算）
                                  -- 如果平仓总数量 >= 开仓总数量（允许1%误差），则认为已经完全平仓
                                  -- 注意：这里计算的是所有已关联的平仓订单总数量，包括当前时间之前的平仓订单
                                  SELECT 1
                                  FROM (
                                      SELECT 
                                          (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                           FROM order_history 
                                           WHERE cl_ord_id = oh.cl_ord_id 
                                             AND side = :open_side 
                                             AND pos_side = :pos_side 
                                             AND state = 'filled') as open_total,
                                          (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                           FROM order_history 
                                           WHERE cl_ord_id = oh.cl_ord_id 
                                             AND side = :close_side 
                                             AND pos_side = :pos_side 
                                             AND state = 'filled'
                                             AND fill_time < :fill_time) as close_total
                                  ) totals
                                  WHERE totals.open_total > 0
                                    AND totals.close_total / totals.open_total >= 0.99
                              )
                            ORDER BY oh.fill_time DESC
                            LIMIT 1
                        """)
                        lookup_result = session.execute(lookup_sql, {
                            'symbol': symbol,
                            'open_side': open_side,
                            'pos_side': pos_side,
                            'time_window_start': time_window_start,
                            'fill_time': fill_time_dt,
                            'current_ord_id': ord_id
                        }).fetchone()
                        
                        if lookup_result and lookup_result[0]:
                            cl_ord_id = lookup_result[0]
                            logger.debug(
                                f"为外部平仓订单关联cl_ord_id: ordId={ord_id}, "
                                f"cl_ord_id={cl_ord_id}, fill_time={fill_time_dt}"
                            )
                    except Exception as e:
                        logger.debug(f"尝试关联外部平仓订单的cl_ord_id失败: {e}")
            
            # 如果没有提供raw_data，使用order_data
            if raw_data is None:
                raw_data = order_data
            
            sql = text("""
                INSERT INTO order_history (
                    ord_id, cl_ord_id, tag, inst_id, symbol, inst_type, ord_type, category,
                    sz, px, side, pos_side, td_mode, lever,
                    acc_fill_sz, fill_px, fill_time_ms, fill_time, trade_id, avg_px, state,
                    tp_trigger_px, tp_ord_px, sl_trigger_px, sl_ord_px,
                    fee, fee_ccy, rebate, rebate_ccy, pnl,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data
                )
                VALUES (
                    :ord_id, :cl_ord_id, :tag, :inst_id, :symbol, :inst_type, :ord_type, :category,
                    :sz, :px, :side, :pos_side, :td_mode, :lever,
                    :acc_fill_sz, :fill_px, :fill_time_ms, :fill_time, :trade_id, :avg_px, :state,
                    :tp_trigger_px, :tp_ord_px, :sl_trigger_px, :sl_ord_px,
                    :fee, :fee_ccy, :rebate, :rebate_ccy, :pnl,
                    :c_time_ms, :c_time, :u_time_ms, :u_time,
                    :raw_data
                )
                ON CONFLICT (ord_id) DO UPDATE SET
                    cl_ord_id = CASE 
                        WHEN EXCLUDED.cl_ord_id IS NOT NULL AND EXCLUDED.cl_ord_id != '' 
                        THEN EXCLUDED.cl_ord_id
                        ELSE order_history.cl_ord_id
                    END,
                    tag = EXCLUDED.tag,
                    inst_id = EXCLUDED.inst_id,
                    symbol = EXCLUDED.symbol,
                    inst_type = EXCLUDED.inst_type,
                    ord_type = EXCLUDED.ord_type,
                    category = EXCLUDED.category,
                    sz = EXCLUDED.sz,
                    px = EXCLUDED.px,
                    side = EXCLUDED.side,
                    pos_side = EXCLUDED.pos_side,
                    td_mode = EXCLUDED.td_mode,
                    lever = EXCLUDED.lever,
                    acc_fill_sz = EXCLUDED.acc_fill_sz,
                    fill_px = EXCLUDED.fill_px,
                    fill_time_ms = EXCLUDED.fill_time_ms,
                    fill_time = EXCLUDED.fill_time,
                    trade_id = EXCLUDED.trade_id,
                    avg_px = EXCLUDED.avg_px,
                    state = EXCLUDED.state,
                    tp_trigger_px = EXCLUDED.tp_trigger_px,
                    tp_ord_px = EXCLUDED.tp_ord_px,
                    sl_trigger_px = EXCLUDED.sl_trigger_px,
                    sl_ord_px = EXCLUDED.sl_ord_px,
                    fee = EXCLUDED.fee,
                    fee_ccy = EXCLUDED.fee_ccy,
                    rebate = EXCLUDED.rebate,
                    rebate_ccy = EXCLUDED.rebate_ccy,
                    pnl = EXCLUDED.pnl,
                    c_time_ms = EXCLUDED.c_time_ms,
                    c_time = EXCLUDED.c_time,
                    u_time_ms = EXCLUDED.u_time_ms,
                    u_time = EXCLUDED.u_time,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
            """)
            
            # 转换数值字段
            def to_decimal(value):
                """转换为Decimal兼容的字符串"""
                if value is None or value == '':
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            result = session.execute(sql, {
                'ord_id': ord_id,
                'cl_ord_id': cl_ord_id,
                'tag': order_data.get('tag'),
                'inst_id': inst_id,
                'symbol': symbol,
                'inst_type': order_data.get('instType'),
                'ord_type': order_data.get('ordType'),
                'category': order_data.get('category'),
                'sz': to_decimal(order_data.get('sz')),
                'px': to_decimal(order_data.get('px')),
                'side': order_data.get('side'),
                'pos_side': order_data.get('posSide'),
                'td_mode': order_data.get('tdMode'),
                'lever': order_data.get('lever'),
                'acc_fill_sz': to_decimal(order_data.get('accFillSz')),
                'fill_px': to_decimal(order_data.get('fillPx')),
                'fill_time_ms': fill_time_ms,
                'fill_time': fill_time,
                'trade_id': order_data.get('tradeId'),
                'avg_px': to_decimal(order_data.get('avgPx')),
                'state': order_data.get('state'),
                'tp_trigger_px': to_decimal(order_data.get('tpTriggerPx')),
                'tp_ord_px': to_decimal(order_data.get('tpOrdPx')),
                'sl_trigger_px': to_decimal(order_data.get('slTriggerPx')),
                'sl_ord_px': to_decimal(order_data.get('slOrdPx')),
                'fee': to_decimal(order_data.get('fee')),
                'fee_ccy': order_data.get('feeCcy'),
                'rebate': to_decimal(order_data.get('rebate')),
                'rebate_ccy': order_data.get('rebateCcy'),
                'pnl': to_decimal(order_data.get('pnl')),
                'c_time_ms': c_time_ms,
                'c_time': c_time,
                'u_time_ms': u_time_ms,
                'u_time': u_time,
                'raw_data': json.dumps(raw_data) if raw_data else None,
            })
            
            # 如果插入/更新后cl_ord_id仍然为空，且是平仓订单，尝试再次关联
            # 这包括两种情况：
            # 1. 新插入的订单，cl_ord_id为空
            # 2. 已存在的订单，现有的cl_ord_id也为空
            # 注意：需要先查询数据库中实际的cl_ord_id，因为ON CONFLICT可能保留了已有值
            # 重要：在同一个事务中，需要先刷新session或重新查询，确保能获取到最新的值
            if not cl_ord_id and fill_time_ms:
                # 检查数据库中实际的cl_ord_id（对于已存在的订单）
                # 注意：在同一个事务中，ON CONFLICT的更新可能还未提交，需要刷新或重新查询
                check_sql = text("SELECT cl_ord_id FROM order_history WHERE ord_id = :ord_id")
                check_result = session.execute(check_sql, {'ord_id': ord_id}).fetchone()
                if check_result and check_result[0]:
                    # 数据库中已有cl_ord_id，更新变量以便后续使用
                    cl_ord_id = check_result[0]
                    logger.debug(f"订单 {ord_id} 在数据库中已有cl_ord_id: {cl_ord_id}")
            
            if not cl_ord_id and fill_time_ms:
                side = order_data.get('side', '').lower()
                pos_side = order_data.get('posSide', '').lower()
                reduce_only = order_data.get('reduceOnly', 'false').lower() == 'true'
                
                is_close_order = (
                    reduce_only or
                    (side == 'sell' and pos_side == 'long') or
                    (side == 'buy' and pos_side == 'short')
                )
                
                if is_close_order:
                    try:
                        from datetime import datetime, timezone, timedelta
                        fill_time_dt = datetime.fromtimestamp(fill_time_ms / 1000.0, tz=timezone.utc)
                        # 只查找平仓订单之前的开仓订单，时间窗口限制在30分钟内
                        time_window_start = fill_time_dt - timedelta(minutes=30)
                        
                        open_side = 'buy' if pos_side == 'long' else 'sell'
                        close_side = 'sell' if pos_side == 'long' else 'buy'
                        lookup_sql = text("""
                            SELECT oh.cl_ord_id
                            FROM order_history oh
                            WHERE oh.symbol = :symbol
                              AND oh.side = :open_side
                              AND oh.pos_side = :pos_side
                              AND oh.cl_ord_id IS NOT NULL
                              AND oh.cl_ord_id != ''
                              AND oh.fill_time >= :time_window_start
                              AND oh.fill_time < :fill_time
                              AND oh.ord_id != :current_ord_id
                              AND NOT EXISTS (
                                  -- 检查该开仓订单是否已经完全平仓（通过trading_relations）
                                  SELECT 1 FROM trading_relations tr
                                  WHERE tr.cl_ord_id = oh.cl_ord_id
                                    AND tr.operation_type = 'close'
                              )
                              AND NOT EXISTS (
                                  -- 检查该开仓订单是否已经完全平仓（通过order_history计算）
                                  -- 如果平仓总数量 >= 开仓总数量（允许1%误差），则认为已经完全平仓
                                  -- 注意：这里计算的是所有已关联的平仓订单总数量，包括当前时间之前的平仓订单
                                  SELECT 1
                                  FROM (
                                      SELECT 
                                          (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                           FROM order_history 
                                           WHERE cl_ord_id = oh.cl_ord_id 
                                             AND side = :open_side 
                                             AND pos_side = :pos_side 
                                             AND state = 'filled') as open_total,
                                          (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                           FROM order_history 
                                           WHERE cl_ord_id = oh.cl_ord_id 
                                             AND side = :close_side 
                                             AND pos_side = :pos_side 
                                             AND state = 'filled'
                                             AND fill_time < :fill_time) as close_total
                                  ) totals
                                  WHERE totals.open_total > 0
                                    AND totals.close_total / totals.open_total >= 0.99
                              )
                            ORDER BY oh.fill_time DESC
                            LIMIT 1
                        """)
                        lookup_result = session.execute(lookup_sql, {
                            'symbol': symbol,
                            'open_side': open_side,
                            'close_side': close_side,
                            'pos_side': pos_side,
                            'time_window_start': time_window_start,
                            'fill_time': fill_time_dt,
                            'current_ord_id': ord_id
                        }).fetchone()
                        
                        if lookup_result and lookup_result[0]:
                            found_cl_ord_id = lookup_result[0]
                            # 更新订单的cl_ord_id（无论是否已存在）
                            update_sql = text("""
                                UPDATE order_history
                                SET cl_ord_id = :cl_ord_id, updated_at = NOW()
                                WHERE ord_id = :ord_id AND (cl_ord_id IS NULL OR cl_ord_id = '')
                            """)
                            update_result = session.execute(update_sql, {
                                'ord_id': ord_id,
                                'cl_ord_id': found_cl_ord_id
                            })
                            if update_result.rowcount > 0:
                                # 重要：更新变量，以便后续的trading_relations处理逻辑能使用
                                cl_ord_id = found_cl_ord_id
                                # 刷新session，确保后续查询能获取到最新值
                                session.flush()
                                logger.info(
                                    f"为外部平仓订单关联cl_ord_id: ordId={ord_id}, "
                                    f"cl_ord_id={found_cl_ord_id}, fill_time={fill_time_dt}"
                                )
                    except Exception as e:
                        logger.debug(f"尝试关联外部平仓订单的cl_ord_id失败: ordId={ord_id}, {e}")
            
            # 如果订单已关联到cl_ord_id，且是外部平仓订单，自动处理trading_relations
            # 注意：这里需要重新获取cl_ord_id，因为可能在上面的逻辑中已经更新
            # 只有当订单插入/更新成功，且有fill_time_ms时，才尝试处理
            if result.rowcount > 0 and fill_time_ms:
                # 重新查询数据库中的cl_ord_id（可能已更新）
                # 重要：在同一个事务中，需要刷新session或重新查询，确保能获取到最新的值
                session.flush()  # 刷新session，确保之前的UPDATE操作可见
                final_cl_ord_id_sql = text("SELECT cl_ord_id FROM order_history WHERE ord_id = :ord_id")
                final_cl_ord_id_result = session.execute(final_cl_ord_id_sql, {'ord_id': ord_id}).fetchone()
                final_cl_ord_id = final_cl_ord_id_result[0] if final_cl_ord_id_result and final_cl_ord_id_result[0] else cl_ord_id
                
                # 如果还是没有cl_ord_id，记录日志以便调试
                if not final_cl_ord_id:
                    logger.debug(f"订单 {ord_id} 在trading_relations处理时仍无cl_ord_id，跳过处理")
                
                if final_cl_ord_id and fill_time_ms:
                    # 先检查该ord_id是否已经在trading_relations中存在（系统订单已处理）
                    check_existing_sql = text("""
                        SELECT id
                        FROM trading_relations
                        WHERE ord_id = :ord_id
                        LIMIT 1
                    """)
                    existing_result = session.execute(check_existing_sql, {'ord_id': ord_id}).fetchone()
                    
                    if existing_result:
                        # 【跳过处理日志】order_history.py:445 - 系统订单已处理，跳过订单WebSocket的自动处理
                        logger.info(
                            f"【跳过处理】位置: order_history.py:445 (insert_order) | "
                            f"ord_id: {ord_id} | cl_ord_id: {final_cl_ord_id} | "
                            f"原因: 该订单的trading_relations记录已存在，说明是系统订单（开仓/加仓/减仓/平仓），已由系统处理，跳过订单WebSocket的自动处理"
                        )
                    else:
                        # 检查是否是外部平仓订单
                        side = order_data.get('side', '').lower()
                        pos_side = order_data.get('posSide', '').lower()
                        reduce_only = order_data.get('reduceOnly', 'false').lower() == 'true'
                        
                        is_close_order = (
                            reduce_only or
                            (side == 'sell' and pos_side == 'long') or
                            (side == 'buy' and pos_side == 'short')
                        )
                        
                        if is_close_order:
                            try:
                                # 检查是否已存在该ord_id的trading_relations记录（避免重复插入）
                                check_existing_sql = text("""
                                    SELECT id FROM trading_relations
                                    WHERE ord_id = :ord_id
                                    LIMIT 1
                                """)
                                existing_result = session.execute(check_existing_sql, {'ord_id': ord_id}).fetchone()
                                
                                if existing_result:
                                    # 【跳过处理日志】order_history.py:456 - 订单已由系统处理，跳过订单WebSocket的自动处理
                                    logger.info(
                                        f"【跳过处理】位置: order_history.py:456 (insert_order) | "
                                        f"ord_id: {ord_id} | cl_ord_id: {final_cl_ord_id} | "
                                        f"原因: 该订单的trading_relations记录已存在，说明是系统订单，已由系统处理，跳过订单WebSocket的自动处理"
                                    )
                                else:
                                    # 查询trading_relations获取signal_id（通过cl_ord_id的开仓记录）
                                    get_signal_id_sql = text("""
                                        SELECT signal_id
                                        FROM trading_relations
                                        WHERE cl_ord_id = :cl_ord_id
                                          AND operation_type = 'open'
                                        ORDER BY created_at ASC
                                        LIMIT 1
                                    """)
                                    signal_id_result = session.execute(get_signal_id_sql, {'cl_ord_id': final_cl_ord_id}).fetchone()
                                    
                                    if not signal_id_result:
                                        logger.debug(f"未找到cl_ord_id={final_cl_ord_id}的开仓记录，跳过trading_relations处理")
                                    else:
                                        signal_id = signal_id_result[0]
                                        
                                        # 判断是部分平仓还是全部平仓
                                        # 重要：order_history中的acc_fill_sz是合约数量，但trading_relations中的amount是币数量
                                        # 需要获取合约乘数，将合约数量转换为币数量，才能正确判断
                                        # 获取合约乘数（从symbol判断，ETH=0.1，其他=1.0）
                                        contract_size = 0.1 if symbol.upper() == 'ETH' else 1.0
                                        
                                        # 查询该cl_ord_id的所有开仓订单总数量（合约数量）
                                        # 使用acc_fill_sz字段（累计成交数量），与trading_relations.amount保持一致
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
                                            'cl_ord_id': final_cl_ord_id,
                                            'open_side': open_side,
                                            'pos_side': pos_side
                                        }).fetchone()
                                        open_total_contracts = float(open_total_result[0]) if open_total_result and open_total_result[0] else 0.0
                                        
                                        # 转换为币数量（用于与trading_relations中的amount比较）
                                        open_total_currency = open_total_contracts * contract_size
                                        
                                        # 查询该cl_ord_id的所有平仓订单总数量（包括本次，合约数量）
                                        # 使用acc_fill_sz字段（累计成交数量），与trading_relations.amount保持一致
                                        # 注意：reduceOnly字段只存在于raw_data JSONB中，需要通过side和pos_side判断
                                        # 平仓订单的判断：side与pos_side反向（sell+long 或 buy+short）
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
                                            'cl_ord_id': final_cl_ord_id,
                                            'close_side': close_side,
                                            'pos_side': pos_side
                                        }).fetchone()
                                        close_total_contracts = float(close_total_result[0]) if close_total_result and close_total_result[0] else 0.0
                                        
                                        # 重要：当前订单可能还没有同步到order_history表，或者查询时由于事务隔离级别查询不到
                                        # 所以查询的平仓总数量可能不包含当前订单，需要加上当前订单的数量
                                        # 先获取当前订单的数量（合约数量）
                                        current_order_acc_fill_sz = to_decimal(order_data.get('accFillSz')) or 0.0
                                        # 加上当前订单的数量
                                        close_total_contracts_with_current = close_total_contracts + current_order_acc_fill_sz
                                        
                                        # 转换为币数量（用于与trading_relations中的amount比较）
                                        close_total_currency = close_total_contracts_with_current * contract_size
                                        
                                        # 判断是全部平仓还是部分平仓
                                        # 如果平仓总数量 >= 开仓总数量（允许小的误差），则为全部平仓
                                        # 注意：使用币数量进行比较，因为trading_relations中存储的是币数量
                                        is_full_close = False
                                        if open_total_currency > 0:
                                            close_ratio = close_total_currency / open_total_currency
                                            # 允许1%的误差（因为可能有手续费等影响）
                                            if close_ratio >= 0.99:
                                                is_full_close = True
                                        
                                        operation_type = 'close' if is_full_close else 'reduce'
                                        
                                        # 查询position_history_id（如果存在）
                                        # 通过pos_id查找（需要从order_history的raw_data中提取pos_id）
                                        position_history_id = None
                                        try:
                                            # raw_data可能是字符串（JSON）或字典
                                            raw_data_dict = None
                                            if raw_data:
                                                if isinstance(raw_data, str):
                                                    raw_data_dict = json.loads(raw_data)
                                                elif isinstance(raw_data, dict):
                                                    raw_data_dict = raw_data
                                            
                                            if raw_data_dict:
                                                pos_id_from_raw = raw_data_dict.get('posId')
                                                if pos_id_from_raw:
                                                    from app.database.trading_relations import TradingRelationsRepository
                                                    position_history_id = TradingRelationsRepository.get_position_history_id_by_pos_id(
                                                        session, pos_id_from_raw
                                                    )
                                        except Exception as e:
                                            logger.debug(f"查询position_history_id失败: {e}")
                                        
                                        # 获取平仓数量和价格
                                        # 重要：trading_relations中的amount使用order_history的acc_fill_sz字段（累计成交数量），转换为币数量
                                        # acc_fill_sz是累计成交数量（合约数量），需要转换为币数量
                                        close_amount_contracts = to_decimal(order_data.get('accFillSz')) or 0.0
                                        close_price = to_decimal(order_data.get('avgPx')) or to_decimal(order_data.get('fillPx')) or None
                                        
                                        # 转换为币数量（用于存储到trading_relations）
                                        # 获取合约乘数（从symbol判断，ETH=0.1，其他=1.0）
                                        contract_size = 0.1 if symbol.upper() == 'ETH' else 1.0
                                        close_amount = close_amount_contracts * contract_size
                                        
                                        # 验证：如果close_amount为0，说明订单可能未成交，不应该处理
                                        if close_amount <= 0:
                                            logger.warning(
                                                f"外部平仓订单数量为0，跳过trading_relations处理: ordId={ord_id}, "
                                                f"sz={order_data.get('sz')}"
                                            )
                                        else:
                                            # 【更新amount日志】order_history.py:597 - 订单WebSocket自动处理外部平仓
                                            logger.info(
                                                f"【更新amount】位置: order_history.py:597 (insert_order自动处理外部平仓) | "
                                                f"操作类型: {operation_type} | ord_id: {ord_id} | cl_ord_id: {final_cl_ord_id} | "
                                                f"acc_fill_sz(合约): {close_amount_contracts} | contract_size: {contract_size} | "
                                                f"最终amount(币): {close_amount} | 价格: {close_price} | 是否全部平仓: {is_full_close}"
                                            )
                                            # 插入trading_relations记录（与系统平仓一致的处理方式）
                                            from app.database.trading_relations import TradingRelationsRepository
                                            success = TradingRelationsRepository.insert_relation(
                                                session=session,
                                                signal_id=signal_id,
                                                cl_ord_id=final_cl_ord_id,
                                                operation_type=operation_type,
                                                ord_id=ord_id,  # 有ord_id，与系统平仓一致
                                                position_history_id=position_history_id,
                                                amount=close_amount,
                                                price=close_price
                                            )
                                            
                                            if success:
                                                logger.info(
                                                    f"外部平仓订单自动处理trading_relations: ordId={ord_id}, "
                                                    f"cl_ord_id={final_cl_ord_id}, operation_type={operation_type}, "
                                                    f"is_full_close={is_full_close}, close_amount={close_amount}"
                                                )
                                            else:
                                                logger.warning(
                                                    f"外部平仓订单处理trading_relations失败: ordId={ord_id}, "
                                                    f"cl_ord_id={final_cl_ord_id}"
                                                )
                            except Exception as e:
                                logger.error(
                                    f"处理外部平仓订单的trading_relations时发生错误: ordId={ord_id}, "
                                    f"错误: {e}", exc_info=True
                                )
                                # 不抛出异常，避免影响订单插入
                    # else: is_close_order为False，不是平仓订单，不需要处理
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入历史订单数据失败 ordId={order_data.get('ordId', 'N/A')}: {e}", exc_info=True)
            return False
    
    @staticmethod
    def get_latest_order_id(session: Session, symbol: Optional[str] = None) -> Optional[str]:
        """
        获取最新的订单ID（用于增量同步）
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选，如果提供则只查询该币种的最新订单）
            
        Returns:
            最新的订单ID，如果没有数据则返回None
        """
        try:
            if symbol:
                sql = text("""
                    SELECT ord_id
                    FROM order_history
                    WHERE symbol = :symbol
                    ORDER BY c_time DESC, ord_id DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'symbol': symbol}).fetchone()
            else:
                sql = text("""
                    SELECT ord_id
                    FROM order_history
                    ORDER BY c_time DESC, ord_id DESC
                    LIMIT 1
                """)
                result = session.execute(sql).fetchone()
            
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新订单ID失败: {e}")
            return None
    
    @staticmethod
    def get_order_count(session: Session, symbol: Optional[str] = None) -> int:
        """
        获取订单总数
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            
        Returns:
            订单总数
        """
        try:
            if symbol:
                sql = text("""
                    SELECT COUNT(*) as count
                    FROM order_history
                    WHERE symbol = :symbol
                """)
                result = session.execute(sql, {'symbol': symbol}).fetchone()
            else:
                sql = text("""
                    SELECT COUNT(*) as count
                    FROM order_history
                """)
                result = session.execute(sql).fetchone()
            
            return result[0] if result else 0
            
        except Exception as e:
            logger.error(f"获取订单总数失败: {e}")
            return 0
    
    @staticmethod
    def get_orders(
        session: Session,
        symbol: Optional[str] = None,
        state: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        查询历史订单
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            state: 订单状态（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 最大返回数量
            offset: 偏移量
            
        Returns:
            订单列表
        """
        try:
            sql = """
                SELECT 
                    ord_id, cl_ord_id, tag, inst_id, symbol, inst_type, ord_type, category,
                    sz, px, side, pos_side, td_mode, lever,
                    acc_fill_sz, fill_px, fill_time_ms, fill_time, trade_id, avg_px, state,
                    tp_trigger_px, tp_ord_px, sl_trigger_px, sl_ord_px,
                    fee, fee_ccy, rebate, rebate_ccy, pnl,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data, created_at, updated_at
                FROM order_history
                WHERE 1=1
            """
            params = {}
            
            if symbol:
                sql += " AND symbol = :symbol"
                params['symbol'] = symbol
            
            if state:
                sql += " AND state = :state"
                params['state'] = state
            
            if start_time:
                sql += " AND c_time >= :start_time"
                params['start_time'] = start_time
            
            if end_time:
                sql += " AND c_time <= :end_time"
                params['end_time'] = end_time
            
            sql += " ORDER BY c_time DESC, ord_id DESC LIMIT :limit OFFSET :offset"
            params['limit'] = limit
            params['offset'] = offset
            
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            orders = []
            for row in rows:
                order = {
                    'ord_id': row[0],
                    'cl_ord_id': row[1],
                    'tag': row[2],
                    'inst_id': row[3],
                    'symbol': row[4],
                    'inst_type': row[5],
                    'ord_type': row[6],
                    'category': row[7],
                    'sz': float(row[8]) if row[8] else None,
                    'px': float(row[9]) if row[9] else None,
                    'side': row[10],
                    'pos_side': row[11],
                    'td_mode': row[12],
                    'lever': row[13],
                    'acc_fill_sz': float(row[14]) if row[14] else None,
                    'fill_px': float(row[15]) if row[15] else None,
                    'fill_time_ms': row[16],
                    'fill_time': row[17],
                    'trade_id': row[18],
                    'avg_px': float(row[19]) if row[19] else None,
                    'state': row[20],
                    'tp_trigger_px': float(row[21]) if row[21] else None,
                    'tp_ord_px': float(row[22]) if row[22] else None,
                    'sl_trigger_px': float(row[23]) if row[23] else None,
                    'sl_ord_px': float(row[24]) if row[24] else None,
                    'fee': float(row[25]) if row[25] else None,
                    'fee_ccy': row[26],
                    'rebate': float(row[27]) if row[27] else None,
                    'rebate_ccy': row[28],
                    'pnl': float(row[29]) if row[29] else None,
                    'c_time_ms': row[30],
                    'c_time': row[31],
                    'u_time_ms': row[32],
                    'u_time': row[33],
                    'raw_data': row[34] if isinstance(row[34], dict) else (json.loads(row[34]) if row[34] else None),
                    'created_at': row[35],
                    'updated_at': row[36],
                }
                orders.append(order)
            
            return orders
            
        except Exception as e:
            logger.error(f"查询历史订单失败: {e}", exc_info=True)
            return []
    
    @staticmethod
    def fix_missing_cl_ord_id(
        session: Session,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> int:
        """
        修复缺少cl_ord_id的平仓订单
        
        Args:
            session: 数据库会话
            symbol: 交易对符号（可选，如果为None则修复所有交易对）
            limit: 每次修复的最大数量
            
        Returns:
            修复的订单数量
        """
        try:
            # 查找缺少cl_ord_id的平仓订单
            # 注意：reduce_only字段只存在于raw_data JSONB中，不能直接查询
            # 只能通过side和pos_side的反向关系来判断平仓订单
            sql = text("""
                SELECT ord_id, symbol, side, pos_side, fill_time, fill_time_ms
                FROM order_history
                WHERE (cl_ord_id IS NULL OR cl_ord_id = '')
                  AND (
                    (side = 'sell' AND pos_side = 'long')
                    OR (side = 'buy' AND pos_side = 'short')
                  )
                  AND fill_time IS NOT NULL
                  AND fill_time_ms IS NOT NULL
            """)
            
            params = {}
            if symbol:
                sql = text(str(sql) + " AND symbol = :symbol")
                params['symbol'] = symbol
            
            sql = text(str(sql) + " ORDER BY fill_time DESC LIMIT :limit")
            params['limit'] = limit
            
            result = session.execute(sql, params)
            rows = result.fetchall()
            
            if not rows:
                return 0
            
            fixed_count = 0
            from datetime import timedelta
            
            for row in rows:
                ord_id, row_symbol, side, pos_side, fill_time, fill_time_ms = row
                
                if not fill_time or not fill_time_ms:
                    continue
                
                try:
                    # 计算时间窗口（只查找平仓订单之前的开仓订单，时间窗口限制在30分钟内）
                    fill_time_dt = fill_time if isinstance(fill_time, datetime) else datetime.fromtimestamp(fill_time_ms / 1000.0, tz=timezone.utc)
                    time_window_start = fill_time_dt - timedelta(minutes=30)
                    
                    # 查找对应的开仓订单（只查找平仓订单之前的、未完全平仓的开仓订单）
                    open_side = 'buy' if pos_side.lower() == 'long' else 'sell'
                    close_side = 'sell' if pos_side.lower() == 'long' else 'buy'
                    lookup_sql = text("""
                        SELECT oh.cl_ord_id
                        FROM order_history oh
                        WHERE oh.symbol = :symbol
                          AND oh.side = :open_side
                          AND oh.pos_side = :pos_side
                          AND oh.cl_ord_id IS NOT NULL
                          AND oh.cl_ord_id != ''
                          AND oh.fill_time >= :time_window_start
                          AND oh.fill_time < :fill_time
                          AND oh.ord_id != :current_ord_id
                          AND NOT EXISTS (
                              -- 检查该开仓订单是否已经完全平仓（通过trading_relations）
                              SELECT 1 FROM trading_relations tr
                              WHERE tr.cl_ord_id = oh.cl_ord_id
                                AND tr.operation_type = 'close'
                          )
                          AND NOT EXISTS (
                              -- 检查该开仓订单是否已经完全平仓（通过order_history计算）
                              -- 如果平仓总数量 >= 开仓总数量（允许1%误差），则认为已经完全平仓
                              -- 注意：这里计算的是所有已关联的平仓订单总数量，包括当前时间之前的平仓订单
                              SELECT 1
                              FROM (
                                  SELECT 
                                      (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                       FROM order_history 
                                       WHERE cl_ord_id = oh.cl_ord_id 
                                         AND side = :open_side 
                                         AND pos_side = :pos_side 
                                         AND state = 'filled') as open_total,
                                      (SELECT COALESCE(SUM(acc_fill_sz), 0) 
                                       FROM order_history 
                                       WHERE cl_ord_id = oh.cl_ord_id 
                                         AND side = :close_side 
                                         AND pos_side = :pos_side 
                                         AND state = 'filled'
                                         AND fill_time < :fill_time) as close_total
                              ) totals
                              WHERE totals.open_total > 0
                                AND totals.close_total / totals.open_total >= 0.99
                          )
                        ORDER BY oh.fill_time DESC
                        LIMIT 1
                    """)
                    lookup_result = session.execute(lookup_sql, {
                        'symbol': row_symbol,
                        'open_side': open_side,
                        'close_side': close_side,
                        'pos_side': pos_side,
                        'time_window_start': time_window_start,
                        'fill_time': fill_time_dt,
                        'current_ord_id': ord_id
                    }).fetchone()
                    
                    if lookup_result and lookup_result[0]:
                        found_cl_ord_id = lookup_result[0]
                        # 更新订单的cl_ord_id
                        update_sql = text("""
                            UPDATE order_history
                            SET cl_ord_id = :cl_ord_id, updated_at = NOW()
                            WHERE ord_id = :ord_id AND (cl_ord_id IS NULL OR cl_ord_id = '')
                        """)
                        update_result = session.execute(update_sql, {
                            'ord_id': ord_id,
                            'cl_ord_id': found_cl_ord_id
                        })
                        if update_result.rowcount > 0:
                            fixed_count += 1
                            logger.info(
                                f"修复缺少cl_ord_id的订单: ordId={ord_id}, "
                                f"cl_ord_id={found_cl_ord_id}, symbol={row_symbol}"
                            )
                except Exception as e:
                    logger.debug(f"修复订单 {ord_id} 失败: {e}")
                    continue
            
            session.commit()
            return fixed_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"修复缺少cl_ord_id的订单失败: {e}", exc_info=True)
            return 0
    
    @staticmethod
    def fix_missing_trading_relations(
        session: Session,
        symbol: Optional[str] = None,
        limit: int = 100
    ) -> int:
        """
        修复缺少trading_relations记录的平仓订单
        
        Args:
            session: 数据库会话
            symbol: 交易对符号（可选，如果为None则修复所有交易对）
            limit: 每次修复的最大数量
            
        Returns:
            修复的记录数量
        """
        try:
            # 查找有cl_ord_id但没有trading_relations记录的平仓订单
            # 使用acc_fill_sz字段（累计成交数量），与trading_relations.amount保持一致
            sql = text("""
                SELECT oh.ord_id, oh.cl_ord_id, oh.symbol, oh.side, oh.pos_side, 
                       oh.acc_fill_sz, oh.avg_px, oh.fill_time_ms, oh.raw_data
                FROM order_history oh
                WHERE oh.cl_ord_id IS NOT NULL
                  AND oh.cl_ord_id != ''
                  AND oh.state = 'filled'
                  AND oh.fill_time_ms IS NOT NULL
                  AND (
                    (oh.side = 'sell' AND oh.pos_side = 'long')
                    OR (oh.side = 'buy' AND oh.pos_side = 'short')
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM trading_relations tr
                    WHERE tr.ord_id = oh.ord_id
                  )
            """)
            
            params = {}
            if symbol:
                sql = text(str(sql) + " AND oh.symbol = :symbol")
                params['symbol'] = symbol
            
            sql = text(str(sql) + " ORDER BY oh.fill_time DESC LIMIT :limit")
            params['limit'] = limit
            
            result = session.execute(sql, params)
            rows = result.fetchall()
            
            if not rows:
                return 0
            
            fixed_count = 0
            import json
            from datetime import datetime, timezone
            
            def to_decimal(value):
                """转换为Decimal兼容的字符串"""
                if value is None or value == '':
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            for row in rows:
                ord_id, cl_ord_id, row_symbol, side, pos_side, acc_fill_sz_value, avg_px, fill_time_ms, raw_data = row
                
                try:
                    # 查询trading_relations获取signal_id（通过cl_ord_id的开仓记录）
                    get_signal_id_sql = text("""
                        SELECT signal_id
                        FROM trading_relations
                        WHERE cl_ord_id = :cl_ord_id
                          AND operation_type = 'open'
                        ORDER BY created_at ASC
                        LIMIT 1
                    """)
                    signal_id_result = session.execute(get_signal_id_sql, {'cl_ord_id': cl_ord_id}).fetchone()
                    
                    if not signal_id_result:
                        logger.debug(f"未找到cl_ord_id={cl_ord_id}的开仓记录，跳过trading_relations处理: ordId={ord_id}")
                        continue
                    
                    signal_id = signal_id_result[0]
                    
                    # 判断是部分平仓还是全部平仓
                    contract_size = 0.1 if row_symbol.upper() == 'ETH' else 1.0
                    
                    # 查询该cl_ord_id的所有开仓订单总数量（合约数量）
                    # 使用acc_fill_sz字段（累计成交数量），与trading_relations.amount保持一致
                    open_side = 'buy' if pos_side.lower() == 'long' else 'sell'
                    get_open_total_sql = text("""
                        SELECT COALESCE(SUM(acc_fill_sz), 0)
                        FROM order_history
                        WHERE cl_ord_id = :cl_ord_id
                          AND side = :open_side
                          AND pos_side = :pos_side
                          AND state = 'filled'
                    """)
                    open_total_result = session.execute(get_open_total_sql, {
                        'cl_ord_id': cl_ord_id,
                        'open_side': open_side,
                        'pos_side': pos_side
                    }).fetchone()
                    open_total_contracts = float(open_total_result[0]) if open_total_result and open_total_result[0] else 0.0
                    open_total_currency = open_total_contracts * contract_size
                    
                    # 查询该cl_ord_id的所有平仓订单总数量（合约数量）
                    # 使用acc_fill_sz字段（累计成交数量），与trading_relations.amount保持一致
                    close_side = 'sell' if pos_side.lower() == 'long' else 'buy'
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
                    close_total_contracts = float(close_total_result[0]) if close_total_result and close_total_result[0] else 0.0
                    close_total_currency = close_total_contracts * contract_size
                    
                    # 判断是全部平仓还是部分平仓
                    is_full_close = False
                    if open_total_currency > 0:
                        close_ratio = close_total_currency / open_total_currency
                        if close_ratio >= 0.99:
                            is_full_close = True
                    
                    operation_type = 'close' if is_full_close else 'reduce'
                    
                    # 查询position_history_id（如果存在）
                    position_history_id = None
                    try:
                        raw_data_dict = None
                        if raw_data:
                            if isinstance(raw_data, str):
                                raw_data_dict = json.loads(raw_data)
                            elif isinstance(raw_data, dict):
                                raw_data_dict = raw_data
                        
                        if raw_data_dict:
                            pos_id_from_raw = raw_data_dict.get('posId')
                            if pos_id_from_raw:
                                from app.database.trading_relations import TradingRelationsRepository
                                position_history_id = TradingRelationsRepository.get_position_history_id_by_pos_id(
                                    session, pos_id_from_raw
                                )
                    except Exception as e:
                        logger.debug(f"查询position_history_id失败: {e}")
                    
                    # 获取平仓数量和价格
                    # 重要：trading_relations中的amount使用order_history的acc_fill_sz字段（累计成交数量），转换为币数量
                    # acc_fill_sz是累计成交数量（合约数量），需要转换为币数量
                    close_amount_contracts = float(acc_fill_sz_value) if acc_fill_sz_value else 0.0
                    close_price = float(avg_px) if avg_px else None
                    close_amount = close_amount_contracts * contract_size
                    
                    if close_amount <= 0:
                        logger.warning(f"平仓订单数量为0，跳过trading_relations处理: ordId={ord_id}")
                        continue
                    
                    # 【更新amount日志】order_history.py:1153 - 修复缺少trading_relations的订单
                    logger.info(
                        f"【更新amount】位置: order_history.py:1153 (fix_missing_trading_relations) | "
                        f"操作类型: {operation_type} | ord_id: {ord_id} | cl_ord_id: {cl_ord_id} | "
                        f"acc_fill_sz(合约): {close_amount_contracts} | contract_size: {contract_size} | "
                        f"最终amount(币): {close_amount} | 价格: {close_price}"
                    )
                    # 插入trading_relations记录
                    from app.database.trading_relations import TradingRelationsRepository
                    success = TradingRelationsRepository.insert_relation(
                        session=session,
                        signal_id=signal_id,
                        cl_ord_id=cl_ord_id,
                        operation_type=operation_type,
                        ord_id=ord_id,
                        position_history_id=position_history_id,
                        amount=close_amount,
                        price=close_price
                    )
                    
                    if success:
                        fixed_count += 1
                        logger.info(
                            f"修复缺少trading_relations的订单: ordId={ord_id}, "
                            f"cl_ord_id={cl_ord_id}, operation_type={operation_type}, "
                            f"is_full_close={is_full_close}, close_amount={close_amount}, "
                            f"position_history_id={position_history_id}"
                        )
                        
                        # 如果position_history_id为空，尝试重新查询（因为position_history可能刚同步完成）
                        if not position_history_id and raw_data:
                            try:
                                raw_data_dict = None
                                if isinstance(raw_data, str):
                                    raw_data_dict = json.loads(raw_data)
                                elif isinstance(raw_data, dict):
                                    raw_data_dict = raw_data
                                
                                if raw_data_dict:
                                    pos_id_from_raw = raw_data_dict.get('posId')
                                    if pos_id_from_raw:
                                        from app.database.trading_relations import TradingRelationsRepository
                                        new_position_history_id = TradingRelationsRepository.get_position_history_id_by_pos_id(
                                            session, pos_id_from_raw
                                        )
                                        if new_position_history_id:
                                            # 更新trading_relations记录的position_history_id
                                            update_sql = text("""
                                                UPDATE trading_relations
                                                SET position_history_id = :position_history_id, updated_at = NOW()
                                                WHERE ord_id = :ord_id
                                            """)
                                            update_result = session.execute(update_sql, {
                                                'position_history_id': new_position_history_id,
                                                'ord_id': ord_id
                                            })
                                            if update_result.rowcount > 0:
                                                logger.info(
                                                    f"更新trading_relations的position_history_id: ordId={ord_id}, "
                                                    f"position_history_id={new_position_history_id}"
                                                )
                            except Exception as e:
                                logger.debug(f"尝试更新position_history_id失败: ordId={ord_id}, {e}")
                    else:
                        logger.warning(f"修复trading_relations失败: ordId={ord_id}, cl_ord_id={cl_ord_id}")
                        
                except Exception as e:
                    logger.debug(f"修复订单 {ord_id} 的trading_relations失败: {e}")
                    continue
            
            session.commit()
            return fixed_count
            
        except Exception as e:
            session.rollback()
            logger.error(f"修复缺少trading_relations的订单失败: {e}", exc_info=True)
            return 0

