"""
K线数据同步测试路由
"""
from fastapi import APIRouter, HTTPException
from app.database.connection import db
from app.database.klines import KlineRepository
from app.components.indicator_calculator import IndicatorCalculator
from app.utils.logger import logger

router = APIRouter(prefix="/kline-test", tags=["K线测试"])


@router.get("/status")
async def get_kline_status():
    """获取K线数据状态"""
    session = db.get_session()
    try:
        status = {}
        for timeframe in ['15m', '4h', '1d']:
            count = KlineRepository.get_kline_count(session, timeframe)
            latest_time = KlineRepository.get_latest_kline_time(session, timeframe)
            status[timeframe] = {
                'count': count,
                'latest_time': latest_time.isoformat() if latest_time else None
            }
        return status
    except Exception as e:
        logger.error(f"获取K线状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取K线状态失败: {str(e)}")
    finally:
        session.close()


@router.get("/data/{timeframe}")
async def get_kline_data(timeframe: str, limit: int = 10):
    """获取K线数据"""
    if timeframe not in ['15m', '4h', '1d']:
        raise HTTPException(status_code=400, detail="不支持的时间周期，支持: 15m, 4h, 1d")
    
    session = db.get_session()
    try:
        df = KlineRepository.get_klines_dataframe(session, timeframe, limit=limit)
        
        if df.empty:
            return {"message": "暂无K线数据", "data": []}
        
        # 转换为字典列表
        data = []
        for time, row in df.iterrows():
            data.append({
                'time': time.isoformat(),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
        
        return {
            "timeframe": timeframe,
            "count": len(data),
            "data": data
        }
    except Exception as e:
        logger.error(f"获取K线数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {str(e)}")
    finally:
        session.close()


@router.post("/calculate-indicators/{timeframe}")
async def calculate_indicators(timeframe: str):
    """手动触发技术指标计算"""
    if timeframe not in ['15m', '4h', '1d']:
        raise HTTPException(status_code=400, detail="不支持的时间周期，支持: 15m, 4h, 1d")
    
    try:
        calculator = IndicatorCalculator()
        success = calculator.update_latest_indicators(timeframe)
        
        if success:
            return {"message": f"{timeframe} 指标计算成功"}
        else:
            return {"message": f"{timeframe} 指标计算失败，可能数据不足"}
    except Exception as e:
        logger.error(f"计算指标失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"计算指标失败: {str(e)}")

