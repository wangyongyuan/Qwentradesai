"""
CoinGlass API测试接口
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from app.components.coinglass_client import CoinGlassClient
from app.config import settings
from app.utils.logger import logger

router = APIRouter(prefix="/coinglass-test", tags=["CoinGlass测试"])


@router.get("/config")
async def test_config() -> Dict[str, Any]:
    """测试CoinGlass配置"""
    return {
        "base_url": settings.COINGLASS_BASE_URL,
        "api_key_set": bool(settings.COINGLASS_API_KEY),
        "api_key_preview": settings.COINGLASS_API_KEY[:4] + "..." if settings.COINGLASS_API_KEY else None
    }


@router.get("/test/supported-coins")
async def test_supported_coins() -> Dict[str, Any]:
    """测试获取支持的币种列表"""
    try:
        client = CoinGlassClient(settings)
        result = client._request('/api/futures/supported-coins')
        
        if result is None:
            return {
                "success": False,
                "message": "API请求失败，请检查日志",
                "data": None
            }
        
        return {
            "success": True,
            "message": "获取成功",
            "data": result,
            "count": len(result) if isinstance(result, list) else "N/A"
        }
    except Exception as e:
        logger.error(f"测试支持的币种失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/test/open-interest/{symbol}")
async def test_open_interest(symbol: str) -> Dict[str, Any]:
    """测试获取未平仓合约数据（近一个月，4小时间隔）"""
    try:
        from datetime import datetime, timedelta, timezone
        
        client = CoinGlassClient(settings)
        
        # 查询近一个月的数据
        now = datetime.now(timezone.utc)
        end_time = int(now.timestamp() * 1000)
        start_time = int((now - timedelta(days=30)).timestamp() * 1000)
        
        result = client.get_open_interest_history(
            symbol=symbol,
            exchange="OKX",
            interval="4h",  # 使用4小时间隔
            start_time=start_time,
            end_time=end_time
        )
        
        if result is None:
            return {
                "success": False,
                "message": "API请求失败，可能是需要升级计划或参数错误",
                "data": None
            }
        
        return {
            "success": True,
            "message": "获取成功（近一个月，4小时间隔）",
            "data": result[:5] if isinstance(result, list) and len(result) > 5 else result,  # 只返回前5条
            "total_count": len(result) if isinstance(result, list) else "N/A",
            "query_params": {
                "symbol": symbol,
                "exchange": "OKX",
                "interval": "4h",
                "start_time": start_time,
                "end_time": end_time,
                "days": 30
            }
        }
    except Exception as e:
        logger.error(f"测试未平仓合约数据失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/test/long-short-ratio/{symbol}")
async def test_long_short_ratio(symbol: str) -> Dict[str, Any]:
    """测试获取多空持仓人数比数据"""
    try:
        client = CoinGlassClient(settings)
        result = client.get_long_short_ratio_history(
            symbol=symbol,
            exchange="Binance",
            interval="4h",
            limit=10  # 只获取10条测试
        )
        
        if result is None:
            return {
                "success": False,
                "message": "API请求失败，可能是需要升级计划或参数错误",
                "data": None
            }
        
        return {
            "success": True,
            "message": "获取成功",
            "data": result,
            "count": len(result) if isinstance(result, list) else "N/A"
        }
    except Exception as e:
        logger.error(f"测试多空持仓人数比失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/test/etf-flow/{symbol}")
async def test_etf_flow(symbol: str) -> Dict[str, Any]:
    """测试获取ETF资金流数据"""
    try:
        if symbol.upper() not in ['BTC', 'ETH']:
            raise HTTPException(status_code=400, detail="只支持BTC和ETH")
        
        client = CoinGlassClient(settings)
        result = client.get_etf_flow_history(symbol=symbol)
        
        if result is None:
            return {
                "success": False,
                "message": "API请求失败，可能是需要升级计划或参数错误",
                "data": None
            }
        
        return {
            "success": True,
            "message": "获取成功",
            "data": result[:5] if isinstance(result, list) and len(result) > 5 else result,  # 只返回前5条
            "total_count": len(result) if isinstance(result, list) else "N/A"
        }
    except Exception as e:
        logger.error(f"测试ETF资金流失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/test/fear-greed")
async def test_fear_greed() -> Dict[str, Any]:
    """测试获取恐惧贪婪指数数据"""
    try:
        client = CoinGlassClient(settings)
        result = client.get_fear_greed_history()
        
        if result is None:
            return {
                "success": False,
                "message": "API请求失败，可能是需要升级计划或参数错误",
                "data": None
            }
        
        # 检查数据格式
        values = result.get('values', [])
        prices = result.get('price_list', [])
        time_list = result.get('time_list', [])
        
        return {
            "success": True,
            "message": "获取成功",
            "data_structure": {
                "has_values": bool(values),
                "has_prices": bool(prices),
                "has_time_list": bool(time_list),
                "values_count": len(values) if isinstance(values, list) else 0,
                "prices_count": len(prices) if isinstance(prices, list) else 0,
                "time_list_count": len(time_list) if isinstance(time_list, list) else 0,
            },
            "sample_data": {
                "first_value": values[0] if values else None,
                "first_price": prices[0] if prices else None,
                "first_time": time_list[0] if time_list else None,
            } if values and prices and time_list else None,
            "full_data": result  # 返回完整数据用于调试
        }
    except Exception as e:
        logger.error(f"测试恐惧贪婪指数失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/test/all")
async def test_all() -> Dict[str, Any]:
    """测试所有CoinGlass API接口"""
    results = {}
    
    # 测试配置
    results["config"] = await test_config()
    
    # 测试支持的币种
    try:
        results["supported_coins"] = await test_supported_coins()
    except Exception as e:
        results["supported_coins"] = {"error": str(e)}
    
    # 测试未平仓合约（BTC）
    try:
        results["open_interest_btc"] = await test_open_interest("BTC")
    except Exception as e:
        results["open_interest_btc"] = {"error": str(e)}
    
    # 测试多空比（BTC）
    try:
        results["long_short_ratio_btc"] = await test_long_short_ratio("BTC")
    except Exception as e:
        results["long_short_ratio_btc"] = {"error": str(e)}
    
    # 测试ETF资金流（BTC）
    try:
        results["etf_flow_btc"] = await test_etf_flow("BTC")
    except Exception as e:
        results["etf_flow_btc"] = {"error": str(e)}
    
    # 测试恐惧贪婪指数
    try:
        results["fear_greed"] = await test_fear_greed()
    except Exception as e:
        results["fear_greed"] = {"error": str(e)}
    
    return {
        "summary": {
            "total_tests": len(results),
            "successful": sum(1 for r in results.values() if isinstance(r, dict) and r.get("success") is True),
            "failed": sum(1 for r in results.values() if isinstance(r, dict) and r.get("success") is False),
        },
        "results": results
    }

