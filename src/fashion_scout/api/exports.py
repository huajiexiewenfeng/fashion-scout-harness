from typing import Literal
from fastapi import Request
from starlette.responses import StreamingResponse
from .models import Operation
from fashion_scout.exports.jobs import Jobs


class CreateExport(Operation):
    selection: Literal['favorites']


def install_exports(app,paths,result):
    jobs=Jobs(paths)

    @app.post('/v1/exports')
    def create(payload:CreateExport,request:Request):
        jid,reused=jobs.create(payload.request_key,payload.selection)
        return result(request,{'export':jobs.get(jid),'reused':reused},200 if reused else 202)

    @app.get('/v1/exports/{jid}')
    def get(jid:str,request:Request):
        return result(request,{'export':jobs.get(jid)})

    @app.post('/v1/exports/{jid}/retry')
    def retry(jid:str,payload:Operation,request:Request):
        reused=jobs.retry(jid,payload.request_key)
        return result(request,{'export':jobs.get(jid),'reused':reused},200 if reused else 202)

    @app.get('/v1/exports/{jid}/download')
    def download(jid:str):
        stream,size=jobs.download(jid)
        def chunks():
            try:
                while data:=stream.read(1024*1024):yield data
            finally:stream.close()
        return StreamingResponse(chunks(),media_type='application/zip',headers={
            'Content-Length':str(size),'Content-Disposition':f'attachment; filename="fashion-scout-{jid}.zip"'})
