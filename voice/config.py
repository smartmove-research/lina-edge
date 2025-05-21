import json

class Config:
    _config = None
    
    @classmethod
    def get_config(cls):
        if cls._config is None:
            cls.reload_config()
        return cls._config
    
    @classmethod
    def reload_config(cls):
        with open("settings.json", "r") as f:
            cls._config = json.load(f)