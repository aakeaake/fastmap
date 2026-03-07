from fastapi import FastAPI
from fastmap.api.routes import router

app = FastAPI(title="FastMap API", version="0.1.0")

app.include_router(router)