"""
OKX仓位历史数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple
import json
from app.database.connection import db
from app.utils.logger import logger


class PositionHistoryRepository:
    """OKX仓位历史数据仓库"""
    
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
    def insert_position(
        session: Session,
        position_data: Dict[str, Any],
        raw_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        插入仓位历史数据
        
        Args:
            session: 数据库会话
            position_data: 仓位数据（OKX API返回的仓位对象）
            raw_data: 完整原始JSON数据（可选，如果不提供则使用position_data）
            
        Returns:
            是否插入成功
        """
        try:
            # 提取必需字段
            pos_id = position_data.get('posId', '')
            u_time_str = position_data.get('uTime', '')
            
            if not pos_id or not u_time_str:
                logger.warning("仓位数据缺少posId或uTime，跳过插入")
                return False
            
            # 从instId提取symbol
            inst_id = position_data.get('instId', '')
            if not inst_id:
                logger.warning(f"仓位数据缺少instId posId={pos_id}，跳过插入")
                return False
            
            symbol = PositionHistoryRepository.extract_symbol_from_inst_id(inst_id)
            if not symbol:
                logger.warning(f"无法从instId提取symbol posId={pos_id}, instId={inst_id}，跳过插入")
                return False
            
            # 检查必需字段
            inst_type = position_data.get('instType', '')
            mgn_mode = position_data.get('mgnMode', '')
            if not inst_type or not mgn_mode:
                logger.warning(f"仓位数据缺少instType或mgnMode posId={pos_id}, instType={inst_type}, mgnMode={mgn_mode}，跳过插入")
                return False
            
            # 解析时间戳
            c_time_ms, c_time = PositionHistoryRepository.parse_timestamp_ms(position_data.get('cTime', ''))
            u_time_ms, u_time = PositionHistoryRepository.parse_timestamp_ms(u_time_str)
            
            # 检查时间戳是否解析成功（数据库字段是NOT NULL）
            if c_time_ms is None or u_time_ms is None or c_time is None or u_time is None:
                logger.warning(f"仓位数据时间戳解析失败 posId={pos_id}, cTime={position_data.get('cTime', 'N/A')}, uTime={u_time_str}，跳过插入")
                return False
            
            # 如果没有提供raw_data，使用position_data
            if raw_data is None:
                raw_data = position_data
            
            # 转换数值字段
            def to_decimal(value):
                """转换为Decimal兼容的数值"""
                if value is None or value == '':
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            sql = text("""
                INSERT INTO position_history (
                    inst_id, symbol, inst_type, mgn_mode, pos_id, pos_side, direction, lever, ccy, uly,
                    open_avg_px, non_settle_avg_px, close_avg_px, trigger_px,
                    open_max_pos, close_total_pos,
                    realized_pnl, settled_pnl, pnl, pnl_ratio, fee, funding_fee, liq_penalty,
                    type, trade_id1, trade_id2,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data
                )
                VALUES (
                    :inst_id, :symbol, :inst_type, :mgn_mode, :pos_id, :pos_side, :direction, :lever, :ccy, :uly,
                    :open_avg_px, :non_settle_avg_px, :close_avg_px, :trigger_px,
                    :open_max_pos, :close_total_pos,
                    :realized_pnl, :settled_pnl, :pnl, :pnl_ratio, :fee, :funding_fee, :liq_penalty,
                    :type, :trade_id1, :trade_id2,
                    :c_time_ms, :c_time, :u_time_ms, :u_time,
                    :raw_data
                )
                ON CONFLICT (pos_id, c_time) DO UPDATE SET
                    inst_id = EXCLUDED.inst_id,
                    symbol = EXCLUDED.symbol,
                    inst_type = EXCLUDED.inst_type,
                    mgn_mode = EXCLUDED.mgn_mode,
                    pos_side = EXCLUDED.pos_side,
                    direction = EXCLUDED.direction,
                    lever = EXCLUDED.lever,
                    ccy = EXCLUDED.ccy,
                    uly = EXCLUDED.uly,
                    open_avg_px = EXCLUDED.open_avg_px,
                    non_settle_avg_px = EXCLUDED.non_settle_avg_px,
                    close_avg_px = EXCLUDED.close_avg_px,
                    trigger_px = EXCLUDED.trigger_px,
                    open_max_pos = EXCLUDED.open_max_pos,
                    close_total_pos = EXCLUDED.close_total_pos,
                    realized_pnl = EXCLUDED.realized_pnl,
                    settled_pnl = EXCLUDED.settled_pnl,
                    pnl = EXCLUDED.pnl,
                    pnl_ratio = EXCLUDED.pnl_ratio,
                    fee = EXCLUDED.fee,
                    funding_fee = EXCLUDED.funding_fee,
                    liq_penalty = EXCLUDED.liq_penalty,
                    type = EXCLUDED.type,
                    trade_id1 = EXCLUDED.trade_id1,
                    trade_id2 = EXCLUDED.trade_id2,
                    u_time_ms = EXCLUDED.u_time_ms,
                    u_time = EXCLUDED.u_time,
                    raw_data = EXCLUDED.raw_data,
                    updated_at = NOW()
            """)
            
            result = session.execute(sql, {
                'inst_id': inst_id,
                'symbol': symbol,
                'inst_type': inst_type,
                'mgn_mode': mgn_mode,
                'pos_id': pos_id,
                'pos_side': position_data.get('posSide'),
                'direction': position_data.get('direction'),
                'lever': position_data.get('lever'),
                'ccy': position_data.get('ccy'),
                'uly': position_data.get('uly'),
                'open_avg_px': to_decimal(position_data.get('openAvgPx')),
                'non_settle_avg_px': to_decimal(position_data.get('nonSettleAvgPx')),
                'close_avg_px': to_decimal(position_data.get('closeAvgPx')),
                'trigger_px': to_decimal(position_data.get('triggerPx')),
                'open_max_pos': to_decimal(position_data.get('openMaxPos')),
                'close_total_pos': to_decimal(position_data.get('closeTotalPos')),
                'realized_pnl': to_decimal(position_data.get('realizedPnl')),
                'settled_pnl': to_decimal(position_data.get('settledPnl')),
                'pnl': to_decimal(position_data.get('pnl')),
                'pnl_ratio': to_decimal(position_data.get('pnlRatio')),
                'fee': to_decimal(position_data.get('fee')),
                'funding_fee': to_decimal(position_data.get('fundingFee')),
                'liq_penalty': to_decimal(position_data.get('liqPenalty')),
                'type': position_data.get('type'),
                'trade_id1': None,  # 扩展字段，默认为空
                'trade_id2': None,  # 扩展字段，默认为空
                'c_time_ms': c_time_ms,
                'c_time': c_time,
                'u_time_ms': u_time_ms,
                'u_time': u_time,
                'raw_data': json.dumps(raw_data) if raw_data else None,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入仓位历史数据失败 posId={position_data.get('posId', 'N/A')}, uTime={position_data.get('uTime', 'N/A')}: {e}", exc_info=True)
            return False
    
    @staticmethod
    def get_latest_position_time(session: Session, symbol: Optional[str] = None) -> Tuple[Optional[int], Optional[datetime]]:
        """
        获取最新的仓位更新时间（用于增量同步）
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选，如果提供则只查询该币种的最新仓位）
            
        Returns:
            (u_time_ms, u_time) 元组，如果没有数据则返回 (None, None)
        """
        try:
            if symbol:
                sql = text("""
                    SELECT u_time_ms, u_time
                    FROM position_history
                    WHERE symbol = :symbol
                    ORDER BY u_time DESC, pos_id DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'symbol': symbol}).fetchone()
            else:
                sql = text("""
                    SELECT u_time_ms, u_time
                    FROM position_history
                    ORDER BY u_time DESC, pos_id DESC
                    LIMIT 1
                """)
                result = session.execute(sql).fetchone()
            
            if result and result[0] and result[1]:
                return result[0], result[1]
            return None, None
            
        except Exception as e:
            logger.error(f"获取最新仓位更新时间失败: {e}")
            return None, None
    
    @staticmethod
    def get_position_count(session: Session, symbol: Optional[str] = None) -> int:
        """
        获取仓位历史总数
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            
        Returns:
            仓位历史总数
        """
        try:
            if symbol:
                sql = text("""
                    SELECT COUNT(*) as count
                    FROM position_history
                    WHERE symbol = :symbol
                """)
                result = session.execute(sql, {'symbol': symbol}).fetchone()
            else:
                sql = text("""
                    SELECT COUNT(*) as count
                    FROM position_history
                """)
                result = session.execute(sql).fetchone()
            
            return result[0] if result else 0
            
        except Exception as e:
            logger.error(f"获取仓位历史总数失败: {e}")
            return 0
    
    @staticmethod
    def get_positions(
        session: Session,
        symbol: Optional[str] = None,
        inst_id: Optional[str] = None,
        pos_id: Optional[str] = None,
        type: Optional[str] = None,
        mgn_mode: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        查询仓位历史
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            inst_id: 产品ID（可选）
            pos_id: 仓位ID（可选）
            type: 平仓类型（可选）
            mgn_mode: 保证金模式（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 最大返回数量
            offset: 偏移量
            
        Returns:
            仓位历史列表
        """
        try:
            sql = """
                SELECT 
                    id, inst_id, symbol, inst_type, mgn_mode, pos_id, pos_side, direction, lever, ccy, uly,
                    open_avg_px, non_settle_avg_px, close_avg_px, trigger_px,
                    open_max_pos, close_total_pos,
                    realized_pnl, settled_pnl, pnl, pnl_ratio, fee, funding_fee, liq_penalty,
                    type, trade_id1, trade_id2,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data, created_at, updated_at
                FROM position_history
                WHERE 1=1
            """
            params = {}
            
            if symbol:
                sql += " AND symbol = :symbol"
                params['symbol'] = symbol
            
            if inst_id:
                sql += " AND inst_id = :inst_id"
                params['inst_id'] = inst_id
            
            if pos_id:
                sql += " AND pos_id = :pos_id"
                params['pos_id'] = pos_id
            
            if type:
                sql += " AND type = :type"
                params['type'] = type
            
            if mgn_mode:
                sql += " AND mgn_mode = :mgn_mode"
                params['mgn_mode'] = mgn_mode
            
            if start_time:
                sql += " AND u_time >= :start_time"
                params['start_time'] = start_time
            
            if end_time:
                sql += " AND u_time <= :end_time"
                params['end_time'] = end_time
            
            sql += " ORDER BY u_time DESC, pos_id DESC LIMIT :limit OFFSET :offset"
            params['limit'] = limit
            params['offset'] = offset
            
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            positions = []
            for row in rows:
                position = {
                    'id': row[0],
                    'inst_id': row[1],
                    'symbol': row[2],
                    'inst_type': row[3],
                    'mgn_mode': row[4],
                    'pos_id': row[5],
                    'pos_side': row[6],
                    'direction': row[7],
                    'lever': row[8],
                    'ccy': row[9],
                    'uly': row[10],
                    'open_avg_px': float(row[11]) if row[11] else None,
                    'non_settle_avg_px': float(row[12]) if row[12] else None,
                    'close_avg_px': float(row[13]) if row[13] else None,
                    'trigger_px': float(row[14]) if row[14] else None,
                    'open_max_pos': float(row[15]) if row[15] else None,
                    'close_total_pos': float(row[16]) if row[16] else None,
                    'realized_pnl': float(row[17]) if row[17] else None,
                    'settled_pnl': float(row[18]) if row[18] else None,
                    'pnl': float(row[19]) if row[19] else None,
                    'pnl_ratio': float(row[20]) if row[20] else None,
                    'fee': float(row[21]) if row[21] else None,
                    'funding_fee': float(row[22]) if row[22] else None,
                    'liq_penalty': float(row[23]) if row[23] else None,
                    'type': row[24],
                    'trade_id1': row[25],
                    'trade_id2': row[26],
                    'c_time_ms': row[27],
                    'c_time': row[28],
                    'u_time_ms': row[29],
                    'u_time': row[30],
                    'raw_data': row[31] if isinstance(row[31], dict) else (json.loads(row[31]) if row[31] else None),
                    'created_at': row[32],
                    'updated_at': row[33],
                }
                positions.append(position)
            
            return positions
            
        except Exception as e:
            logger.error(f"查询仓位历史失败: {e}", exc_info=True)
            return []

