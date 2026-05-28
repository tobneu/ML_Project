from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from minecraft_skin_downloader import MinecraftSkinDownloader
import tensorflow as tf
import numpy as np
from rich import status

from tensorflow.keras import layers, Sequential


## Ignore this, our data agumentation layer may be required for the model to load correctly
# TODO: This can be resolved by building the model correctly
@tf.keras.utils.register_keras_serializable(package="Custom", name="RandomColorShift")
class RandomColorShift(layers.Layer):
    def __init__(self, shift_val=0.1, **kwargs):
        super().__init__(**kwargs)
        self.shift_val = shift_val

    def call(self, x, training=None):
        if not training:
            return x  # passthrough at inference
        rgb = x[..., :3]  # mask the R, G, B Values from x
        alpha = x[..., 3:4]  # mask alpha, dont change it
        noise = tf.random.uniform(tf.shape(rgb), -self.shift_val, self.shift_val)
        return tf.concat([tf.clip_by_value(rgb + noise, 0.0, 1.0), alpha], axis=-1)  # put data with noise together

    def get_config(self):
        config = super().get_config()
        config.update({
            "shift_val": self.shift_val
        })
        return config


data_augmentation = tf.keras.Sequential([
    RandomColorShift(0.1),
    layers.GaussianNoise(0.05),  # already respects training flag
])


app = FastAPI()

model = tf.keras.models.load_model("./model/best_model.keras")
model_threshold = 0.652

class PlayerCheckRequest(BaseModel):
    player_name: str
    player_id: str | None = None

@app.get("/")
def read_root():
    return {"message": "This is the minecraft skin safety gateway"}

# TODO: This is not a secure endpoint, just for demonstration and local use only :)
@app.post("/check/player/")
def check_player(request: PlayerCheckRequest):
    if request.player_name == "" and request.player_id == "":
        raise HTTPException(status_code=400)

    dl = MinecraftSkinDownloader()
    res = {
        "player_name": request.player_name,
        "score": 0.0,
        "risk": False
    }

    if request.player_id:
        res["player_id"] = request.player_id
        img_path = f"./data/skins/id/{request.player_id}.png"
        dl.download_by_uuid(request.player_id, img_path)
    else:
        img_path = f"./data/skins/name/{request.player_name}.png"
        dl.download_by_name(request.player_name, img_path)

    loaded_skin = load_skin(img_path)
    y = float(model.predict(loaded_skin)[0][0])

    res["score"] = y
    res["risk"] = y > model_threshold

    print(f"Score for {request.player_name}: {y:.4f} | Risk: {res['risk']}")
    return res

def load_skin(path: str):
    img = tf.keras.utils.load_img(path, color_mode="rgba", target_size=(64, 64))
    arr = tf.keras.utils.img_to_array(img) / 255.0  # normalize to [0, 1]
    return arr[np.newaxis, ...]

def preprocess_skin():
    pass

