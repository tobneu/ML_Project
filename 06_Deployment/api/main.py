from fastapi import FastAPI, HTTPException, Form
from pydantic import BaseModel
from rich import status

app = FastAPI()

class PlayerCheckRequest(BaseModel):
    player_name: str
    player_id: str | None = None

@app.get("/")
def read_root():
    return {"message": "This is the minecraft skin safety gateway"}

@app.post("/check/player/")
def check_player(request: PlayerCheckRequest):
    if request.player_name == "" and request.player_id == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    # path 1: PlayerId call
    if request.player_id != None:
        return {"player_name": request.player_name, "player_id": request.player_id}
    else :
        return {"player_name": request.player_name}

