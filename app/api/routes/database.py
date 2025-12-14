"""
数据库测试路由
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from app.database.connection import db
from app.utils.logger import logger

router = APIRouter(prefix="/database", tags=["数据库"])


@router.get("/test")
async def test_database():
    """测试数据库连接"""
    try:
        session = db.get_session()
        try:
            # 测试查询
            result = session.execute(text("SELECT 1"))
            result.fetchone()
            
            # 查询表数量
            result = session.execute(
                text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
            )
            table_count = result.scalar()
            
            return {
                "status": "success",
                "message": "数据库连接正常",
                "table_count": table_count
            }
        finally:
            session.close()
    except Exception as e:
        logger.error(f"数据库连接失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"数据库连接失败: {str(e)}")


@router.get("/tables")
async def list_tables():
    """列出所有表"""
    try:
        session = db.get_session()
        try:
            result = session.execute(
                text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
            )
            tables = [row[0] for row in result]
            
            return {
                "status": "success",
                "tables": tables,
                "count": len(tables)
            }
        finally:
            session.close()
    except Exception as e:
        logger.error(f"查询表列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")

