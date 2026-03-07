from pydantic import BaseModel

class MapRequest(BaseModel):
    lat: float
    lon: float
    scale: int
    paper_size: str
    orientation: str