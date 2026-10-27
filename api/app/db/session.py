from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)

# A factory that creates sessions.Calling SessionLocal() gives you one conversation with the database.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

# autoflush=False means changes are sent to the DB only when you commit or flush, not silently before every query.
# expire_on_commit=False keeps objects readable after commit(). Without it, returning a freshly created user from a route triggers an extra query or an error.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


#NOTE: A good line for your notes: engine = once per database per process; session = once per request.



#!Learning :  Dont have Many Engines 
# health.py still has its own engine. That’s fine for now. You can switch it to import engine from session.py later so there is only one.

'''
=> One engine per database, shared by the whole app. That's the standard practice.

An engine owns a connection pool: a set of already-open connections to Postgres that requests borrow and 
return. Opening a new connection is slow, so the pool reuses them. If you create many engines for the 
same database, you get many separate pools, each holding its own connections. Postgres has a limit on 
total connections (100 by default), so extra engines waste them and can exhaust the limit, with errors 
like “too many clients”.

The engine is also built to be shared: it is thread-safe, and you create it once at startup and keep it 
for the life of the process. Sessions are the cheap, short-lived thing you create per request. Engines 
are the expensive, long-lived thing you create once.

'''

#! When should we have more than one (many engine) ? 

'''
=>Different databases, for example one engine for the main Postgres and another for an analytics DB or a 
  read replica.
=>Different pool settings for a special workload.
=>Separate processes. Your API and your agent worker each have their own engine, because they are separate 
  programs. That is normal and expected.
  
'''
