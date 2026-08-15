from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://pie:pie_password@localhost:5432/pie_db"
    debug: bool = False
    # Set only by the native-Windows-port launcher (issue #82) - the containerized deployment
    # leaves this unset, since the frontend runs via its own Vite dev server / HAProxy there.
    frontend_dist_dir: str | None = None


settings = Settings()
