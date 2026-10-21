from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database: str
    username: str
    password: str
    secret: str

    @classmethod
    def load(cls):
        load_dotenv(ROOT / '.env', override=False)
        return cls(os.getenv('DB_HOST', '127.0.0.1'), int(os.getenv('DB_PORT', '3307')),
                   os.getenv('DB_NAME', 'algorithm_review'), os.getenv('DB_USER', ''),
                   os.getenv('DB_PASSWORD', ''), os.getenv('APP_SECRET', ''))

    def url(self):
        if not self.username or not self.password or len(self.secret) < 32:
            raise ValueError('Database credentials and APP_SECRET must be configured locally.')
        return URL.create('mysql+pymysql', username=self.username, password=self.password,
                          host=self.host, port=self.port, database=self.database,
                          query={'charset': 'utf8mb4'})
