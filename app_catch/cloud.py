"""Authenticated single-workspace control plane. PostgreSQL production, SQLite tests."""
import hashlib
import secrets
import hmac
import os
import time
import uuid
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Float,
                        Integer, JSON, select, update, and_, or_, UniqueConstraint)
from sqlalchemy.exc import IntegrityError
from .core import valid_context, validate_bundle, digest

metadata = MetaData()
jobs = Table('ac_jobs', metadata,
    Column('id', String, primary_key=True), Column('request_key', String, unique=True),
    Column('payload', JSON, nullable=False), Column('state', String, nullable=False),
    Column('lease', String), Column('lease_until', Float), Column('attempts', Integer, default=0),
    Column('created_at', Float), Column('result_hash', String), Column('error_code', String))
results = Table('ac_results', metadata,
    Column('job_id', String, primary_key=True), Column('hash', String), Column('bundle', JSON))
nodes = Table('ac_nodes', metadata, Column('id', String, primary_key=True), Column('last_seen', Float))

sessions = Table('ac_sessions', metadata, Column('hash', String, primary_key=True), Column('expires', Float))

class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)

class Submit(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    recipe: str = Field(pattern=r'^[a-z0-9-]{1,60}$')
    context: dict

class Lease(BaseModel):
    lease: str = Field(min_length=20, max_length=100)

class Finish(Lease):
    bundle: dict

class Failure(Lease):
    code: str = Field(pattern=r'^[A-Z_]{1,60}$')

class Queue:
    def __init__(self, url, clock=time.time):
        kwargs = {'connect_args': {'check_same_thread': False}} if url.startswith('sqlite') else {}
        self.engine = create_engine(url, **kwargs)
        self.clock = clock
        metadata.create_all(self.engine)

    def submit(self, value):
        valid_context(value['context'])
        payload = {'recipe': value['recipe'], 'context': value['context']}
        identity = str(uuid.uuid4())
        try:
            with self.engine.begin() as con:
                con.execute(jobs.insert().values(id=identity, request_key=value['request_key'],
                    payload=payload, state='PENDING', attempts=0, created_at=self.clock()))
        except IntegrityError:
            with self.engine.connect() as con:
                old = con.execute(select(jobs).where(jobs.c.request_key == value['request_key'])).mappings().one()
            if old['payload'] != payload:
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            identity = old['id']
        return {'id': identity}

    def claim(self):
        now = self.clock()
        eligible = or_(jobs.c.state == 'PENDING', and_(jobs.c.state == 'RUNNING', jobs.c.lease_until <= now))
        with self.engine.begin() as con:
            con.execute(update(jobs).where(eligible, jobs.c.attempts >= 5).values(state='FAILED', error_code='ATTEMPTS_EXHAUSTED'))
            row = con.execute(select(jobs).where(eligible, jobs.c.attempts < 5)
                .order_by(jobs.c.created_at).limit(1).with_for_update(skip_locked=True)).mappings().first()
            if not row:
                return None
            token = str(uuid.uuid4())
            changed = con.execute(update(jobs).where(jobs.c.id == row['id'], eligible,
                jobs.c.attempts == row['attempts']).values(state='RUNNING', lease=token,
                lease_until=now+60, attempts=row['attempts']+1)).rowcount
            if not changed:
                return None
            return {'id': row['id'], 'lease': token, 'payload': row['payload']}

    def active(self, identity, lease):
        return and_(jobs.c.id == identity, jobs.c.state == 'RUNNING',
                    jobs.c.lease == lease, jobs.c.lease_until > self.clock())

    def heartbeat(self, identity, lease):
        with self.engine.begin() as con:
            if not con.execute(update(jobs).where(self.active(identity, lease)).values(lease_until=self.clock()+60)).rowcount:
                raise HTTPException(409, 'LEASE_LOST')
        return {'ok': True}

    def finish(self, identity, lease, bundle):
        validate_bundle(bundle)
        if len({r['listing_key'] for r in bundle['rows']}) != len(bundle['rows']):
            raise ValueError('DUPLICATE_ROWS')
        fingerprint = digest(bundle)
        with self.engine.begin() as con:
            row = con.execute(select(jobs).where(jobs.c.id == identity).with_for_update()).mappings().first()
            if not row:
                raise HTTPException(404, 'NOT_FOUND')
            if row['state'] in ('SUCCEEDED', 'PARTIAL') and row['lease'] == lease and row['result_hash'] == fingerprint:
                return {'ok': True, 'duplicate': True}
            if bundle['context'] != row['payload']['context']:
                raise HTTPException(409, 'CONTEXT_MISMATCH')
            if not con.execute(update(jobs).where(self.active(identity, lease)).values(
                    state=bundle['status'], result_hash=fingerprint)).rowcount:
                raise HTTPException(409, 'LEASE_LOST')
            con.execute(results.insert().values(job_id=identity, hash=fingerprint, bundle=bundle))
        return {'ok': True, 'duplicate': False}

    def fail(self, identity, lease, code):
        with self.engine.begin() as con:
            if not con.execute(update(jobs).where(self.active(identity, lease)).values(state='FAILED', error_code=code)).rowcount:
                raise HTTPException(409, 'LEASE_LOST')
        return {'ok': True}

    def cancel(self, identity):
        with self.engine.begin() as con:
            n = con.execute(update(jobs).where(jobs.c.id == identity,
                jobs.c.state.in_(['PENDING', 'RUNNING'])).values(state='CANCELLED', lease=None)).rowcount
        return {'cancelled': bool(n)}

    def list_jobs(self):
        with self.engine.connect() as con:
            return [dict(r) for r in con.execute(select(jobs.c.id, jobs.c.payload, jobs.c.state,
                jobs.c.attempts, jobs.c.error_code, jobs.c.created_at).order_by(jobs.c.created_at.desc()).limit(100)).mappings()]


def create_app(database_url=None, admin_token=None, worker_token=None, clock=time.time):
    database_url = database_url or os.environ['AC_DATABASE_URL']
    admin_token = admin_token or os.environ['AC_ADMIN_TOKEN']
    worker_token = worker_token or os.environ['AC_WORKER_TOKEN']
    if min(len(admin_token), len(worker_token)) < 32 or admin_token == worker_token:
        raise ValueError('Use distinct random admin and worker tokens of at least 32 characters')
    if os.getenv('AC_ENV') == 'production' and not database_url.startswith('postgresql+psycopg://'):
        raise ValueError('Production requires dedicated PostgreSQL')
    queue = Queue(database_url, clock)
    app = FastAPI(title='App Catch Control Plane', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.queue = queue
    bearer = HTTPBearer(auto_error=False)
    def auth(expected):
        def verify(request: Request, value: Optional[HTTPAuthorizationCredentials] = Depends(bearer)):
            if value and hmac.compare_digest(value.credentials, expected):
                return
            if expected == admin_token:
                token = request.cookies.get('ac_session', '')
                with queue.engine.connect() as con:
                    match = con.execute(select(sessions).where(sessions.c.hash == hashlib.sha256(token.encode()).hexdigest(), sessions.c.expires > clock())).first()
                if match and token:
                    if request.method not in ('GET','HEAD') and request.headers.get('X-Requested-With') != 'appcatch':
                        raise HTTPException(403, 'CSRF_REQUIRED')
                    return
            raise HTTPException(401, 'UNAUTHORIZED')
        return verify
    admin, worker = auth(admin_token), auth(worker_token)

    @app.exception_handler(ValueError)
    async def contract_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={'detail': 'INVALID_DATA_CONTRACT'})

    @app.middleware('http')
    async def bounded_body(request, call_next):
        from fastapi.responses import JSONResponse
        from urllib.parse import urlsplit
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse(status_code=403,content={'detail':'ORIGIN_REJECTED'})
        if request.method in ('POST', 'PUT'):
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 4*1024*1024:
                    return JSONResponse(status_code=413, content={'detail': 'BODY_TOO_LARGE'})
            request._body = bytes(body)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/healthz')
    def health():
        with queue.engine.connect() as con:
            con.execute(select(1))
        return {'status': 'ok', 'release': os.getenv('AC_RELEASE', 'local'), 'protocol': 1}

    @app.post('/api/jobs', dependencies=[Depends(admin)])
    def submit(value: Submit):
        return queue.submit(value.model_dump())

    @app.get('/api/jobs', dependencies=[Depends(admin)])
    def listing():
        return queue.list_jobs()

    @app.post('/api/jobs/{identity}/cancel', dependencies=[Depends(admin)])
    def cancel(identity: str):
        return queue.cancel(identity)

    @app.get('/api/jobs/{identity}/result', dependencies=[Depends(admin)])
    def result(identity: str):
        with queue.engine.connect() as con:
            row = con.execute(select(results.c.bundle).where(results.c.job_id == identity)).first()
        if not row:
            raise HTTPException(404, 'RESULT_NOT_AVAILABLE')
        return row[0]

    @app.get('/api/jobs/{identity}', dependencies=[Depends(admin)])
    def job_detail(identity: str):
        with queue.engine.connect() as con:
            row=con.execute(select(jobs.c.id,jobs.c.payload,jobs.c.state,jobs.c.attempts,jobs.c.created_at,jobs.c.error_code).where(jobs.c.id==identity)).mappings().first()
        if not row:raise HTTPException(404,'NOT_FOUND')
        return dict(row)

    @app.post('/worker/claim', dependencies=[Depends(worker)])
    def claim():
        with queue.engine.begin() as con:
            if not con.execute(update(nodes).where(nodes.c.id == 'mac-1').values(last_seen=clock())).rowcount:
                con.execute(nodes.insert().values(id='mac-1', last_seen=clock()))
        return {'task': queue.claim()}

    @app.post('/worker/jobs/{identity}/heartbeat', dependencies=[Depends(worker)])
    def heartbeat(identity: str, value: Lease):
        result=queue.heartbeat(identity, value.lease)
        with queue.engine.begin() as con:con.execute(update(nodes).where(nodes.c.id=='mac-1').values(last_seen=clock()))
        return result

    @app.post('/worker/jobs/{identity}/finish', dependencies=[Depends(worker)])
    def finish(identity: str, value: Finish):
        return queue.finish(identity, value.lease, value.bundle)

    @app.post('/worker/jobs/{identity}/fail', dependencies=[Depends(worker)])
    def fail(identity: str, value: Failure):
        return queue.fail(identity, value.lease, value.code)

    from pathlib import Path
    from fastapi.responses import FileResponse
    static = Path(__file__).parent/'static'
    attempts = {}
    @app.post('/auth/login')
    def login(request: Request, response: Response, value: Login):
        ip = request.client.host if request.client else 'unknown'
        recent = [t for t in attempts.get(ip,[]) if t > clock()-300]
        if len(recent) >= 10: raise HTTPException(429,'LOGIN_RATE_LIMIT')
        recent.append(clock()); attempts[ip]=recent
        password = os.getenv('AC_ADMIN_PASSWORD','')
        if len(password)<12 or not hmac.compare_digest(value.password,password):
            raise HTTPException(401,'INVALID_LOGIN_OR_NOT_CONFIGURED')
        token = secrets.token_urlsafe(40)
        with queue.engine.begin() as con:
            con.execute(sessions.delete().where(sessions.c.expires < clock()))
            con.execute(sessions.insert().values(hash=hashlib.sha256(token.encode()).hexdigest(),expires=clock()+12*3600))
        response.set_cookie('ac_session',token,httponly=True,secure=os.getenv('AC_ENV')=='production',samesite='strict',max_age=12*3600)
        return {'ok':True}
    @app.post('/auth/logout', dependencies=[Depends(admin)])
    def logout(request:Request,response:Response):
        token=request.cookies.get('ac_session','')
        with queue.engine.begin() as con:con.execute(sessions.delete().where(sessions.c.hash==hashlib.sha256(token.encode()).hexdigest()))
        response.delete_cookie('ac_session');return {'ok':True}
    @app.get('/')
    def home(): return FileResponse(static/'index.html')
    @app.get('/collections/{identity}')
    @app.get('/reports/{identity}')
    def detail_page(identity:str):return FileResponse(static/'index.html')
    @app.get('/assets/{name}')
    def asset(name:str):
        if name not in ('app.js','lab.js','style.css'):raise HTTPException(404)
        return FileResponse(static/name)
    from .product import register
    register(app,queue,admin)
    from .lab import register as register_lab
    register_lab(app,queue,admin)
    return app
