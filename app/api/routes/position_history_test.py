"""
OKX仓位历史测试路由
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from app.database.connection import db
from app.database.position_history import PositionHistoryRepository
from app.utils.logger import logger

router = APIRouter(prefix="/position-history", tags=["OKX仓位历史测试"])


@router.get("/status")
async def get_position_history_status():
    """
    获取仓位历史统计信息
    
    Returns:
        仓位统计信息
    """
    session = db.get_session()
    try:
        # 获取总仓位数
        total_count = PositionHistoryRepository.get_position_count(session)
        
        # 按币种统计
        symbols = ['BTC', 'ETH']
        symbol_stats = {}
        for symbol in symbols:
            count = PositionHistoryRepository.get_position_count(session, symbol=symbol)
            latest_u_time_ms, latest_u_time = PositionHistoryRepository.get_latest_position_time(session, symbol=symbol)
            symbol_stats[symbol] = {
                'count': count,
                'latest_u_time_ms': latest_u_time_ms,
                'latest_u_time': latest_u_time.isoformat() if latest_u_time else None
            }
        
        return {
            "status": "success",
            "total_count": total_count,
            "symbol_stats": symbol_stats
        }
    except Exception as e:
        logger.error(f"获取仓位历史统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
    finally:
        session.close()


@router.get("/positions")
async def get_positions(
    symbol: Optional[str] = Query(None, description="币种名称（BTC/ETH）"),
    inst_id: Optional[str] = Query(None, description="产品ID（如BTC-USDT-SWAP）"),
    pos_id: Optional[str] = Query(None, description="仓位ID"),
    type: Optional[str] = Query(None, description="平仓类型（1-6）"),
    mgn_mode: Optional[str] = Query(None, description="保证金模式（cross/isolated）"),
    begin: Optional[int] = Query(None, description="开始时间（Unix时间戳，毫秒）"),
    end: Optional[int] = Query(None, description="结束时间（Unix时间戳，毫秒）"),
    limit: int = Query(100, ge=1, le=100, description="返回数量（1-100）"),
    offset: int = Query(0, ge=0, description="偏移量")
):
    """
    查询仓位历史
    
    Args:
        symbol: 币种名称（可选，验证格式）
        inst_id: 产品ID（可选，验证格式）
        pos_id: 仓位ID（可选，验证格式）
        type: 平仓类型（可选，验证范围1-6）
        mgn_mode: 保证金模式（可选，验证值cross/isolated）
        begin: 开始时间（Unix时间戳，毫秒）
        end: 结束时间（Unix时间戳，毫秒）
        limit: 返回数量（最大100）
        offset: 偏移量
    
    Returns:
        仓位历史列表
    """
    # 输入验证
    if symbol and (len(symbol) > 20 or not symbol.isalnum()):
        raise HTTPException(status_code=400, detail="币种名称格式错误")
    if inst_id and len(inst_id) > 50:
        raise HTTPException(status_code=400, detail="产品ID格式错误")
    if pos_id and len(pos_id) > 50:
        raise HTTPException(status_code=400, detail="仓位ID格式错误")
    if type and type not in ['1', '2', '3', '4', '5', '6']:
        raise HTTPException(status_code=400, detail="平仓类型必须是1-6")
    if mgn_mode and mgn_mode not in ['cross', 'isolated']:
        raise HTTPException(status_code=400, detail="保证金模式必须是cross或isolated")
    if begin and end and begin > end:
        raise HTTPException(status_code=400, detail="开始时间不能大于结束时间")
    session = db.get_session()
    try:
        # 将时间戳转换为datetime（用于数据库查询）
        start_dt = None
        end_dt = None
        
        if begin:
            try:
                start_dt = datetime.fromtimestamp(begin / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="开始时间格式错误，请使用Unix时间戳（毫秒）")
        
        if end:
            try:
                end_dt = datetime.fromtimestamp(end / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="结束时间格式错误，请使用Unix时间戳（毫秒）")
        
        # 查询仓位历史
        positions = PositionHistoryRepository.get_positions(
            session,
            symbol=symbol,
            inst_id=inst_id,
            pos_id=pos_id,
            type=type,
            mgn_mode=mgn_mode,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit,
            offset=offset
        )
        
        return {
            "status": "success",
            "count": len(positions),
            "limit": limit,
            "offset": offset,
            "positions": positions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询仓位历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        session.close()


@router.get("/positions/{pos_id}")
async def get_position_by_id(
    pos_id: str,
    u_time: Optional[int] = Query(None, description="仓位更新时间（Unix时间戳，毫秒），如果不提供则返回该pos_id的最新记录")
):
    """
    根据仓位ID查询仓位详情
    
    Args:
        pos_id: 仓位ID
        u_time: 仓位更新时间（可选，如果不提供则返回该pos_id的最新记录）
    
    Returns:
        仓位详情
    """
    # 验证pos_id格式（防止SQL注入，虽然使用了参数化查询，但验证格式更安全）
    if not pos_id or len(pos_id) > 50:
        raise HTTPException(status_code=400, detail="仓位ID格式错误")
    
    session = db.get_session()
    try:
        from sqlalchemy import text
        import json
        
        if u_time:
            # 验证u_time格式
            try:
                u_time_dt = datetime.fromtimestamp(u_time / 1000.0, tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                raise HTTPException(status_code=400, detail="时间戳格式错误，请使用Unix时间戳（毫秒）")
            sql = text("""
                SELECT 
                    id, inst_id, symbol, inst_type, mgn_mode, pos_id, pos_side, direction, lever, ccy, uly,
                    open_avg_px, non_settle_avg_px, close_avg_px, trigger_px,
                    open_max_pos, close_total_pos,
                    realized_pnl, settled_pnl, pnl, pnl_ratio, fee, funding_fee, liq_penalty,
                    type, trade_id1, trade_id2,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data, created_at, updated_at
                FROM position_history
                WHERE pos_id = :pos_id AND u_time = :u_time
            """)
            result = session.execute(sql, {'pos_id': pos_id, 'u_time': u_time_dt}).fetchone()
        else:
            # 查询该pos_id的最新记录
            sql = text("""
                SELECT 
                    id, inst_id, symbol, inst_type, mgn_mode, pos_id, pos_side, direction, lever, ccy, uly,
                    open_avg_px, non_settle_avg_px, close_avg_px, trigger_px,
                    open_max_pos, close_total_pos,
                    realized_pnl, settled_pnl, pnl, pnl_ratio, fee, funding_fee, liq_penalty,
                    type, trade_id1, trade_id2,
                    c_time_ms, c_time, u_time_ms, u_time,
                    raw_data, created_at, updated_at
                FROM position_history
                WHERE pos_id = :pos_id
                ORDER BY u_time DESC
                LIMIT 1
            """)
            result = session.execute(sql, {'pos_id': pos_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail=f"仓位 {pos_id} 不存在")
        
        position = {
            'id': result[0],
            'inst_id': result[1],
            'symbol': result[2],
            'inst_type': result[3],
            'mgn_mode': result[4],
            'pos_id': result[5],
            'pos_side': result[6],
            'direction': result[7],
            'lever': result[8],
            'ccy': result[9],
            'uly': result[10],
            'open_avg_px': float(result[11]) if result[11] else None,
            'non_settle_avg_px': float(result[12]) if result[12] else None,
            'close_avg_px': float(result[13]) if result[13] else None,
            'trigger_px': float(result[14]) if result[14] else None,
            'open_max_pos': float(result[15]) if result[15] else None,
            'close_total_pos': float(result[16]) if result[16] else None,
            'realized_pnl': float(result[17]) if result[17] else None,
            'settled_pnl': float(result[18]) if result[18] else None,
            'pnl': float(result[19]) if result[19] else None,
            'pnl_ratio': float(result[20]) if result[20] else None,
            'fee': float(result[21]) if result[21] else None,
            'funding_fee': float(result[22]) if result[22] else None,
            'liq_penalty': float(result[23]) if result[23] else None,
            'type': result[24],
            'trade_id1': result[25],
            'trade_id2': result[26],
            'c_time_ms': result[27],
            'c_time': result[28].isoformat() if result[28] else None,
            'u_time_ms': result[29],
            'u_time': result[30].isoformat() if result[30] else None,
            'raw_data': result[31] if isinstance(result[31], dict) else (json.loads(result[31]) if result[31] else None),
            'created_at': result[32].isoformat() if result[32] else None,
            'updated_at': result[33].isoformat() if result[33] else None,
        }
        
        return {
            "status": "success",
            "position": position
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询仓位详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        session.close()


@router.get("/symbols/{symbol}/stats")
async def get_symbol_stats(symbol: str):
    """
    获取某个币种的仓位统计信息
    
    Args:
        symbol: 币种名称（BTC/ETH）
    
    Returns:
        统计信息
    """
    # 验证symbol格式
    if not symbol or len(symbol) > 20 or not symbol.isalnum():
        raise HTTPException(status_code=400, detail="币种名称格式错误")
    
    session = db.get_session()
    try:
        # 获取仓位总数
        total_count = PositionHistoryRepository.get_position_count(session, symbol=symbol)
        
        # 获取最新仓位更新时间
        latest_u_time_ms, latest_u_time = PositionHistoryRepository.get_latest_position_time(session, symbol=symbol)
        
        # 按平仓类型统计
        from sqlalchemy import text
        type_sql = text("""
            SELECT type, COUNT(*) as count
            FROM position_history
            WHERE symbol = :symbol
            GROUP BY type
        """)
        type_stats = {}
        for row in session.execute(type_sql, {'symbol': symbol}):
            type_stats[row[0]] = row[1]
        
        # 按保证金模式统计
        mgn_mode_sql = text("""
            SELECT mgn_mode, COUNT(*) as count
            FROM position_history
            WHERE symbol = :symbol
            GROUP BY mgn_mode
        """)
        mgn_mode_stats = {}
        for row in session.execute(mgn_mode_sql, {'symbol': symbol}):
            mgn_mode_stats[row[0]] = row[1]
        
        # 按持仓方向统计
        direction_sql = text("""
            SELECT direction, COUNT(*) as count
            FROM position_history
            WHERE symbol = :symbol
            GROUP BY direction
        """)
        direction_stats = {}
        for row in session.execute(direction_sql, {'symbol': symbol}):
            direction_stats[row[0]] = row[1]
        
        return {
            "status": "success",
            "symbol": symbol,
            "total_count": total_count,
            "latest_u_time_ms": latest_u_time_ms,
            "latest_u_time": latest_u_time.isoformat() if latest_u_time else None,
            "type_stats": type_stats,
            "mgn_mode_stats": mgn_mode_stats,
            "direction_stats": direction_stats
        }
        
    except Exception as e:
        logger.error(f"获取币种统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
    finally:
        session.close()

