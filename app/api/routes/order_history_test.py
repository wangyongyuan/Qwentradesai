"""
OKX历史订单测试路由
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from app.database.connection import db
from app.database.order_history import OrderHistoryRepository
from app.utils.logger import logger

router = APIRouter(prefix="/order-history", tags=["OKX历史订单测试"])


@router.get("/status")
async def get_order_history_status():
    """
    获取历史订单统计信息
    
    Returns:
        订单统计信息
    """
    session = db.get_session()
    try:
        # 获取总订单数
        total_count = OrderHistoryRepository.get_order_count(session)
        
        # 按币种统计
        symbols = ['BTC', 'ETH']
        symbol_stats = {}
        for symbol in symbols:
            count = OrderHistoryRepository.get_order_count(session, symbol=symbol)
            latest_ord_id = OrderHistoryRepository.get_latest_order_id(session, symbol=symbol)
            symbol_stats[symbol] = {
                'count': count,
                'latest_ord_id': latest_ord_id
            }
        
        return {
            "status": "success",
            "total_count": total_count,
            "symbol_stats": symbol_stats
        }
    except Exception as e:
        logger.error(f"获取历史订单统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
    finally:
        session.close()


@router.get("/orders")
async def get_orders(
    symbol: Optional[str] = Query(None, description="币种名称（BTC/ETH）"),
    state: Optional[str] = Query(None, description="订单状态（filled/canceled等）"),
    begin: Optional[int] = Query(None, description="开始时间（Unix时间戳，毫秒，如：1704067200000）"),
    end: Optional[int] = Query(None, description="结束时间（Unix时间戳，毫秒）"),
    after: Optional[str] = Query(None, description="分页参数，请求此订单ID之前（更旧的数据）的分页内容"),
    limit: int = Query(100, ge=1, le=100, description="返回数量（1-100，与OKX API一致）")
):
    """
    查询历史订单（参数与OKX API orders-history-archive接口一致）
    
    Args:
        symbol: 币种名称（可选）
        state: 订单状态（可选）
        begin: 开始时间（Unix时间戳，毫秒）
        end: 结束时间（Unix时间戳，毫秒）
        after: 分页参数（订单ID）
        limit: 返回数量（最大100，与OKX API一致）
    
    Returns:
        订单列表
    """
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
        
        # 如果有after参数，需要先查询该订单的时间，然后只查询更旧的数据
        if after:
            # 查询after订单的创建时间
            from sqlalchemy import text
            after_sql = text("SELECT c_time FROM order_history WHERE ord_id = :ord_id")
            after_result = session.execute(after_sql, {'ord_id': after}).fetchone()
            if after_result:
                # 只查询比after订单更旧的数据
                if end_dt is None or after_result[0] < end_dt:
                    end_dt = after_result[0]
        
        # 查询订单（使用offset=0，因为OKX API使用after参数分页，不是offset）
        orders = OrderHistoryRepository.get_orders(
            session,
            symbol=symbol,
            state=state,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit,
            offset=0
        )
        
        # 如果有after参数，过滤掉after订单本身及更新的订单
        if after:
            filtered_orders = []
            for order in orders:
                if order['ord_id'] == after:
                    break
                filtered_orders.append(order)
            orders = filtered_orders
        
        return {
            "status": "success",
            "count": len(orders),
            "limit": limit,
            "after": after,
            "orders": orders
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询历史订单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        session.close()


@router.get("/orders/{ord_id}")
async def get_order_by_id(ord_id: str):
    """
    根据订单ID查询订单详情
    
    Args:
        ord_id: 订单ID
    
    Returns:
        订单详情
    """
    session = db.get_session()
    try:
        # 直接查询数据库
        from sqlalchemy import text
        import json
        
        sql = text("""
            SELECT 
                ord_id, cl_ord_id, tag, inst_id, symbol, inst_type, ord_type, category,
                sz, px, side, pos_side, td_mode, lever,
                acc_fill_sz, fill_px, fill_time_ms, fill_time, trade_id, avg_px, state,
                tp_trigger_px, tp_ord_px, sl_trigger_px, sl_ord_px,
                fee, fee_ccy, rebate, rebate_ccy, pnl,
                c_time_ms, c_time, u_time_ms, u_time,
                raw_data, created_at, updated_at
            FROM order_history
            WHERE ord_id = :ord_id
        """)
        result = session.execute(sql, {'ord_id': ord_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail=f"订单 {ord_id} 不存在")
        
        order = {
            'ord_id': result[0],
            'cl_ord_id': result[1],
            'tag': result[2],
            'inst_id': result[3],
            'symbol': result[4],
            'inst_type': result[5],
            'ord_type': result[6],
            'category': result[7],
            'sz': float(result[8]) if result[8] else None,
            'px': float(result[9]) if result[9] else None,
            'side': result[10],
            'pos_side': result[11],
            'td_mode': result[12],
            'lever': result[13],
            'acc_fill_sz': float(result[14]) if result[14] else None,
            'fill_px': float(result[15]) if result[15] else None,
            'fill_time_ms': result[16],
            'fill_time': result[17].isoformat() if result[17] else None,
            'trade_id': result[18],
            'avg_px': float(result[19]) if result[19] else None,
            'state': result[20],
            'tp_trigger_px': float(result[21]) if result[21] else None,
            'tp_ord_px': float(result[22]) if result[22] else None,
            'sl_trigger_px': float(result[23]) if result[23] else None,
            'sl_ord_px': float(result[24]) if result[24] else None,
            'fee': float(result[25]) if result[25] else None,
            'fee_ccy': result[26],
            'rebate': float(result[27]) if result[27] else None,
            'rebate_ccy': result[28],
            'pnl': float(result[29]) if result[29] else None,
            'c_time_ms': result[30],
            'c_time': result[31].isoformat() if result[31] else None,
            'u_time_ms': result[32],
            'u_time': result[33].isoformat() if result[33] else None,
            'raw_data': result[34] if isinstance(result[34], dict) else (json.loads(result[34]) if result[34] else None),
            'created_at': result[35].isoformat() if result[35] else None,
            'updated_at': result[36].isoformat() if result[36] else None,
        }
        
        return {
            "status": "success",
            "order": order
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询订单详情失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        session.close()


@router.get("/symbols/{symbol}/stats")
async def get_symbol_stats(symbol: str):
    """
    获取某个币种的订单统计信息
    
    Args:
        symbol: 币种名称（BTC/ETH）
    
    Returns:
        统计信息
    """
    session = db.get_session()
    try:
        # 获取订单总数
        total_count = OrderHistoryRepository.get_order_count(session, symbol=symbol)
        
        # 获取最新订单ID
        latest_ord_id = OrderHistoryRepository.get_latest_order_id(session, symbol=symbol)
        
        # 按状态统计
        from sqlalchemy import text
        stats_sql = text("""
            SELECT state, COUNT(*) as count
            FROM order_history
            WHERE symbol = :symbol
            GROUP BY state
        """)
        state_stats = {}
        for row in session.execute(stats_sql, {'symbol': symbol}):
            state_stats[row[0]] = row[1]
        
        # 按方向统计
        side_sql = text("""
            SELECT side, COUNT(*) as count
            FROM order_history
            WHERE symbol = :symbol
            GROUP BY side
        """)
        side_stats = {}
        for row in session.execute(side_sql, {'symbol': symbol}):
            side_stats[row[0]] = row[1]
        
        return {
            "status": "success",
            "symbol": symbol,
            "total_count": total_count,
            "latest_ord_id": latest_ord_id,
            "state_stats": state_stats,
            "side_stats": side_stats
        }
        
    except Exception as e:
        logger.error(f"获取币种统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
    finally:
        session.close()

