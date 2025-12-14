"""
健康检查路由
"""
from fastapi import APIRouter
from app.utils.logger import logger

router = APIRouter(prefix="/health", tags=["健康检查"])


@router.get("")
async def health_check():
    """健康检查"""
    logger.info("健康检查请求")
    return {
        "status": "ok",
        "message": "QwenTradeAI is running"
    }

