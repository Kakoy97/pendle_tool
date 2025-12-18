import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.db import init_models
from app.services.smart_money_updater import smart_money_updater
from .routers import pendle, smart_money

logger = logging.getLogger(__name__)

# 前端文件目录
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="Pendle Tool API")

    # 添加 CORS 中间件，允许前端访问
    # 注意：CORS 中间件必须在所有路由之前添加
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 因为前后端在同一域名，可以允许所有来源
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 路由（必须在静态文件路由之前注册）
    app.include_router(pendle.router, prefix="/api")
    app.include_router(smart_money.router, prefix="/api")

    # 静态文件服务（CSS、JS等）
    if FRONTEND_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
        logger.info(f"静态文件目录已挂载: {FRONTEND_DIR}")
    else:
        logger.warning(f"前端目录不存在: {FRONTEND_DIR}")

    # 根路径返回 index.html（必须在通配路由之前）
    @app.get("/")
    async def read_root():
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "Pendle Tool API", "docs": "/docs"}

    # 其他路径也返回 index.html（用于前端路由，必须在最后注册）
    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        # 如果是 API 路径或静态文件路径，跳过（由其他路由处理）
        if path.startswith("api/") or path.startswith("static/") or path == "docs" or path == "openapi.json":
            return {"error": "Not found"}
        
        # 尝试返回对应的静态文件
        file_path = FRONTEND_DIR / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        
        # 否则返回 index.html（用于前端路由）
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        
        return {"error": "Not found"}

    @app.on_event("startup")
    async def startup_event() -> None:
        try:
            logger.info("正在初始化数据库...")
            await init_models()
            logger.info("数据库初始化完成")
            
            logger.info("正在启动聪明钱自动更新服务...")
            await smart_money_updater.start()
            logger.info("聪明钱自动更新服务启动完成")
            
            logger.info("应用启动完成！")
        except Exception as e:
            logger.error(f"应用启动失败: {e}", exc_info=True)
            # 不抛出异常，让服务器继续运行（即使 Telegram 监听器失败）
            logger.warning("应用将继续运行，但某些功能可能不可用")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        try:
            logger.info("正在停止聪明钱自动更新服务...")
            await smart_money_updater.stop()
            logger.info("聪明钱自动更新服务已停止")
        except Exception as e:
            logger.error(f"停止聪明钱自动更新服务时出错: {e}", exc_info=True)

    return app


app = create_app()
