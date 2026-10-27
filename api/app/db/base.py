from sqlalchemy.orm import DeclarativeBase

#The parent class every model will inherit from. It collects all table definitions in Base.metadata, 
#which Alembic reads later.

class Base(DeclarativeBase):
    pass

