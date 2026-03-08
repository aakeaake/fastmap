from fastapi import FastAPI
from fastmap.api.routes import router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="FastMap API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:5500"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # expose Content-Disposition so frontend fetch() can read the filename
    expose_headers=["Content-Disposition"],
)
app.include_router(router)