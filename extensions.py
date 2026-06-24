"""Shared extension instances, created unbound and initialised in the factory."""

from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy

# Database handle. Bound to the app in create_app() via db.init_app(app).
db = SQLAlchemy()
